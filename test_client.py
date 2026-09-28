import asyncio
import json
import os
import sys
from pathlib import Path

# Add current folder to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from spruthub_client import SprutHubClient

async def main():
    config_path = BASE_DIR / "config.json"
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    ws_url = os.environ.get("SPRUTHUB_WS_URL", config.get("ws_url", "ws://127.0.0.1/spruthub"))
    token = os.environ.get("SPRUTHUB_TOKEN", config.get("token", ""))
    serial = os.environ.get("SPRUTHUB_SERIAL", config.get("serial", ""))

    if not token or not serial:
        print("Error: SPRUTHUB_TOKEN and SPRUTHUB_SERIAL must be configured in config.json or environment variables.")
        sys.exit(1)

    client = SprutHubClient(
        ws_url=ws_url,
        token=token,
        serial=serial
    )
    print(f"Connecting to SprutHub at {ws_url}...")
    info = await client.get_hub_info()
    print("Hub name:", info.get("name"), "version:", info.get("version", {}).get("current", {}).get("version"))
    
    rooms = await client.list_rooms()
    print(f"Rooms found ({len(rooms)}):", [r.get("name") for r in rooms])
    
    accessories = await client.list_accessories()
    print(f"Accessories found ({len(accessories)})")
    if accessories:
        first_acc = accessories[0]
        acc_id = first_acc.get("id")
        acc = await client.get_accessory(acc_id)
        print(f"Accessory {acc_id} ({acc.get('name')}) services:", [s.get("type") for s in acc.get("services", [])])
    
    await client.close()
    print("Client tests passed successfully!")

if __name__ == '__main__':
    asyncio.run(main())
