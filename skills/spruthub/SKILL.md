---
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
