import asyncio
import json
import logging
import websockets
from typing import Any, Dict, List, Optional

logger = logging.getLogger("spruthub")

class SprutHubClient:
    def __init__(self, ws_url: str, token: str, serial: str):
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
                    "serial": self.serial,
                    "params": formatted_params
                }
                
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
        return await self.call("hub.get", {"serial": self.serial})

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

    async def close(self):
        if self._ws:
            await self._ws.close()
            self._ws = None
