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


def main():
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
