#!/usr/bin/env python3
"""SprutHub CLI: Lightweight command-line utility for SprutHub smart home control."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
import unicodedata

# Add current folder to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from spruthub_client import SprutHubClient, load_config, normalize_ws_url


def _vis_len(s: Any) -> int:
    w = 0
    for ch in str(s):
        if ch in ("🟢", "🔴", "⚪", "⚡") or unicodedata.east_asian_width(ch) in ("W", "F"):
            w += 2
        else:
            w += 1
    return w


def _pad(s: Any, target_width: int, align: str = "left") -> str:
    s_str = str(s) if s is not None else ""
    vw = _vis_len(s_str)
    sp = max(0, target_width - vw)
    if align == "right":
        return " " * sp + s_str
    return s_str + " " * sp


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


async def cmd_summary(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        hub_info, account, rooms, accessories, scenarios, extensions = await asyncio.gather(
            client.get_hub_info(),
            client.call("account.get", {}),
            client.list_rooms(),
            client.list_accessories(),
            client.list_scenarios(),
            client.list_extensions(),
        )

        ver = hub_info.get("version", {}).get("current", {})
        plat = hub_info.get("platform", {})
        owner = hub_info.get("owner") or account.get("email") or "Не указан"

        online_accs = sum(1 for a in accessories if a.get("online", True))
        offline_accs = len(accessories) - online_accs
        active_scenarios = sum(1 for s in scenarios if s.get("active"))

        # Category definitions
        cat_defs = [
            ("Выключатели и силовые реле", lambda st, a: "Switch" in st, True),
            ("Розетки", lambda st, a: "Outlet" in st, True),
            ("Освещение", lambda st, a: "Lightbulb" in st, True),
            ("Термостаты и климат", lambda st, a: "Thermostat" in st or "Fan" in st, True),
            ("Шторы и электроприводы", lambda st, a: "WindowCovering" in st, False),
            ("Датчики климата (T / H / P)", lambda st, a: any(t in st for t in ("TemperatureSensor", "HumiditySensor", "C_AtmosphericPressureSensor")), False),
            ("Датчики движения и освещенности", lambda st, a: any(t in st for t in ("MotionSensor", "LightSensor", "OccupancySensor")), False),
            ("Датчики открытия (двери / окна)", lambda st, a: any(t in st for t in ("ContactSensor", "DoorSensor")), False),
            ("Датчики безопасности (дым / газ / протечка)", lambda st, a: any(t in st for t in ("LeakSensor", "SmokeSensor", "C_GasSensor")), False),
            ("Беспроводные выключатели и кнопки", lambda st, a: "StatelessProgrammableSwitch" in st, False),
            ("Сетевые ретрансляторы Zigbee", lambda st, a: "C_Repeater" in st, False),
            ("Охранные системы", lambda st, a: "SecuritySystem" in st, False),
            ("Системный контроллер", lambda st, a: a.get("id") == 1, False),
        ]

        cat_stats = []
        assigned_ids = set()

        for name, matcher, can_be_on in cat_defs:
            total = 0
            online = 0
            offline = 0
            turned_on = 0

            for a in accessories:
                aid = a.get("id")
                if aid in assigned_ids:
                    continue

                stypes = {s.get("type") for s in a.get("services", [])}
                if matcher(stypes, a):
                    assigned_ids.add(aid)
                    total += 1
                    is_onl = a.get("online", True)
                    if is_onl:
                        online += 1
                    else:
                        offline += 1

                    if can_be_on and is_onl:
                        is_on = False
                        for s in a.get("services", []):
                            if s.get("type") in ("Switch", "Lightbulb", "Outlet", "Thermostat", "Fan"):
                                for c in s.get("characteristics", []):
                                    ctl = c.get("control", {})
                                    if ctl.get("type") == "On" and ctl.get("value", {}).get("boolValue") is True:
                                        is_on = True
                        if is_on:
                            turned_on += 1

            if total > 0:
                cat_stats.append({
                    "name": name,
                    "total": total,
                    "online": online,
                    "offline": offline,
                    "turned_on": turned_on if can_be_on else None,
                })

        remaining = [a for a in accessories if a.get("id") not in assigned_ids]
        if remaining:
            r_online = sum(1 for a in remaining if a.get("online", True))
            cat_stats.append({
                "name": "Прочие устройства",
                "total": len(remaining),
                "online": r_online,
                "offline": len(remaining) - r_online,
                "turned_on": None,
            })

        controllable_count = sum(c["total"] for c in cat_stats if c["turned_on"] is not None)
        turned_on_count = sum(c["turned_on"] for c in cat_stats if c["turned_on"] is not None)

        room_map = {r["id"]: {"room": r, "devices": [], "online_count": 0, "offline_count": 0, "on_count": 0} for r in rooms}
        unassigned = []

        for a in accessories:
            rid = a.get("roomId") or a.get("room")
            is_onl = a.get("online", True)
            is_on = False
            if is_onl:
                for s in a.get("services", []):
                    if s.get("type") in ("Switch", "Lightbulb", "Outlet", "Thermostat", "Fan"):
                        for c in s.get("characteristics", []):
                            ctl = c.get("control", {})
                            if ctl.get("type") == "On" and ctl.get("value", {}).get("boolValue") is True:
                                is_on = True

            if rid in room_map:
                room_map[rid]["devices"].append(a)
                if is_onl:
                    room_map[rid]["online_count"] += 1
                else:
                    room_map[rid]["offline_count"] += 1
                if is_on:
                    room_map[rid]["on_count"] += 1
            else:
                unassigned.append(a)

        if args.json:
            out = {
                "hub": {
                    "name": hub_info.get("name"),
                    "model": hub_info.get("model"),
                    "serial": hub_info.get("serial"),
                    "owner": owner,
                    "online": hub_info.get("online"),
                    "version": ver.get("version"),
                    "revision": ver.get("revision"),
                    "platform": f"{plat.get('manufacturer', '')} {plat.get('model', '')}".strip(),
                },
                "stats": {
                    "rooms_total": len(rooms),
                    "accessories_total": len(accessories),
                    "accessories_online": online_accs,
                    "accessories_offline": offline_accs,
                    "controllable_total": controllable_count,
                    "turned_on_now": turned_on_count,
                    "scenarios_total": len(scenarios),
                    "scenarios_active": active_scenarios,
                    "extensions_total": len(extensions),
                },
                "categories": cat_stats,
                "rooms": [
                    {
                        "id": rid,
                        "name": rdata["room"].get("name"),
                        "online": rdata["online_count"],
                        "turned_on": rdata["on_count"],
                        "offline": rdata["offline_count"],
                        "total": len(rdata["devices"]),
                        "sensors": [s.get("label") for s in rdata["room"].get("sensors", []) if s.get("label")],
                    }
                    for rid, rdata in sorted(room_map.items())
                ],
                "extensions": extensions,
            }
            print(json.dumps(out, indent=2, ensure_ascii=False))
            return

        print("==========================================================================================")
        print("                            СПРУТХАБ: СВОДНЫЙ ОТЧЕТ (SUMMARY)                             ")
        print("==========================================================================================")
        print(f"Контроллер: {hub_info.get('name')} (Sprut.hub {hub_info.get('model')}) | Владелец: {owner}")
        print(f"Серийный №: {hub_info.get('serial')} | Платформа: {plat.get('manufacturer')} {plat.get('model')} (MAC: {plat.get('mac')})")
        print(f"Версия ПО:  v{ver.get('version')} (rev {ver.get('revision')}, template {ver.get('template')}, ветка {hub_info.get('version', {}).get('branch')}) | Java: JDK {plat.get('jdk')}")
        print(f"Статус:     {'🟢 ОНЛАЙН' if hub_info.get('online') else '🔴 ОФЛАЙН'} | Язык: {hub_info.get('lang')}")
        print("------------------------------------------------------------------------------------------")
        print("ОБЩАЯ СТАТИСТИКА:")
        print(f"  • Комнат:         {len(rooms)}")
        print(f"  • Аксессуаров:    {len(accessories)} (в сети: {online_accs}, офлайн: {offline_accs})")
        print(f"  • Управляемых:    {controllable_count} (включено прямо сейчас: {turned_on_count})")
        print(f"  • Сценариев:      {len(scenarios)} (активных: {active_scenarios}, выключенных: {len(scenarios) - active_scenarios})")
        print(f"  • Расширений:     {len(extensions)} (контроллеры, мосты, службы уведомлений)")
        print("------------------------------------------------------------------------------------------")
        print("УСТРОЙСТВА ПО КАТЕГОРИЯМ:")
        print(f"  {_pad('Категория', 42)} | {_pad('🟢 В сети', 11)} | {_pad('⚡ Вкл', 8)} | {_pad('🔴 Офлайн', 11)} | {_pad('Всего', 6)}")
        print("  " + "-" * 88)
        for c in cat_stats:
            on_disp = str(c["turned_on"]) if c["turned_on"] is not None else "-"
            print(f"  {_pad(c['name'], 42)} | {_pad(c['online'], 11)} | {_pad(on_disp, 8)} | {_pad(c['offline'], 11)} | {_pad(c['total'], 6)}")
        print("------------------------------------------------------------------------------------------")
        print("КОНТРОЛЛЕРЫ И РАСШИРЕНИЯ:")
        by_type: dict[str, list[dict[str, Any]]] = {}
        for e in extensions:
            btype = e.get("bundleType") or "OTHER"
            by_type.setdefault(btype, []).append(e)

        type_labels = {
            "CONTROLLER": "Протокольные контроллеры",
            "BRIDGE": "Мосты интеграций",
            "NOTIFICATION": "Службы уведомлений",
            "PLUGIN": "Плагины и сервисы",
        }
        for btype, elist in by_type.items():
            print(f"  [{type_labels.get(btype, btype)}]")
            for e in elist:
                status_icon = "🟢" if e.get("state") == "LOADED" else ("⚪" if not e.get("enabled") else "🔴")
                child_str = f"{e.get('childCount', 0)} устройств" if "childCount" in e else ""
                version_str = ""
                for sp in e.get("spaces", []):
                    h = sp.get("label", {}).get("header", "")
                    if "v" in h:
                        version_str = h.split()[-1]
                        break
                ver_disp = f"({version_str})" if version_str else ""
                print(f"    {status_icon} {e.get('name'):<20} | Тип: {e.get('type'):<10} {ver_disp:<10} | {e.get('state'):<10} | {child_str}")
        print("------------------------------------------------------------------------------------------")
        print("КОМНАТЫ И РАСПРЕДЕЛЕНИЕ УСТРОЙСТВ:")
        print(f"  {_pad('ID', 4)} | {_pad('Комната', 20)} | {_pad('🟢 В сети', 11)} | {_pad('⚡ Вкл', 8)} | {_pad('🔴 Офлайн', 11)} | {_pad('Всего', 6)} | Сенсоры")
        print("  " + "-" * 92)
        for rid, rdata in sorted(room_map.items()):
            r = rdata["room"]
            dev_total = len(rdata["devices"])
            onl_cnt = rdata["online_count"]
            on_cnt = rdata["on_count"]
            off_cnt = rdata["offline_count"]
            sensors = [s.get("label") for s in r.get("sensors", []) if s.get("label")]
            sensors_str = ", ".join(sensors[:3]) if sensors else "-"
            if len(sensors) > 3:
                sensors_str += f" (+{len(sensors)-3})"
            print(f"  {_pad(rid, 4)} | {_pad(r.get('name'), 20)} | {_pad(onl_cnt, 11)} | {_pad(on_cnt, 8)} | {_pad(off_cnt, 11)} | {_pad(dev_total, 6)} | {sensors_str}")

        if unassigned:
            u_onl = sum(1 for a in unassigned if a.get("online", True))
            u_off = len(unassigned) - u_onl
            print(f"  {_pad('--', 4)} | {_pad('Без комнаты', 20)} | {_pad(u_onl, 11)} | {_pad('-', 8)} | {_pad(u_off, 11)} | {_pad(len(unassigned), 6)} | -")
        print("==========================================================================================")
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


async def cmd_history(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        a_id = args.accessory_id
        acc = await client.get_accessory(a_id)

        # Build list of available characteristics
        telemetry_chars = []
        for s in acc.get("services", []):
            sid = s.get("sId")
            sname = s.get("name") or s.get("type", "")
            for c in s.get("characteristics", []):
                cid = c.get("cId")
                ctl = c.get("control", {})
                cname = ctl.get("name") or ctl.get("type", "")
                ctype = ctl.get("type", "")
                if ctype in (
                    "Identify",
                    "Name",
                    "C_Online",
                    "C_Room",
                    "SerialNumber",
                    "Manufacturer",
                    "Model",
                    "FirmwareRevision",
                    "C_CatalogId",
                ):
                    continue
                val = _extract_val(ctl.get("value"))
                telemetry_chars.append({
                    "sId": sid,
                    "cId": cid,
                    "sName": sname,
                    "cName": cname,
                    "type": ctype,
                    "current": val,
                })

        target_sid = args.service
        target_cid = None

        if args.characteristic:
            query = str(args.characteristic).strip().lower()
            if "." in query and all(part.isdigit() for part in query.split(".", 1)):
                parts = query.split(".", 1)
                target_sid = int(parts[0])
                target_cid = int(parts[1])
            elif query.isdigit():
                target_cid = int(query)
            else:
                matches = [
                    tc
                    for tc in telemetry_chars
                    if query in tc["sName"].lower()
                    or query in tc["cName"].lower()
                    or query in tc["type"].lower()
                ]
                if len(matches) == 1:
                    target_sid = matches[0]["sId"]
                    target_cid = matches[0]["cId"]
                elif len(matches) > 1:
                    exact = [
                        tc
                        for tc in matches
                        if query == tc["sName"].lower() or query == tc["cName"].lower()
                    ]
                    if len(exact) == 1:
                        target_sid = exact[0]["sId"]
                        target_cid = exact[0]["cId"]
                    else:
                        print(f"Ambiguous characteristic '{args.characteristic}'. Matches:", file=sys.stderr)
                        for m in matches:
                            print(
                                f"  - {m['sName']} / {m['cName']} (sId={m['sId']}, cId={m['cId']})",
                                file=sys.stderr,
                            )
                        sys.exit(1)
                else:
                    print(f"Error: Characteristic '{args.characteristic}' not found on accessory {a_id}.", file=sys.stderr)
                    sys.exit(1)
        else:
            if len(telemetry_chars) == 1:
                target_sid = telemetry_chars[0]["sId"]
                target_cid = telemetry_chars[0]["cId"]
            else:
                acc_name = acc.get("name") or "Accessory"
                print(f"Accessory {a_id} ({acc_name}) has {len(telemetry_chars)} measurable characteristics:")
                for tc in telemetry_chars:
                    curr_val = f" = {tc['current']}" if tc["current"] is not None else ""
                    print(f"  - sId={tc['sId']:<2} cId={tc['cId']:<2} | {tc['sName']:<15} | {tc['cName']} ({tc['type']}){curr_val}")
                print(f"\nSpecify characteristic by name or cId:\n  spruthub-cli history {a_id} <name_or_cId> [--days 7]")
                return

        # Fetch history
        if args.days or args.hours:
            records = await client.get_history_range(
                accessory_id=a_id,
                service_id=target_sid,
                characteristic_id=target_cid,
                days=args.days,
                hours=args.hours,
                max_records=args.limit or 10000,
            )
        else:
            records = await client.get_history(
                accessory_id=a_id,
                service_id=target_sid,
                characteristic_id=target_cid,
                limit=args.limit or 500,
            )

        matched_info = next(
            (tc for tc in telemetry_chars if tc["cId"] == target_cid and (target_sid is None or tc["sId"] == target_sid)),
            {"sName": str(target_sid or ""), "cName": str(target_cid), "type": "Unknown", "current": None},
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

        if args.json:
            out = {
                "accessory_id": a_id,
                "service_id": target_sid,
                "characteristic_id": target_cid,
                "name": f"{matched_info['sName']} / {matched_info['cName']}",
                "stats": stats,
                "records_count": len(records),
                "history": records,
            }
            print(json.dumps(out, indent=2, ensure_ascii=False))
            return

        from datetime import datetime
        acc_name = acc.get("name") or f"ID {a_id}"
        char_label = f"{matched_info['sName']} -> {matched_info['cName']}"
        print(f"History: {acc_name} | {char_label} (sId={target_sid}, cId={target_cid})")
        print(f"Total points: {len(records)}")

        if not records:
            print("No history records found for the requested period.")
            return

        first_ts = records[-1]["timestamp"] / 1000
        last_ts = records[0]["timestamp"] / 1000
        first_dt = datetime.fromtimestamp(first_ts).strftime("%Y-%m-%d %H:%M:%S")
        last_dt = datetime.fromtimestamp(last_ts).strftime("%Y-%m-%d %H:%M:%S")
        print(f"Period: {first_dt} — {last_dt}")

        if stats:
            print(f"Stats: Min: {stats['min']:.4g} | Max: {stats['max']:.4g} | Avg: {stats['avg']:.4g} | Latest: {stats['latest']:.4g} | Delta: {stats['delta']:.4g}")

        if (last_ts - first_ts) > 86400:
            by_day = {}
            for r in records:
                dt_day = datetime.fromtimestamp(r["timestamp"] / 1000).strftime("%Y-%m-%d")
                val = _extract_val(r.get("value"))
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    by_day.setdefault(dt_day, []).append(float(val))

            print("\nDaily breakdown:")
            for day in sorted(by_day.keys()):
                vals = by_day[day]
                print(f"  {day}: min={min(vals):.4g}, max={max(vals):.4g}, avg={sum(vals)/len(vals):.4g} (samples: {len(vals)})")
        else:
            print("\nRecent points (up to 15):")
            for r in records[:15]:
                dt_str = datetime.fromtimestamp(r["timestamp"] / 1000).strftime("%H:%M:%S")
                val = _extract_val(r.get("value"))
                print(f"  {dt_str} | {val}")
    finally:
        await client.close()


async def cmd_scenarios(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        scenarios = await client.list_scenarios()
        if args.search:
            q = args.search.lower()
            scenarios = [s for s in scenarios if q in (s.get("name") or "").lower()]

        if args.json:
            print(json.dumps(scenarios, indent=2, ensure_ascii=False))
            return

        print(f"Scenarios ({len(scenarios)}):")
        for s in scenarios:
            idx = s.get("index")
            name = s.get("name") or "Unnamed"
            status = "ACTIVE" if s.get("active") else "DISABLED"
            rooms = s.get("rooms", [])
            rooms_str = f" [Rooms: {rooms}]" if rooms else ""
            print(f"  [{idx:>3}] {name:<35} | {status}{rooms_str}")
    finally:
        await client.close()


async def cmd_scenario_run(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        scenarios = await client.list_scenarios()
        target_index = None
        target_name = None

        query = str(args.scenario).strip()
        for s in scenarios:
            if str(s.get("index")) == query:
                target_index = s.get("index")
                target_name = s.get("name")
                break
            if query.lower() == (s.get("name") or "").lower():
                target_index = s.get("index")
                target_name = s.get("name")
                break

        if not target_index:
            matches = [s for s in scenarios if query.lower() in (s.get("name") or "").lower()]
            if len(matches) == 1:
                target_index = matches[0].get("index")
                target_name = matches[0].get("name")
            elif len(matches) > 1:
                print(f"Ambiguous scenario name '{query}'. Matches:", file=sys.stderr)
                for m in matches:
                    print(f"  [{m.get('index')}] {m.get('name')}", file=sys.stderr)
                sys.exit(1)
            else:
                print(f"Error: Scenario '{query}' not found.", file=sys.stderr)
                sys.exit(1)

        await client.run_scenario(target_index)
        print(f"Success: Scenario '{target_name}' [index {target_index}] executed.")
    finally:
        await client.close()


async def cmd_logs(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        from datetime import datetime

        logs = await client.get_logs(count=args.count or 50)
        if args.level:
            lvl = args.level.upper()
            logs = [l for l in logs if lvl in (l.get("level") or "").upper()]
        if args.search:
            q = args.search.lower()
            logs = [
                l
                for l in logs
                if q in (l.get("message") or "").lower() or q in (l.get("path") or "").lower()
            ]

        if args.json:
            print(json.dumps(logs, indent=2, ensure_ascii=False))
            return

        print(f"SprutHub Logs ({len(logs)}):")
        for l in logs:
            ts_ms = l.get("time", 0)
            dt_str = (
                datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
                if ts_ms
                else "Unknown"
            )
            lvl = (l.get("level") or "").replace("LOG_LEVEL_", "")
            path = l.get("path") or ""
            msg = l.get("message") or ""
            print(f"[{dt_str}] [{lvl:<5}] [{path}]: {msg}")
    finally:
        await client.close()


async def cmd_extensions(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        exts = await client.list_extensions()
        if args.json:
            print(json.dumps(exts, indent=2, ensure_ascii=False))
            return

        print(f"Extensions / Protocols ({len(exts)}):")
        for e in exts:
            e_id = e.get("id")
            name = e.get("name") or "Unnamed"
            etype = e.get("type") or ""
            online = "ONLINE" if e.get("online", True) else "OFFLINE"
            enabled = "ENABLED" if e.get("enabled", True) else "DISABLED"
            print(f"  ID {e_id:<2} | {name:<20} | Type: {etype:<12} | {enabled} | {online}")
    finally:
        await client.close()


async def cmd_restart(args: argparse.Namespace) -> None:
    if not args.yes:
        confirm = input("Are you sure you want to restart SprutHub? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Restart aborted.")
            return

    client = get_client()
    try:
        await client.restart_hub()
        print("Success: Restart signal sent to SprutHub controller.")
    finally:
        await client.close()


async def cmd_room_create(args: argparse.Namespace) -> None:
    name = args.name.strip()
    if not name:
        print("Error: Room name cannot be empty.", file=sys.stderr)
        sys.exit(1)

    client = get_client()
    try:
        res = await client.create_room(name)
        new_id = res.get("id")
        print(f"Success: Room '{name}' created with ID {new_id}.")
    finally:
        await client.close()


async def cmd_room_rename(args: argparse.Namespace) -> None:
    target = str(args.room).strip()
    new_name = args.new_name.strip()
    if not new_name:
        print("Error: New room name cannot be empty.", file=sys.stderr)
        sys.exit(1)

    client = get_client()
    try:
        rooms = await client.list_rooms()
        room_id = None
        current_name = None

        if target.isdigit():
            r_id = int(target)
            for r in rooms:
                if r.get("id") == r_id:
                    room_id = r_id
                    current_name = r.get("name")
                    break
        if room_id is None:
            for r in rooms:
                if r.get("name", "").lower() == target.lower():
                    room_id = r.get("id")
                    current_name = r.get("name")
                    break

        if room_id is None:
            print(f"Error: Room '{target}' not found.", file=sys.stderr)
            sys.exit(1)

        await client.update_room(room_id=room_id, name=new_name)
        print(f"Success: Room ID {room_id} ('{current_name}') renamed to '{new_name}'.")
    finally:
        await client.close()


async def cmd_room_delete(args: argparse.Namespace) -> None:
    target = str(args.room).strip()
    client = get_client()
    try:
        rooms = await client.list_rooms()
        room_id = None
        room_name = None

        if target.isdigit():
            r_id = int(target)
            for r in rooms:
                if r.get("id") == r_id:
                    room_id = r_id
                    room_name = r.get("name")
                    break
        if room_id is None:
            for r in rooms:
                if r.get("name", "").lower() == target.lower():
                    room_id = r.get("id")
                    room_name = r.get("name")
                    break

        if room_id is None:
            print(f"Error: Room '{target}' not found.", file=sys.stderr)
            sys.exit(1)

        if not args.yes:
            confirm = (
                input(f"Are you sure you want to delete room '{room_name}' (ID {room_id})? [y/N]: ")
                .strip()
                .lower()
            )
            if confirm not in ("y", "yes"):
                print("Deletion aborted.")
                return

        await client.delete_room(room_id)
        print(f"Success: Room '{room_name}' (ID {room_id}) deleted.")
    finally:
        await client.close()


async def cmd_catalog_list(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        cats = await client.list_catalog(search=args.search, limit=args.limit or 50)
        if args.json:
            print(json.dumps(cats, indent=2, ensure_ascii=False))
            return

        print(f"Catalog Templates ({len(cats)}):")
        for c in cats:
            m = c.get("model") or "-"
            man = c.get("manufacturer") or "-"
            ctl = c.get("controller") or "-"
            f = c.get("file") or "-"
            s = c.get("store") or "MAIN"
            print(f"  [{ctl:<6}] {man:<15} | Model: {m:<15} | File: {f} ({s})")
    finally:
        await client.close()


async def cmd_catalog_get(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        store = args.store
        controller = args.controller
        file_path = args.file

        if not store or not controller:
            cats = await client.list_catalog(search=file_path, limit=10)
            matched = None
            for c in cats:
                if (
                    c.get("file") == file_path
                    or file_path in c.get("file", "")
                    or file_path.lower() == (c.get("model") or "").lower()
                ):
                    matched = c
                    break
            if not matched and cats:
                matched = cats[0]

            if not matched:
                print(f"Error: Catalog template '{file_path}' not found.", file=sys.stderr)
                sys.exit(1)

            store = matched.get("store", "MAIN")
            controller = matched.get("controller", "zigbee")
            file_path = matched.get("file")

        cat_details = await client.get_catalog(store=store, controller=controller, file=file_path)
        if args.json:
            print(json.dumps(cat_details, indent=2, ensure_ascii=False))
            return

        tmpl = cat_details.get("template")
        if tmpl and isinstance(tmpl, str):
            try:
                parsed = json.loads(tmpl)
                print(json.dumps(parsed, indent=2, ensure_ascii=False))
                return
            except Exception:
                pass
        print(json.dumps(cat_details, indent=2, ensure_ascii=False))
    finally:
        await client.close()


SKILL_MARKDOWN = """---
name: spruthub
description: Control and monitor SprutHub smart home (lights, switches, rooms, sensors, temperature, history, scenarios, logs, catalog) on-demand via lightweight CLI without background daemon overhead.
---

# SprutHub Smart Home Skill

Use this skill whenever the user asks to inspect, monitor, or control devices in their **SprutHub** smart home (e.g. "включи свет в спальне", "какая температура в кабинете", "история разницы напряжений за неделю", "запусти сценарий вечер", "создай комнату", "покажи логи").

## Execution Mode

Always execute commands via `uvx` (or local `spruthub-cli`) using `spruthub-cli`. This executes on-demand in ~80 ms without keeping any background daemon or eating RAM.

### Command Format

```bash
uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli <command> [args]
```

## Quick Reference

### 1. Hub Status & Rooms
* **Comprehensive summary dashboard:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli summary`
* **Hub info:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli info`
* **List all rooms (with sensor readings):**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli rooms`
* **Create room:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli room create <name>`
* **Rename room:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli room rename <id_or_name> <new_name>`
* **Delete room:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli room delete <id_or_name> --yes`

### 2. Finding & Inspecting Devices
* **List controllable devices in a specific room:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli devices --room <room_id>`
* **Search devices by name:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli devices --search "свет"`
* **Inspect full device characteristics:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli device <accessory_id>`

### 3. Historical Telemetry & Sensors
* **List available characteristics for device:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli history <accessory_id>`
* **Get history for last 7 days:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli history <accessory_id> <name_or_cId> --days 7`
* **Get history for last 24 hours:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli history <accessory_id> <name_or_cId> --hours 24`

### 4. Scenarios & Automations
* **List scenarios:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli scenarios`
* **Run scenario:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli scenario run <name_or_index>`

### 5. Diagnostics, Logs & Extensions
* **View recent logs:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli logs --count 50`
* **Filter logs by error or keyword:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli logs --level ERROR --search "zigbee"`
* **List extensions and protocols:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli extensions`
* **Restart hub controller:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli restart --yes`

### 6. Templates & Device Catalog
* **Search catalog templates:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli catalog list --search "Aubess"`
* **Inspect device template:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli catalog get <model_or_file>`

### 7. Controlling Switches, Lights & Outlets
* **Turn ON:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli switch <accessory_id> on`
* **Turn OFF:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli switch <accessory_id> off`

### 8. Setting Characteristics (Brightness, Target Temp, Modes)
* **Set specific value:**
  `uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli set <accessory_id> <service_id> <characteristic_id> <value>`

## Guidelines for the Agent
1. If the user asks about a room (e.g., "что включено в кабинете?"), run `spruthub-cli rooms` to get the `room_id`, then `spruthub-cli devices --room <id>` to see the exact state.
2. If turning a switch on/off, use `spruthub-cli switch <id> on/off`. It automatically detects the correct Switch/Lightbulb/Outlet service without needing `sId` or `cId`.
3. Never delete user rooms or devices without explicit confirmation.
4. Provide a clear, concise confirmation to the user in Russian.
"""


async def cmd_install(args: argparse.Namespace) -> None:
    host = args.host
    token = args.token

    # Load existing config if available
    config = load_config()
    if not host:
        host = config.get("host") or config.get("ws_url")
    if not token:
        token = config.get("token")

    if not host or not token:
        print("Please configure SprutHub connection:")
        if not host:
            host = input("SprutHub IP or host (e.g. 192.168.1.100): ").strip()
        if not token:
            token = input("SprutHub local password / token: ").strip()

    if not host or not token:
        print("Error: Both host and token are required.", file=sys.stderr)
        sys.exit(1)

    # Save XDG config
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        cfg_dir = Path(appdata) / "spruthub" if appdata else Path.home() / ".config" / "spruthub"
    else:
        xdg_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        cfg_dir = Path(xdg_home) / "spruthub"

    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = cfg_dir / "config.json"
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump({"host": host, "token": token}, f, indent=2)
    try:
        cfg_file.chmod(0o600)
    except Exception:
        pass
    print(f"✓ Configuration saved to {cfg_file}")

    # Detect and install skill to known agent directories
    installed_targets = []

    # Antigravity (~/.gemini/config/skills/spruthub/SKILL.md)
    gemini_skills = Path.home() / ".gemini" / "config" / "skills" / "spruthub"
    gemini_skills.mkdir(parents=True, exist_ok=True)
    (gemini_skills / "SKILL.md").write_text(SKILL_MARKDOWN, encoding="utf-8")
    installed_targets.append("Antigravity (~/.gemini/config/skills/spruthub/SKILL.md)")

    # Claude Code (~/.claude/skills/spruthub/SKILL.md) if ~/.claude exists
    claude_dir = Path.home() / ".claude"
    if claude_dir.exists():
        claude_skills = claude_dir / "skills" / "spruthub"
        claude_skills.mkdir(parents=True, exist_ok=True)
        (claude_skills / "SKILL.md").write_text(SKILL_MARKDOWN, encoding="utf-8")
        installed_targets.append("Claude Code (~/.claude/skills/spruthub/SKILL.md)")

    for target in installed_targets:
        print(f"✓ Installed Skill for {target}")

    # Optional: Register MCP in Claude Desktop / Cursor
    claude_cfg = get_claude_desktop_config_path()
    cursor_cfg = get_cursor_mcp_config_path()
    enable_mcp = getattr(args, "mcp", False)

    if not enable_mcp and sys.stdin.isatty():
        if claude_cfg.parent.exists() or cursor_cfg.parent.exists():
            ans = input("\nDetected MCP client (Claude Desktop / Cursor). Register SprutHub MCP server? [Y/n]: ").strip().lower()
            if ans in ("", "y", "yes", "д", "да"):
                enable_mcp = True

    if enable_mcp:
        print("\nRegistering SprutHub MCP server in clients...")
        reg_claude = register_mcp_server(claude_cfg, host, token, "Claude Desktop")
        print(f"✓ Registered SprutHub MCP server in Claude Desktop ({reg_claude})")
        print(f"  (Backup saved to {claude_cfg.name}.bak)")

        if cursor_cfg.parent.exists():
            reg_cursor = register_mcp_server(cursor_cfg, host, token, "Cursor")
            print(f"✓ Registered SprutHub MCP server in Cursor ({reg_cursor})")

    # Verify connection
    print("\nVerifying connection to SprutHub...")
    client = SprutHubClient(ws_url=normalize_ws_url(host), token=token)
    try:
        info = await client.get_hub_info()
        name = info.get("name", "SprutHub")
        model = info.get("model", "")
        ver = info.get("version", {}).get("current", {}).get("version", "") if isinstance(info.get("version"), dict) else info.get("version", "")
        print(f"✓ Success! Connected to {name} (Model: {model}, v{ver})")
        print("\nAll set! Your AI agent can now seamlessly control your smart home.")
    except Exception as e:
        print(f"Warning: Connection check failed: {e}\nPlease verify host and token.", file=sys.stderr)
    finally:
        await client.close()


def get_claude_desktop_config_path() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Claude" / "claude_desktop_config.json" if appdata else Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        xdg_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        return Path(xdg_home) / "Claude" / "claude_desktop_config.json"


def get_cursor_mcp_config_path() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def register_mcp_server(config_path: Path, host: str, token: str, client_name: str) -> str:
    """Safely register SprutHub MCP server in a client configuration JSON with automatic backup."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing_data: dict[str, Any] = {}

    if config_path.exists():
        backup_path = config_path.with_suffix(".json.bak")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    existing_data = json.loads(content)
            # Create backup
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(existing_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            pass

    if not isinstance(existing_data, dict):
        existing_data = {}

    if "mcpServers" not in existing_data or not isinstance(existing_data["mcpServers"], dict):
        existing_data["mcpServers"] = {}

    existing_data["mcpServers"]["spruthub"] = {
        "command": "uvx",
        "args": [
            "--from",
            "git+https://github.com/pikerr/spruthub-mcp",
            "spruthub-mcp"
        ],
        "env": {
            "SPRUTHUB_HOST": host,
            "SPRUTHUB_TOKEN": token
        }
    }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)

    return str(config_path)


async def cmd_install_mcp(args: argparse.Namespace) -> None:
    config = load_config()
    host = args.host or config.get("host") or config.get("ws_url")
    token = args.token or config.get("token")

    if not host or not token:
        if not host:
            host = input("SprutHub IP or host (e.g. 192.168.1.100): ").strip()
        if not token:
            token = input("SprutHub local password / token: ").strip()

    if not host or not token:
        print("Error: Both host and token are required.", file=sys.stderr)
        sys.exit(1)

    claude_cfg = get_claude_desktop_config_path()
    cursor_cfg = get_cursor_mcp_config_path()

    if args.client in ("claude", "all"):
        reg = register_mcp_server(claude_cfg, host, token, "Claude Desktop")
        print(f"✓ Registered SprutHub MCP server in Claude Desktop ({reg})")
        print(f"  (Backup saved to {claude_cfg.name}.bak)")

    if args.client in ("cursor", "all"):
        reg = register_mcp_server(cursor_cfg, host, token, "Cursor")
        print(f"✓ Registered SprutHub MCP server in Cursor ({reg})")

    print("\nMCP configuration updated successfully! Please restart your MCP client (Claude Desktop / Cursor).")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="spruthub-cli",
        description="SprutHub Smart Home CLI",
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # install
    p_inst = subparsers.add_parser("install", help="Self-install SprutHub skill and configure credentials")
    p_inst.add_argument("--host", help="SprutHub IP or hostname (e.g. 192.168.1.100)")
    p_inst.add_argument("--token", help="SprutHub local password / token")
    p_inst.add_argument("--mcp", action="store_true", help="Also register MCP server in Claude Desktop / Cursor")
    p_inst.set_defaults(func=cmd_install)

    # install-mcp
    p_mcp = subparsers.add_parser("install-mcp", help="Register SprutHub MCP server in Claude Desktop / Cursor")
    p_mcp.add_argument("--host", help="SprutHub IP or hostname (e.g. 192.168.1.100)")
    p_mcp.add_argument("--token", help="SprutHub local password / token")
    p_mcp.add_argument("--client", choices=["claude", "cursor", "all"], default="all", help="Target client")
    p_mcp.set_defaults(func=cmd_install_mcp)

    # info
    p_info = subparsers.add_parser("info", help="Get SprutHub info")
    p_info.set_defaults(func=cmd_info)

    # summary
    p_summary = subparsers.add_parser("summary", help="Get comprehensive smart home dashboard summary")
    p_summary.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_summary.set_defaults(func=cmd_summary)

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

    # history
    p_hist = subparsers.add_parser("history", help="Get historical sensor/telemetry data")
    p_hist.add_argument("accessory_id", type=int, help="Accessory ID")
    p_hist.add_argument(
        "characteristic",
        nargs="?",
        default=None,
        help="Characteristic name (e.g. DIFF, Temperature) or cId or sId.cId",
    )
    p_hist.add_argument("--service", "-s", type=int, default=None, help="Service ID (sId)")
    p_hist.add_argument("--days", "-d", type=float, default=None, help="History window in days (e.g. 7)")
    p_hist.add_argument("--hours", "-H", type=float, default=None, help="History window in hours (e.g. 24)")
    p_hist.add_argument(
        "--limit",
        "-l",
        type=int,
        default=None,
        help="Max records limit (default: 500 without range, 10000 with --days/--hours)",
    )
    p_hist.set_defaults(func=cmd_history)

    # scenarios
    p_scenarios = subparsers.add_parser("scenarios", help="List automation scenarios")
    p_scenarios.add_argument("--search", "-s", type=str, default=None, help="Filter scenarios by name")
    p_scenarios.set_defaults(func=cmd_scenarios)

    # scenario
    p_scenario = subparsers.add_parser("scenario", help="Control automation scenario")
    sc_sub = p_scenario.add_subparsers(dest="scenario_action", required=True)
    p_sc_run = sc_sub.add_parser("run", help="Run scenario by name or index")
    p_sc_run.add_argument("scenario", help="Scenario index or name")
    p_sc_run.set_defaults(func=cmd_scenario_run)

    # logs
    p_logs = subparsers.add_parser("logs", help="View recent hub logs and errors")
    p_logs.add_argument("--count", "-n", type=int, default=50, help="Number of log entries (default 50)")
    p_logs.add_argument("--level", help="Filter by level (e.g. ERROR, WARN, INFO)")
    p_logs.add_argument("--search", "-s", help="Filter logs by message or path")
    p_logs.set_defaults(func=cmd_logs)

    # extensions
    p_exts = subparsers.add_parser("extensions", help="List installed protocols and extensions (Zigbee, BLE, etc.)")
    p_exts.set_defaults(func=cmd_extensions)

    # restart
    p_restart = subparsers.add_parser("restart", help="Restart SprutHub controller")
    p_restart.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    p_restart.set_defaults(func=cmd_restart)

    # room
    p_room = subparsers.add_parser("room", help="Manage rooms (create, rename, delete)")
    room_sub = p_room.add_subparsers(dest="room_action", required=True)

    p_r_create = room_sub.add_parser("create", help="Create a new room")
    p_r_create.add_argument("name", help="Room name")
    p_r_create.set_defaults(func=cmd_room_create)

    p_r_rename = room_sub.add_parser("rename", help="Rename an existing room")
    p_r_rename.add_argument("room", help="Room ID or current name")
    p_r_rename.add_argument("new_name", help="New room name")
    p_r_rename.set_defaults(func=cmd_room_rename)

    p_r_delete = room_sub.add_parser("delete", help="Delete a room")
    p_r_delete.add_argument("room", help="Room ID or name to delete")
    p_r_delete.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    p_r_delete.set_defaults(func=cmd_room_delete)

    # catalog
    p_cat = subparsers.add_parser("catalog", help="Inspect device templates and catalog")
    cat_sub = p_cat.add_subparsers(dest="catalog_action", required=True)

    p_cat_list = cat_sub.add_parser("list", help="List device templates in catalog")
    p_cat_list.add_argument("--search", "-s", help="Search by model or manufacturer (e.g. Aubess)")
    p_cat_list.add_argument("--limit", "-l", type=int, default=50, help="Max results (default 50)")
    p_cat_list.set_defaults(func=cmd_catalog_list)

    p_cat_get = cat_sub.add_parser("get", help="Get device template details")
    p_cat_get.add_argument("file", help="Template file path or model name")
    p_cat_get.add_argument("--store", default=None, help="Catalog store (e.g. MAIN)")
    p_cat_get.add_argument("--controller", default=None, help="Controller type (e.g. zigbee)")
    p_cat_get.set_defaults(func=cmd_catalog_get)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
