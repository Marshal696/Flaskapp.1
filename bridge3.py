from SlotSDK import SlotSDK
import requests
import sqlite3
import threading
import time
import socket
import platform
import os
import uuid
from flask import Flask, request, jsonify


RELAY_URL = "ws://192.168.230.133:8081/ws"
SLOT_ID = "backpro-multi-agent"
BACKPRO_URL = "http://127.0.0.1:5000"
HTTP_PORT = 5001

app = Flask(__name__)

class BridgeState:
    sdk = None

implant_mapping = {} 
telepat_to_implant = {}  
command_mapping = {}  
reverse_command_mapping = {}  

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] [Bridge] {msg}")

def forward_to_backpro(command, arguments="", backpro_agent_id=1):
    try:
        payload = {
            "command_text": command,
            "arguments": arguments or "",
            "agent_id": backpro_agent_id
        }
        r = requests.post(
            f"{BACKPRO_URL}/api/admin/commands",
            json=payload,
            timeout=10
        )
        if r.status_code in (200, 201):
            resp = r.json()
            backpro_cmd_id = resp.get("id") or resp.get("command_id")
            if backpro_cmd_id:
                log(f"Command forwarded to Backpro agent {backpro_agent_id} (Backpro cmd ID: {backpro_cmd_id})")
            else:
                log("Command forwarded but no Backpro command_id returned")
        else:
            log(f"Forward failed: HTTP {r.status_code} - {r.text}")
    except Exception as e:
        log(f"Error forwarding to Backpro: {e}")

def send_results_to_telepat():
    try:
        conn = sqlite3.connect("db.sqlite")
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.id, r.result_data, r.command_id
            FROM Results r
            WHERE r.id > (SELECT COALESCE(MAX(result_id), 0) FROM sent_results)
        """)
        rows = cursor.fetchall()
        conn.close()

        for result_id, result_data, backpro_cmd_id in rows:
            if BridgeState.sdk and BridgeState.sdk.connected and BridgeState.sdk.registered:
                telepat_cmd_id = reverse_command_mapping.get(backpro_cmd_id, "unknown")
                result_payload = {
                    "stdout": result_data.strip(),
                    "stderr": "",
                    "exit_code": 0,
                    "duration": 0,
                    "finished": True
                }
                BridgeState.sdk.send_result(telepat_cmd_id, result_payload)
                log(f"Result sent to TelePAT for command ID: {telepat_cmd_id}")

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
    while True:
        if BridgeState.sdk.registered and BridgeState.sdk.connected:
            for telepat_agent_id in telepat_to_implant.keys():
                cmd = BridgeState.sdk.request_commands(
                    agent_id=telepat_agent_id,
                    count=1,
                    timeout=10
                )
                if cmd:
                    telepat_cmd_id = cmd.get("command_id")
                    command_text = cmd.get("input_data", {}).get("command", "").strip()
                    arguments = cmd.get("input_data", {}).get("arguments", "")

                    if not command_text:
                        continue

                    backpro_agent_id = telepat_to_implant[telepat_agent_id]

                    log(f"Command for TelePAT agent {telepat_agent_id} (Backpro agent {backpro_agent_id}): {command_text}")

                    try:
                        payload = {
                            "command_text": command_text,
                            "arguments": arguments,
                            "agent_id": backpro_agent_id
                        }
                        r = requests.post(f"{BACKPRO_URL}/api/admin/commands", json=payload, timeout=10)
                        if r.status_code in (200, 201):
                            resp = r.json()
                            backpro_cmd_id = resp.get("id") or resp.get("command_id")
                            if backpro_cmd_id:
                                command_mapping[telepat_cmd_id] = backpro_cmd_id
                                reverse_command_mapping[backpro_cmd_id] = telepat_cmd_id
                                log(f"Mapped TelePAT cmd {telepat_cmd_id} <-> Backpro cmd {backpro_cmd_id}")
                            log(f"Command forwarded to Backpro agent {backpro_agent_id}")
                        else:
                            log(f"Forward failed: {r.status_code}")
                    except Exception as e:
                        log(f"Error forwarding: {e}")

        time.sleep(5)

def register_agents():
    global implant_mapping, telepat_to_implant
    implants = [
        {"hostname": "IMPLANT-PC1", "uuid": str(uuid.uuid4())},
        {"hostname": "IMPLANT-PC2", "uuid": str(uuid.uuid4())},
        {"hostname": "IMPLANT-PC3", "uuid": str(uuid.uuid4())},
    ]

    backpro_agent_id = 1
    for imp in implants:
        description = f"Backpro Implant - {imp['hostname']}"
        result = BridgeState.sdk.send_agent_registration(
            description=description,
            hostname=imp['hostname'],
            os_name=platform.system().lower(),
            arch=platform.machine(),
            version="1.0.0",
            timeout=60
        )
        if isinstance(result, int):
            implant_mapping[backpro_agent_id] = {
                "telepat_agent_id": result,
                "hostname": imp['hostname'],
                "uuid": imp['uuid']
            }
            telepat_to_implant[result] = backpro_agent_id
            log(f"Registered TelePAT agent {result} for Backpro agent {backpro_agent_id} ({imp['hostname']})")
            backpro_agent_id += 1
        else:
            log(f"Failed to register agent for {imp['hostname']}")

if __name__ == "__main__":
    log("Starting Multi-Agent TelePAT → Backpro Bridge")

    conn = sqlite3.connect("db.sqlite")
    conn.execute("CREATE TABLE IF NOT EXISTS sent_results (result_id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    BridgeState.sdk = SlotSDK(RELAY_URL, SLOT_ID, lambda msg: None, heartbeat_interval=30)
    threading.Thread(target=BridgeState.sdk.run, daemon=True).start()

    while not (BridgeState.sdk.registered and BridgeState.sdk.connected):
        time.sleep(1)
    log("Slot registered and connected")

    register_agents()
    log("All agents registered")

    threading.Thread(target=command_polling_loop, daemon=True).start()
    log("Multi-agent command polling started")

    threading.Thread(target=background_loop, daemon=True).start()

    log("Multi-agent bridge fully active")
    while True:
        time.sleep(60)