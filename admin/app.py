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
            agent_id INTEGER DEFAULT 1,  -- اضافه شد
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