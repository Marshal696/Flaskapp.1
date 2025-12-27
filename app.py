from flask import Flask, request, jsonify
from admin.app import admin_bp
from client.app import client_bp   
import os
import socket
import platform
import threading
import uuid
import time
import requests
import sqlite3
from SlotSDK import SlotSDK

app = Flask(__name__)


app.register_blueprint(admin_bp)
app.register_blueprint(client_bp)

@app.route('/')
def home():
    return "<h1> Backpro is up!!!!</h1>"


@app.route('/api/agents', methods=['GET'])
def get_agents():
    try:
        conn = sqlite3.connect("db.sqlite")  # یا دیتابیس پنل TelePAT
        cursor = conn.cursor()

        # پارامترهای فیلتر/جستجو/مرتب‌سازی
        search = request.args.get('search', '').lower().strip()
        status = request.args.get('status')  # e.g., 'connected', 'disconnected', 'sleep'
        relay = request.args.get('relay')  # اگر فیلتر relay وجود داره
        sort_by = request.args.get('sort_by', 'last_seen')  # default: last_seen
        sort_order = request.args.get('sort_order', 'desc')  # asc یا desc

        # کوئری پایه
        query = """
            SELECT id, agent_id, hostname, os_arch, version, status, connected, last_seen
            FROM agents
            WHERE 1=1
        """
        params = []

        # جستجو در hostname یا description
        if search:
            query += " AND (hostname LIKE ? OR description LIKE ?)"
            like_search = f"%{search}%"
            params.extend([like_search, like_search])

        # فیلتر وضعیت (status)
        if status and status != 'All Status':
            query += " AND status = ?"
            params.append(status)

        # فیلتر relay (اگر وجود داره)
        if relay and relay != 'All Relays':
            query += " AND relay_id = ?"
            params.append(relay)

        # مرتب‌سازی
        valid_sort = {'agent_id': 'agent_id', 'hostname': 'hostname', 'last_seen': 'last_seen', 'status': 'status'}
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

        return jsonify({
            "status": "success",
            "agents": agents,
            "total": len(agents)
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)


