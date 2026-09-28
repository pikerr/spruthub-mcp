#!/usr/bin/env python3
"""SprutHub CLI: Lightweight command-line utility for SprutHub smart home control."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Add current folder to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from spruthub_client import SprutHubClient, load_config


def _extract_val(val_dict: Any) -> Any:
    if not val_dict or not isinstance(val_dict, dict):
        return val_dict
    for k in ("boolValue", "intValue", "longValue", "doubleValue", "stringValue"):
        if k in val_dict:
            return val_dict[k]
    return val_dict


def get_client() -> SprutHubClient:
    config = load_config()
    token = config.get("token")
    if not token:
        print(
            "Error: SprutHub token (local password) not found.\n"
            "Set SPRUTHUB_TOKEN environment variable or save in ~/.config/spruthub/config.json",
            file=sys.stderr,
        )
        sys.exit(1)

    return SprutHubClient(
        ws_url=config.get("ws_url", "ws://127.0.0.1/spruthub"),
        token=token,
        serial=config.get("serial"),
    )


async def cmd_info(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        info = await client.get_hub_info()
        if args.json:
            print(json.dumps(info, indent=2, ensure_ascii=False))
            return

        print(f"Hub: {info.get('name')} (Model: {info.get('model')})")
        print(f"Serial: {info.get('serial')}")
        print(f"Online: {info.get('online')}")
        ver = info.get("version", {}).get("current", {}).get("version") or info.get("version")
        print(f"Version: {ver}")
    finally:
        await client.close()


async def cmd_rooms(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        rooms = await client.list_rooms()
        if args.json:
            print(json.dumps(rooms, indent=2, ensure_ascii=False))
            return

        print(f"Rooms ({len(rooms)}):")
        for r in rooms:
            sensors = [s.get("label") for s in r.get("sensors", []) if s.get("label")]
            sensors_str = f" [Sensors: {', '.join(sensors)}]" if sensors else ""
            print(f"  ID {r.get('id'):<4} | {r.get('name')}{sensors_str}")
    finally:
        await client.close()


async def cmd_devices(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        accessories = await client.list_accessories()
        results = []

        for a in accessories:
            a_id = a.get("id")
            a_name = a.get("name", "Unknown")
            a_room = a.get("roomId") or a.get("room")

            if args.room is not None and a_room != args.room:
                continue

            if args.search:
                q = args.search.lower()
                if q not in a_name.lower():
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
                    })

                if chars_summary:
                    services_summary.append({
                        "sId": s.get("sId"),
                        "type": s_type,
                        "characteristics": chars_summary,
                    })

            if services_summary:
                results.append({
                    "accessory_id": a_id,
                    "name": a_name,
                    "room_id": a_room,
                    "services": services_summary,
                })

        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
            return

        print(f"Controllable Devices ({len(results)}):")
        for dev in results:
            chars = []
            for s in dev["services"]:
                for c in s["characteristics"]:
                    chars.append(f"{c['name']}={c['value']}")
            status = f" ({', '.join(chars)})" if chars else ""
            print(f"  ID {dev['accessory_id']:<5} | [Room {dev['room_id']}] {dev['name']}{status}")
    finally:
        await client.close()


async def cmd_device(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        acc = await client.get_accessory(args.accessory_id)
        print(json.dumps(acc, indent=2, ensure_ascii=False))
    finally:
        await client.close()


async def cmd_switch(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        acc = await client.get_accessory(args.accessory_id)
        target_sid = None
        target_cid = None

        for s in acc.get("services", []):
            if args.service is not None and s.get("sId") != args.service:
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
            print(f"Error: Controllable switch not found on accessory {args.accessory_id}", file=sys.stderr)
            sys.exit(1)

        is_on = args.state.lower() in ("on", "true", "1")
        await client.update_characteristic(
            a_id=args.accessory_id,
            s_id=target_sid,
            c_id=target_cid,
            value=is_on,
        )
        status_text = "ON" if is_on else "OFF"
        print(f"Success: Accessory {args.accessory_id} set to {status_text}")
    finally:
        await client.close()


async def cmd_set(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        # Parse value type
        val_raw = args.value
        val: Any
        if val_raw.lower() in ("true", "false"):
            val = val_raw.lower() == "true"
        elif val_raw.isdigit():
            val = int(val_raw)
        else:
            try:
                val = float(val_raw)
            except ValueError:
                val = val_raw

        await client.update_characteristic(
            a_id=args.accessory_id,
            s_id=args.service_id,
            c_id=args.characteristic_id,
            value=val,
        )
        print(f"Success: Accessory {args.accessory_id} [{args.service_id}.{args.characteristic_id}] = {val}")
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="spruthub-cli",
        description="SprutHub Smart Home CLI",
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # info
    p_info = subparsers.add_parser("info", help="Get SprutHub info")
    p_info.set_defaults(func=cmd_info)

    # rooms
    p_rooms = subparsers.add_parser("rooms", help="List rooms")
    p_rooms.set_defaults(func=cmd_rooms)

    # devices
    p_devices = subparsers.add_parser("devices", help="List controllable accessories")
    p_devices.add_argument("--room", type=int, default=None, help="Filter by room ID")
    p_devices.add_argument("--search", "-s", type=str, default=None, help="Search by name")
    p_devices.set_defaults(func=cmd_devices)

    # device
    p_device = subparsers.add_parser("device", help="Get complete accessory details")
    p_device.add_argument("accessory_id", type=int, help="Accessory ID")
    p_device.set_defaults(func=cmd_device)

    # switch
    p_switch = subparsers.add_parser("switch", help="Turn switch, light, or outlet ON or OFF")
    p_switch.add_argument("accessory_id", type=int, help="Accessory ID")
    p_switch.add_argument("state", choices=["on", "off", "true", "false", "1", "0"], help="Target state")
    p_switch.add_argument("--service", type=int, default=None, help="Service ID (if multiple)")
    p_switch.set_defaults(func=cmd_switch)

    # set
    p_set = subparsers.add_parser("set", help="Set specific characteristic value")
    p_set.add_argument("accessory_id", type=int, help="Accessory ID")
    p_set.add_argument("service_id", type=int, help="Service ID (sId)")
    p_set.add_argument("characteristic_id", type=int, help="Characteristic ID (cId)")
    p_set.add_argument("value", help="Value to set")
    p_set.set_defaults(func=cmd_set)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
