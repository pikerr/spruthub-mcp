import os
import sys
import json
import logging
from typing import Any, Dict, List, Optional, Union
from pathlib import Path

# Add current folder to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from mcp.server.mcpserver import MCPServer
from spruthub_client import SprutHubClient, load_config

# Configure logging to stderr (stdio is reserved for JSON-RPC MCP messages)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger("spruthub-mcp")

# Load configuration (env vars > XDG/AppData > local config.json)
config = load_config()

WS_URL = config.get("ws_url", "ws://127.0.0.1/spruthub")
TOKEN = config.get("token", "")
SERIAL = config.get("serial", None)

if not TOKEN:
    logger.warning("SPRUTHUB_TOKEN is not set. Tools requiring hub communication will fail until configured.")

client = SprutHubClient(ws_url=WS_URL, token=TOKEN, serial=SERIAL)

# Initialize MCP Server
app = MCPServer(
    name="SprutHub",
    version="1.0.0",
    instructions="MCP Server for controlling and monitoring SprutHub smart home devices (switches, sensors, lights, rooms)."
)


def _extract_val(val_dict: Optional[Dict[str, Any]]) -> Any:
    if not val_dict or not isinstance(val_dict, dict):
        return val_dict
    for k in ("boolValue", "intValue", "longValue", "doubleValue", "stringValue"):
        if k in val_dict:
            return val_dict[k]
    return val_dict


@app.tool()
async def sprut_get_hub_info() -> Dict[str, Any]:
    """Get general information about the SprutHub controller (name, model, firmware version, online status)."""
    info = await client.get_hub_info()
    return {
        "name": info.get("name"),
        "model": info.get("model"),
        "manufacturer": info.get("manufacturer"),
        "serial": info.get("serial"),
        "online": info.get("online"),
        "version": info.get("version", {}).get("current", {}).get("version"),
        "platform": info.get("platform", {}).get("model")
    }


@app.tool()
async def sprut_list_rooms() -> List[Dict[str, Any]]:
    """List all rooms in the smart home with their IDs, names, and sensor summary."""
    rooms = await client.list_rooms()
    result = []
    for r in rooms:
        result.append({
            "room_id": r.get("id"),
            "name": r.get("name"),
            "sensors": [s.get("label") for s in r.get("sensors", []) if s.get("label")],
            "actions_count": len(r.get("actions", []))
        })
    return result


@app.tool()
async def sprut_list_devices(room_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """List smart home accessories / devices with their controllable services and current values.
    
    Args:
        room_id: Optional filter to list devices only in a specific room.
    """
    accessories = await client.list_accessories()
    devices = []
    
    for a in accessories:
        a_id = a.get("id")
        a_name = a.get("name")
        a_room = a.get("roomId") or a.get("room")
        
        if room_id is not None and a_room != room_id:
            continue
            
        services_summary = []
        for s in a.get("services", []):
            s_type = s.get("type")
            if s_type == "AccessoryInformation":
                continue
                
            chars_summary = []
            for c in s.get("characteristics", []):
                ctl = c.get("control", {})
                c_name = ctl.get("type") or ctl.get("name")
                if c_name in ("Name", "Identify", "C_Online"):
                    continue
                val = _extract_val(ctl.get("value"))
                chars_summary.append({
                    "cId": c.get("cId"),
                    "name": c_name,
                    "value": val,
                    "writeable": ctl.get("write", False)
                })
                
            if chars_summary:
                services_summary.append({
                    "sId": s.get("sId"),
                    "type": s_type,
                    "characteristics": chars_summary
                })
                
        devices.append({
            "accessory_id": a_id,
            "name": a_name,
            "room_id": a_room,
            "services": services_summary
        })
        
    return devices


@app.tool()
async def sprut_get_device(accessory_id: int) -> Dict[str, Any]:
    """Get complete details and all characteristics of a specific accessory.
    
    Args:
        accessory_id: The ID of the accessory (e.g. 1155).
    """
    acc = await client.get_accessory(accessory_id)
    return acc


@app.tool()
async def sprut_set_switch(accessory_id: int, on: bool, service_id: Optional[int] = None) -> str:
    """Turn a switch, light, or relay ON or OFF.
    
    Args:
        accessory_id: The ID of the accessory (e.g. 1155).
        on: True to turn ON, False to turn OFF.
        service_id: Optional service ID if the accessory has multiple switches. If omitted, the first Switch service is used automatically.
    """
    acc = await client.get_accessory(accessory_id)
    target_sid = None
    target_cid = None
    
    for s in acc.get("services", []):
        if service_id is not None and s.get("sId") != service_id:
            continue
        if s.get("type") in ("Switch", "Lightbulb", "Outlet"):
            for c in s.get("characteristics", []):
                ctl = c.get("control", {})
                if ctl.get("type") == "On" or "boolValue" in ctl.get("value", {}):
                    target_sid = s.get("sId")
                    target_cid = c.get("cId")
                    break
            if target_sid:
                break
                
    if target_sid is None or target_cid is None:
        return f"Error: No controllable switch/on-off characteristic found on accessory {accessory_id}"
        
    await client.update_characteristic(
        a_id=accessory_id,
        s_id=target_sid,
        c_id=target_cid,
        value=on
    )
    status_str = "ON (true)" if on else "OFF (false)"
    return f"Success: Accessory {accessory_id} (service {target_sid}, char {target_cid}) set to {status_str}"


@app.tool()
async def sprut_set_characteristic(
    accessory_id: int,
    service_id: int,
    characteristic_id: int,
    value: Union[bool, int, float, str]
) -> str:
    """Set any characteristic on an accessory (brightness, temperature, mode, etc.).
    
    Args:
        accessory_id: The ID of the accessory.
        service_id: The ID of the service (sId).
        characteristic_id: The ID of the characteristic (cId).
        value: The target value to set (boolean, integer, float, or string).
    """
    await client.update_characteristic(
        a_id=accessory_id,
        s_id=service_id,
        c_id=characteristic_id,
        value=value
    )
    return f"Success: Accessory {accessory_id} [{service_id}.{characteristic_id}] updated to {value}"


@app.tool()
async def sprut_get_history(
    accessory_id: int,
    service_id: Optional[int] = None,
    characteristic_id: Optional[int] = None,
    days: Optional[float] = None,
    hours: Optional[float] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Retrieve historical telemetry data and statistics for sensor or accessory characteristics.
    
    Args:
        accessory_id: ID of the accessory.
        service_id: Optional Service ID (sId).
        characteristic_id: Optional Characteristic ID (cId).
        days: Optional time window in days (e.g. 7).
        hours: Optional time window in hours (e.g. 24).
        limit: Optional maximum number of records to retrieve.
    """
    if days or hours:
        records = await client.get_history_range(
            accessory_id=accessory_id,
            service_id=service_id,
            characteristic_id=characteristic_id,
            days=days,
            hours=hours,
            max_records=limit or 10000,
        )
    else:
        records = await client.get_history(
            accessory_id=accessory_id,
            service_id=service_id,
            characteristic_id=characteristic_id,
            limit=limit or 500,
        )

    num_values = []
    for r in records:
        v = _extract_val(r.get("value"))
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            num_values.append(float(v))

    stats = {}
    if num_values:
        stats = {
            "count": len(num_values),
            "min": min(num_values),
            "max": max(num_values),
            "avg": sum(num_values) / len(num_values),
            "latest": num_values[0],
            "delta": max(num_values) - min(num_values),
        }

    return {
        "accessory_id": accessory_id,
        "service_id": service_id,
        "characteristic_id": characteristic_id,
        "records_count": len(records),
        "stats": stats,
        "history": records[:50] if len(records) > 50 else records,
    }


@app.tool()
async def sprut_list_scenarios() -> List[Dict[str, Any]]:
    """List all automation scenarios configured in SprutHub."""
    scenarios = await client.list_scenarios()
    return [
        {
            "index": s.get("index"),
            "name": s.get("name"),
            "active": s.get("active"),
            "rooms": s.get("rooms", []),
        }
        for s in scenarios
    ]


@app.tool()
async def sprut_run_scenario(index: str) -> str:
    """Trigger / execute an automation scenario by index.
    
    Args:
        index: The index of the scenario (from sprut_list_scenarios).
    """
    await client.run_scenario(index)
    return f"Success: Scenario [index {index}] triggered."


@app.tool()
async def sprut_get_logs(count: int = 50, level: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get recent system and driver logs from SprutHub.
    
    Args:
        count: Number of log entries to retrieve (default 50).
        level: Optional filter by log level (e.g. ERROR, WARN, INFO).
    """
    logs = await client.get_logs(count=count)
    if level:
        lvl = level.upper()
        logs = [l for l in logs if lvl in (l.get("level") or "").upper()]
    return logs


@app.tool()
async def sprut_list_extensions() -> List[Dict[str, Any]]:
    """List installed protocols and extensions (Zigbee, BLE, HomeKit, MQTT, etc.) and their status."""
    return await client.list_extensions()


@app.tool()
async def sprut_create_room(name: str) -> Dict[str, Any]:
    """Create a new room in the smart home.
    
    Args:
        name: Name for the new room.
    """
    return await client.create_room(name)


@app.tool()
async def sprut_update_room(room_id: int, name: Optional[str] = None) -> str:
    """Update or rename an existing room.
    
    Args:
        room_id: ID of the room to update.
        name: Optional new name for the room.
    """
    await client.update_room(room_id=room_id, name=name)
    return f"Success: Room ID {room_id} updated."


@app.tool()
async def sprut_delete_room(room_id: int) -> str:
    """Delete a room from the smart home.
    
    Args:
        room_id: ID of the room to delete.
    """
    await client.delete_room(room_id)
    return f"Success: Room ID {room_id} deleted."


@app.tool()
async def sprut_list_catalog(search: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """List or search device templates in the SprutHub catalog.
    
    Args:
        search: Optional query to search by model or manufacturer (e.g. Aubess, TS000F).
        limit: Max number of templates to return.
    """
    return await client.list_catalog(search=search, limit=limit)


@app.tool()
async def sprut_get_catalog_template(
    file_or_model: str,
    store: Optional[str] = None,
    controller: Optional[str] = None,
) -> Dict[str, Any]:
    """Get full device template and definition from catalog.
    
    Args:
        file_or_model: Template file path or model name.
        store: Optional catalog store (default MAIN).
        controller: Optional controller (e.g. zigbee).
    """
    if not store or not controller:
        cats = await client.list_catalog(search=file_or_model, limit=10)
        matched = None
        for c in cats:
            if (
                c.get("file") == file_or_model
                or file_or_model in c.get("file", "")
                or file_or_model.lower() == (c.get("model") or "").lower()
            ):
                matched = c
                break
        if not matched and cats:
            matched = cats[0]

        if not matched:
            raise ValueError(f"Catalog template '{file_or_model}' not found.")

        store = matched.get("store", "MAIN")
        controller = matched.get("controller", "zigbee")
        file_or_model = matched.get("file")

    return await client.get_catalog(store=store, controller=controller, file=file_or_model)


@app.tool()
async def sprut_restart_hub() -> str:
    """Restart the SprutHub controller service."""
    await client.restart_hub()
    return "Success: SprutHub restart signal sent."


def main():
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
