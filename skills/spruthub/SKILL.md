---
name: spruthub
description: Control and monitor SprutHub smart home (lights, switches, rooms, sensors, temperature) on-demand via lightweight CLI without background daemon overhead.
---

# SprutHub Smart Home Skill

Use this skill whenever the user asks to inspect, monitor, or control devices in their **SprutHub** smart home (e.g. "включи свет в спальне", "какая температура в кабинете", "список комнат", "выключи розетку").

## Execution Mode

Always execute commands via `uvx` (or local `uv run` if inside workspace) using `spruthub-cli`. This executes on-demand in ~80 ms without keeping any background daemon or eating RAM.

### Command Format

```bash
# Via uvx (recommended for any system):
uvx --from git+https://github.com/pikerr/spruthub-mcp spruthub-cli <command> [args]

# Or locally within workspace:
uv run spruthub-cli <command> [args]
```

## Quick Reference

### 1. Hub Status & Rooms
* **Hub info:**
  `uv run spruthub-cli info`
* **List all rooms (with current sensor readings):**
  `uv run spruthub-cli rooms`

### 2. Finding & Inspecting Devices
* **List controllable devices in a specific room:**
  `uv run spruthub-cli devices --room <room_id>`
* **Search devices by name:**
  `uv run spruthub-cli devices --search "свет"`
* **Inspect full device characteristics:**
  `uv run spruthub-cli device <accessory_id>`

### 3. Controlling Switches, Lights & Outlets
* **Turn ON:**
  `uv run spruthub-cli switch <accessory_id> on`
* **Turn OFF:**
  `uv run spruthub-cli switch <accessory_id> off`

### 4. Setting Characteristics (Brightness, Target Temp, Modes)
* **Set specific value:**
  `uv run spruthub-cli set <accessory_id> <service_id> <characteristic_id> <value>`
  * Example: `uv run spruthub-cli set 1014 1 2 22.5`

## Guidelines for the Agent
1. If the user asks about a room (e.g., "что включено в кабинете?"), run `spruthub-cli rooms` to get the `room_id`, then `spruthub-cli devices --room <id>` to see the exact state.
2. If turning a switch on/off, use `spruthub-cli switch <id> on/off`. It automatically detects the correct Switch/Lightbulb/Outlet service without needing `sId` or `cId`.
3. Provide a clear, concise confirmation to the user in Russian.
