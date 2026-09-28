import asyncio
import json
import logging
import websockets
from typing import Any, Dict, List, Optional

import os
from pathlib import Path

logger = logging.getLogger("spruthub")


def normalize_ws_url(raw: str) -> str:
    """Normalize a host, IP, or URL into a valid SprutHub WebSocket URL."""
    raw = (raw or "").strip()
    if not raw:
        return "ws://127.0.0.1/spruthub"

    if raw.startswith("ws://") or raw.startswith("wss://"):
        if not raw.endswith("/spruthub"):
            raw = raw.rstrip("/") + "/spruthub"
        return raw

    if raw.startswith("http://"):
        raw = "ws://" + raw[7:]
    elif raw.startswith("https://"):
        raw = "wss://" + raw[8:]
    else:
        # Bare IP or hostname (e.g. 192.168.1.100 or spruthub.local)
        raw = f"ws://{raw}"

    if not raw.endswith("/spruthub"):
        raw = raw.rstrip("/") + "/spruthub"

    return raw


def load_config() -> dict[str, Any]:
    """Load SprutHub configuration from env vars, XDG/AppData, or local config.json."""
    config: dict[str, Any] = {}

    # 1. Check local file (development / workspace)
    local_cfg = Path("config.json")
    if local_cfg.exists():
        try:
            with open(local_cfg, "r", encoding="utf-8") as f:
                config.update(json.load(f))
        except Exception as e:
            logger.debug(f"Failed to load {local_cfg}: {e}")

    # 2. Check XDG / system config (~/.config/spruthub/config.json or %APPDATA%/spruthub/config.json)
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        sys_cfg = Path(appdata) / "spruthub" / "config.json" if appdata else None
    else:
        xdg_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        sys_cfg = Path(xdg_home) / "spruthub" / "config.json"

    if sys_cfg and sys_cfg.exists():
        try:
            with open(sys_cfg, "r", encoding="utf-8") as f:
                for k, v in json.load(f).items():
                    if k not in config:
                        config[k] = v
        except Exception as e:
            logger.debug(f"Failed to load {sys_cfg}: {e}")

    # 3. Environment variables have the highest priority
    if os.environ.get("SPRUTHUB_HOST"):
        config["host"] = os.environ["SPRUTHUB_HOST"]
    if os.environ.get("SPRUTHUB_IP"):
        config["host"] = os.environ["SPRUTHUB_IP"]
    if os.environ.get("SPRUTHUB_WS_URL"):
        config["ws_url"] = os.environ["SPRUTHUB_WS_URL"]
    if os.environ.get("SPRUTHUB_TOKEN"):
        config["token"] = os.environ["SPRUTHUB_TOKEN"]
    if os.environ.get("SPRUTHUB_SERIAL"):
        config["serial"] = os.environ["SPRUTHUB_SERIAL"]

    # Determine and normalize final ws_url
    raw_host = config.get("host") or config.get("ip") or config.get("ws_url") or "127.0.0.1"
    config["ws_url"] = normalize_ws_url(raw_host)

    return config


class SprutHubClient:
    def __init__(self, ws_url: str, token: str, serial: Optional[str] = None):
        self.ws_url = ws_url
        self.token = token
        self.serial = serial
        self._ws = None
        self._req_id = 0
        self._lock = asyncio.Lock()

    async def connect(self):
        if self._ws is None or self._ws.state is not websockets.State.OPEN:
            self._ws = await websockets.connect(
                self.ws_url,
                subprotocols=["json-rpc"],
                origin="http://spruthub.local",
                max_size=20 * 1024 * 1024
            )

    async def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        async with self._lock:
            try:
                await self.connect()
                self._req_id += 1
                cur_id = self._req_id
                
                parts = method.split(".", 1)
                if len(parts) == 2:
                    formatted_params = {parts[0]: {parts[1]: params or {}}}
                else:
                    formatted_params = {method: params or {}}

                msg = {
                    "id": cur_id,
                    "token": self.token,
                    "params": formatted_params
                }
                if self.serial:
                    msg["serial"] = self.serial
                
                await self._ws.send(json.dumps(msg))
                
                while True:
                    resp_text = await self._ws.recv()
                    data = json.loads(resp_text)
                    
                    # Skip background event frames and wait for response matching our request ID
                    if "id" in data and data["id"] == cur_id:
                        if "error" in data:
                            raise RuntimeError(f"SprutHub RPC Error: {data['error']}")
                        res = data.get("result", {})
                        if len(parts) == 2 and parts[0] in res and parts[1] in res[parts[0]]:
                            return res[parts[0]][parts[1]]
                        return res
            except (websockets.ConnectionClosed, OSError) as e:
                self._ws = None
                raise RuntimeError(f"SprutHub connection lost: {e}") from e

    async def get_hub_info(self) -> Dict[str, Any]:
        if self.serial:
            try:
                return await self.call("hub.get", {"serial": self.serial})
            except Exception:
                pass
        
        # Fallback to hub.list which does not require serial and works for any hub
        res = await self.call("hub.list", {})
        hubs = res.get("hubs", [])
        if hubs:
            hub = hubs[0]
            if not self.serial and hub.get("serial"):
                self.serial = hub["serial"]
            return hub
        return {}

    async def list_rooms(self) -> List[Dict[str, Any]]:
        res = await self.call("room.list", {})
        return res.get("rooms", [])

    async def get_accessory(self, accessory_id: int) -> Dict[str, Any]:
        return await self.call("accessory.get", {"id": accessory_id, "expand": "services,characteristics"})

    async def list_accessories(self) -> List[Dict[str, Any]]:
        res = await self.call("accessory.list", {"expand": "services,characteristics"})
        return res.get("accessories", [])

    async def update_characteristic(self, a_id: int, s_id: int, c_id: int, value: Any) -> Dict[str, Any]:
        val_obj = {}
        if isinstance(value, bool):
            val_obj = {"boolValue": value}
        elif isinstance(value, int):
            val_obj = {"intValue": value}
        elif isinstance(value, float):
            val_obj = {"doubleValue": value}
        elif isinstance(value, str):
            val_obj = {"stringValue": value}
        else:
            val_obj = {"stringValue": str(value)}

        payload = {
            "aId": a_id,
            "sId": s_id,
            "cId": c_id,
            "control": {
                "value": val_obj
            }
        }
        return await self.call("characteristic.update", payload)

    async def get_history(
        self,
        accessory_id: int,
        service_id: Optional[int] = None,
        characteristic_id: Optional[int] = None,
        after_timestamp: Optional[int] = None,
        before_timestamp: Optional[int] = None,
        after_id: Optional[int] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        acc_filter: Dict[str, Any] = {"aId": accessory_id}
        if service_id is not None:
            acc_filter["sId"] = service_id
        if characteristic_id is not None:
            acc_filter["cId"] = characteristic_id

        params: Dict[str, Any] = {
            "filter": {"accessories": [acc_filter]},
            "limit": limit,
        }
        if after_timestamp is not None:
            params["afterTimestamp"] = after_timestamp
        if before_timestamp is not None:
            params["beforeTimestamp"] = before_timestamp
        if after_id is not None:
            params["afterId"] = after_id

        res = await self.call("history.list", params)
        return res.get("histories", [])

    async def get_history_range(
        self,
        accessory_id: int,
        service_id: Optional[int] = None,
        characteristic_id: Optional[int] = None,
        days: Optional[float] = None,
        hours: Optional[float] = None,
        max_records: int = 10000,
    ) -> List[Dict[str, Any]]:
        import time

        cutoff_ms: Optional[int] = None
        now_ms = int(time.time() * 1000)
        if days is not None:
            cutoff_ms = int(now_ms - days * 86400 * 1000)
        elif hours is not None:
            cutoff_ms = int(now_ms - hours * 3600 * 1000)

        all_records = []
        after_id = None
        limit = 500

        while len(all_records) < max_records:
            cur_limit = min(limit, max_records - len(all_records))
            records = await self.get_history(
                accessory_id=accessory_id,
                service_id=service_id,
                characteristic_id=characteristic_id,
                after_id=after_id,
                limit=cur_limit,
            )
            if not records:
                break

            all_records.extend(records)
            after_id = records[-1]["id"]

            if cutoff_ms is not None:
                oldest_ts = records[-1].get("timestamp", 0)
                if oldest_ts < cutoff_ms:
                    break

            if len(records) < cur_limit:
                break

        if cutoff_ms is not None:
            all_records = [r for r in all_records if r.get("timestamp", 0) >= cutoff_ms]

        return all_records

    async def list_scenarios(self) -> List[Dict[str, Any]]:
        res = await self.call("scenario.list", {})
        return res.get("scenarios", [])

    async def run_scenario(self, index: str) -> Any:
        return await self.call("scenario.run", {"index": str(index)})

    async def get_logs(self, count: int = 50) -> List[Dict[str, Any]]:
        res = await self.call("log.list", {"count": count})
        return res.get("log", [])

    async def list_extensions(self) -> List[Dict[str, Any]]:
        res = await self.call("extension.list", {})
        return res.get("extensions", [])

    async def restart_hub(self) -> Any:
        payload = {"serial": self.serial} if self.serial else {}
        return await self.call("hub.restart", payload)

    async def create_room(self, name: str) -> Dict[str, Any]:
        return await self.call("room.create", {"name": name.strip()})

    async def update_room(
        self,
        room_id: int,
        name: Optional[str] = None,
        visible: Optional[bool] = None,
        order: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"id": room_id}
        if name is not None:
            payload["name"] = name.strip()
        if visible is not None:
            payload["visible"] = visible
        if order is not None:
            payload["order"] = order
        return await self.call("room.update", payload)

    async def delete_room(self, room_id: int) -> Dict[str, Any]:
        return await self.call("room.delete", {"id": room_id})

    async def list_catalog(
        self,
        search: Optional[str] = None,
        limit: int = 50,
        filter_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {"limit": limit}
        if search:
            payload["search"] = search.strip()
        if filter_params:
            payload["filter"] = filter_params
        res = await self.call("catalog.list", payload)
        return res.get("catalogs", [])

    async def get_catalog(self, store: str, controller: str, file: str) -> Dict[str, Any]:
        payload = {
            "store": store,
            "controller": controller,
            "file": file,
        }
        res = await self.call("catalog.get", payload)
        return res.get("catalog", res)

    async def close(self):
        if self._ws:
            await self._ws.close()
            self._ws = None


