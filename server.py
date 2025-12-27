#!/usr/bin/env python3
"""
TelePAT Agent Server

Simple HTTP bridge between agents and relay.
Agents poll for commands and push results.
Server communicates with relay using SlotSDK (WebSocket).
"""

import os
import threading
from datetime import datetime, UTC
from typing import Dict, Any, Optional
from flask import Flask, request, jsonify

from SlotSDK import SlotSDK


# Configuration
SERVER_PORT = 44399
RELAY_URL = os.getenv("RELAY_URL", "ws://192.168.230.133:8081/ws")
SLOT_ID = os.getenv("SLOT_ID", "py-slot")

app = Flask(__name__)

# Global variables
sdk: Optional[SlotSDK] = None


def handle_relay_command(msg: Dict[str, Any]):
    """
    Handle COMMAND message from relay

    In pull-based mode, unsolicited commands should not arrive.
    This handler is kept for backward compatibility and logging.
    """
    try:
        payload = msg.get("payload", {})
        agent_id = payload.get("agent_id") or msg.get("agent_id")
        command_id = payload.get("command_id")

        # Log warning - in pull-based mode, commands should only arrive as responses
        print(f"Warning: Received unsolicited COMMAND (not pull-based): agent_id={agent_id}, command_id={command_id}")
        print(f"This should not happen in pull-based mode. Message: {msg}")

    except Exception as e:
        print(f"Error handling command: {e}")


@app.route('/commands', methods=['GET'])
def get_commands():
    """
    Agent polls for pending commands - forwards request to relay (pull-based)

    Query params:
        agent_id: The agent identifier (integer)

    Returns:
        Command payload or {"no_command": true}
    """
    agent_id = request.args.get('agent_id', type=int)
    print(f"[/commands] Agent {agent_id} polling for commands")

    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400

    try:
        # Check if SDK is connected
        if not sdk or not sdk.connected:
            print(f"[/commands] SDK not connected to relay")
            return jsonify({"error": "Not connected to relay"}), 503

        # Request command from relay synchronously (waits for response)
        print(f"[/commands] Requesting commands from relay for agent {agent_id}")
        command = sdk.request_commands(agent_id, count=1, timeout=5)

        print(f"[/commands] Relay response: {command}")

        if command is None:
            # Timeout or no commands available
            print(f"[/commands] No commands available, returning no_command")
            return jsonify({"no_command": True})

        # Return command to agent
        print(f"[/commands] Returning command to agent: {command}")
        return jsonify(command)

    except Exception as e:
        print(f"[/commands] Error in get_commands: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/results', methods=['POST'])
def post_results():
    """
    Agent posts execution result

    JSON body must contain:
        command_id: The command that was executed
        (other result fields: stdout, stderr, exit_code, etc.)

    Note: agent_id not required - relay knows from command_id
    """
    try:
        result = request.get_json()
        if not result:
            return jsonify({"error": "JSON body required"}), 400

        command_id = result.get('command_id')
        if not command_id:
            return jsonify({"error": "command_id required"}), 400

        # Send result to relay (relay will lookup agent from command_id)
        if sdk and sdk.connected:
            sdk.send_result(command_id, result)
            print(f"Result forwarded to relay: {command_id}")
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Not connected to relay"}), 503

    except Exception as e:
        print(f"Error in post_results: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/register', methods=['POST'])
def register_agent():
    """
    Agent registers itself with the slot

    JSON body (all fields optional):
        description: Human-readable description (e.g., "My laptop agent")
        hostname: Agent hostname
        os: Operating system
        arch: Architecture
        domain: Domain/environment (e.g., "production", "dev")
        version: Agent version

    Returns:
        success: Boolean
        message: Status message
        Note: Core assigns agent_id. Agent should poll API to discover it.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        # All fields are optional
        description = data.get('description')
        hostname = data.get('hostname')
        os_name = data.get('os')
        arch = data.get('arch')
        domain = data.get('domain')
        version = data.get('version', '1.0.0')

        # Send registration to relay (relay will forward to core)
        if sdk and sdk.connected:
            # Wait for ACK response with agent_id (timeout after 10 seconds)
            result = sdk.send_agent_registration(description, hostname, os_name, arch, domain, version, timeout=10)

            if isinstance(result, int):
                # Success - got agent_id
                print(f"Agent registered successfully: agent_id={result}")
                return jsonify({
                    "success": True,
                    "agent_id": result,
                    "message": f"Agent registered successfully with ID {result}"
                })
            elif isinstance(result, dict) and "error" in result:
                # Error from core
                print(f"Agent registration failed: {result['error']}")
                return jsonify({
                    "success": False,
                    "error": result['error']
                }), 400
            else:
                # Timeout or unexpected response
                print("Agent registration timeout - no response from core")
                return jsonify({
                    "success": False,
                    "error": "Registration timeout - core did not respond"
                }), 504
        else:
            # SDK not connected yet
            print(f"Warning: Agent registration received but SDK not connected yet")
            return jsonify({
                "success": False,
                "message": "Slot server connecting to relay, please retry in a moment"
            }), 503

    except Exception as e:
        print(f"Error in register_agent: {e}")
        return jsonify({"error": str(e)}), 500


def run_flask():
    """Run Flask HTTP server"""
    print(f"Starting HTTP server on port {SERVER_PORT}...")
    app.run(host='0.0.0.0', port=SERVER_PORT, debug=False, use_reloader=False)


def run_sdk():
    """Run SlotSDK to connect to relay"""
    global sdk

    print(f"Connecting to relay at {RELAY_URL}...")
    sdk = SlotSDK(RELAY_URL, SLOT_ID, handle_relay_command)

    try:
        sdk.run()
    except KeyboardInterrupt:
        print("\nShutting down SDK...")
        sdk.stop()


def main():
    """Main entry point"""
    print("=" * 40)
    print("  TelePAT Slot Server")
    print("=" * 40)
    print()
    print(f"HTTP Port:  {SERVER_PORT}")
    print(f"Relay URL:  {RELAY_URL}")
    print(f"Slot ID:   {SLOT_ID}")
    print()

    # Start Flask in separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Wait for Flask to start
    import time
    time.sleep(2)

    # Run SDK in main thread (handles Ctrl+C)
    try:
        run_sdk()
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    finally:
        if sdk:
            sdk.stop()

        # Clean up PID file on shutdown
        pid_file = os.path.join(os.path.dirname(__file__), "logs", "server.pid")
        if os.path.exists(pid_file):
            try:
                os.remove(pid_file)
                print(f"Removed PID file: {pid_file}")
            except Exception as e:
                print(f"Warning: Could not remove PID file: {e}")


if __name__ == "__main__":
    main()