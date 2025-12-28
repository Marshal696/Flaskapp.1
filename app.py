from flask import Flask, request, jsonify
from admin.app import admin_bp
from client.app import client_bp
import os
import sqlite3
from datetime import datetime
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
import secrets
import base64
import socket
import platform
import threading
import uuid
import time
import requests
import sqlite3
import json

app = Flask(__name__)

MASTER_KEY = os.environ.get("MASTER_KEY")
if not MASTER_KEY:
    raise ValueError("MASTER_KEY environment variable is required")

app.register_blueprint(admin_bp)
app.register_blueprint(client_bp)

def encrypt_data(data, key_hex):
    key_bytes = bytes.fromhex(key_hex)
    iv = os.urandom(16)
    data_str = json.dumps(data).encode('utf-8')
    pad_len = 16 - (len(data_str) % 16)
    data_str += bytes([pad_len] * pad_len)
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(data_str) + encryptor.finalize()
    result = iv + encrypted
    return base64.b64encode(result).decode('utf-8')

def decrypt_data(encrypted_b64, key_hex):
    key_bytes = bytes.fromhex(key_hex)
    data = base64.b64decode(encrypted_b64)
    iv = data[:16]
    ciphertext = data[16:]
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_padded = decryptor.update(ciphertext) + decryptor.finalize()
    pad_len = decrypted_padded[-1]
    decrypted = decrypted_padded[:-pad_len]
    return json.loads(decrypted.decode('utf-8'))

@app.route('/api/client/handshake', methods=['POST'])
def handshake():
    try:
        data = request.get_json()
        client_uuid = data.get('uuid')
        client_public_key_pem = data.get('public_key')

        if not client_uuid or not client_public_key_pem:
            return jsonify({"message": "uuid and public_key required"}), 400

        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()
        cursor.execute("SELECT uuid FROM agents WHERE uuid = ?", (client_uuid,))
        if cursor.fetchone():
            conn.close()
            return jsonify({"message": "agent already registered"}), 400

        aes_key_bytes = secrets.token_bytes(16)
        aes_key_hex = aes_key_bytes.hex()

        public_key = serialization.load_pem_public_key(client_public_key_pem.encode(), backend=default_backend())
        encrypted_aes_key = public_key.encrypt(
            aes_key_bytes,
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA1()), algorithm=hashes.SHA1(), label=None)
        )
        encrypted_aes_key_b64 = base64.b64encode(encrypted_aes_key).decode('utf-8')

        encrypted_aes_for_db = encrypt_data({"key": aes_key_hex}, MASTER_KEY)

        cursor.execute("""
            INSERT INTO agents 
            (uuid, aes_key_encrypted, last_seen, status, hostname, os_arch, version, connected)
            VALUES (?, ?, ?, 'active', '', '', '', 0)
        """, (client_uuid, encrypted_aes_for_db, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

        return jsonify({"encrypted_aes_key": encrypted_aes_key_b64}), 200

    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/')
def home():
    return "<h1>Backpro is up!!!!</h1>"

@app.route('/api/agents', methods=['GET'])
def get_agents():
    try:
        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()

        search = request.args.get('search', '').lower().strip()
        status = request.args.get('status')
        sort_by = request.args.get('sort_by', 'last_seen')
        sort_order = request.args.get('sort_order', 'desc')

        query = "SELECT id, uuid, hostname, os_arch, version, status, connected, last_seen FROM agents WHERE 1=1"
        params = []

        if search:
            query += " AND (hostname LIKE ? OR description LIKE ?)"
            like_search = f"%{search}%"
            params.extend([like_search, like_search])

        if status and status != 'All Status':
            query += " AND status = ?"
            params.append(status)

        valid_sort = {'uuid': 'uuid', 'hostname': 'hostname', 'last_seen': 'last_seen', 'status': 'status'}
        sort_field = valid_sort.get(sort_by, 'last_seen')
        order = 'DESC' if sort_order.lower() == 'desc' else 'ASC'
        query += f" ORDER BY {sort_field} {order}"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        agents = []
        for row in rows:
            agents.append({
                "id": row[0],
                "agent_id": row[1],
                "hostname": row[2],
                "os_arch": row[3],
                "version": row[4],
                "status": row[5],
                "connected": row[6],
                "last_seen": row[7]
            })

        conn.close()
        return jsonify({"status": "success", "agents": agents, "total": len(agents)}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)