import subprocess
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SERVER_SCRIPT = str(BASE_DIR / "server.py")

def test_mcp_server():
    proc = subprocess.Popen(
        [sys.executable, SERVER_SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=0
    )
    
    # 1. Initialize
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"}
        }
    }
    
    proc.stdin.write(json.dumps(init_request) + "\n")
    proc.stdin.flush()
    
    line = proc.stdout.readline()
    print("Initialize response:", line.strip())
    
    # Send initialized notification
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    proc.stdin.flush()
    
    # 2. List tools
    tools_request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }
    proc.stdin.write(json.dumps(tools_request) + "\n")
    proc.stdin.flush()
    
    line2 = proc.stdout.readline()
    data2 = json.loads(line2)
    tools = data2.get("result", {}).get("tools", [])
    print(f"\nDiscovered tools ({len(tools)}):")
    for t in tools:
        print(f" - {t.get('name')}: {t.get('description')}")
        
    proc.terminate()
    print("\nMCP Protocol Test Successful!")

if __name__ == '__main__':
    test_mcp_server()
