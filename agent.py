#!/usr/bin/env python3
"""
TelePAT Python Agent

Simple agent that polls the server for commands, executes them, and returns results.
Communicates with server.py via HTTP.

Agent ID Assignment:
- First run: Registers and polls API to discover assigned ID, saves to id.txt
- Future runs: Reads ID from id.txt
"""

import os
import time
import socket
import platform
import subprocess
import hashlib
import mimetypes
import base64
import requests # type: ignore
from typing import Dict, Any, Optional


# Configuration
AGENT_ID_FILE = os.path.join(os.path.dirname(__file__), "id.txt")
AGENT_DESCRIPTION = os.getenv("AGENT_DESCRIPTION", "")  # Optional: Human-readable description
AGENT_DOMAIN = os.getenv("AGENT_DOMAIN", "")  # Optional: Domain like "production" or "dev"
SERVER_URL = os.getenv("SERVER_URL", "http://10.20.30.4:44399")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "2"))  # seconds


def read_agent_id() -> Optional[int]:
    """Read agent ID from id.txt file if it exists"""
    if os.path.exists(AGENT_ID_FILE):
        try:
            with open(AGENT_ID_FILE, 'r') as f:
                agent_id = int(f.read().strip())
                print(f"Found existing agent ID: {agent_id}")
                return agent_id
        except (ValueError, IOError) as e:
            print(f"Warning: Could not read agent ID from {AGENT_ID_FILE}: {e}")
    return None


def save_agent_id(agent_id: int):
    """Save agent ID to id.txt file"""
    try:
        with open(AGENT_ID_FILE, 'w') as f:
            f.write(str(agent_id))
        print(f"Agent ID {agent_id} saved to {AGENT_ID_FILE}")
    except IOError as e:
        print(f"Warning: Could not save agent ID to {AGENT_ID_FILE}: {e}")


def execute_command(input_data: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    """Execute a shell command and return the result"""
    start_time = time.time()
    command = input_data.get("command", "")

    if not command:
        return {
            "stdout": "",
            "stderr": "No command specified",
            "exit_code": 1,
            "duration": 0,
            "error": "No command specified"
        }

    try:
        timeout_val = float(timeout) if timeout > 0 else None

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_val
        )

        duration = int((time.time() - start_time) * 1000)

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "duration": duration,
            "error": ""
        }

    except subprocess.TimeoutExpired:
        duration = int((time.time() - start_time) * 1000)
        return {
            "stdout": "",
            "stderr": "",
            "exit_code": 1,
            "duration": duration,
            "error": "command timed out"
        }

    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": 1,
            "duration": duration,
            "error": str(e)
        }


def download_file(input_data: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    """Download a file from agent and return file data"""
    start_time = time.time()
    file_path = input_data.get("path", "")

    if not file_path:
        return {
            "stdout": "",
            "stderr": "No file path specified",
            "exit_code": 1,
            "duration": 0,
            "error": "No file path specified"
        }

    try:
        # Check if file exists
        if not os.path.exists(file_path):
            return {
                "stdout": "",
                "stderr": f"File not found: {file_path}",
                "exit_code": 1,
                "duration": int((time.time() - start_time) * 1000),
                "error": f"File not found: {file_path}"
            }

        # Check if it's a file
        if not os.path.isfile(file_path):
            return {
                "stdout": "",
                "stderr": f"Path is not a file: {file_path}",
                "exit_code": 1,
                "duration": int((time.time() - start_time) * 1000),
                "error": f"Path is not a file: {file_path}"
            }

        # Read file
        with open(file_path, 'rb') as f:
            file_data = f.read()

        # Calculate hash
        file_hash = hashlib.sha256(file_data).hexdigest()

        # Get file info
        file_name = os.path.basename(file_path)
        file_size = len(file_data)
        file_mime, _ = mimetypes.guess_type(file_path)

        # Encode file data as base64
        file_data_b64 = base64.b64encode(file_data).decode('utf-8')

        duration = int((time.time() - start_time) * 1000)

        return {
            "result_type": "file",
            "file_name": file_name,
            "file_size": file_size,
            "file_mime": file_mime or "application/octet-stream",
            "file_data": file_data_b64,
            "file_hash": file_hash,
            "stdout": f"File downloaded: {file_name} ({file_size} bytes)",
            "stderr": "",
            "exit_code": 0,
            "duration": duration,
            "error": ""
        }

    except PermissionError:
        duration = int((time.time() - start_time) * 1000)
        return {
            "stdout": "",
            "stderr": f"Permission denied: {file_path}",
            "exit_code": 1,
            "duration": duration,
            "error": f"Permission denied: {file_path}"
        }

    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": 1,
            "duration": duration,
            "error": str(e)
        }


def upload_file(input_data: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    """Upload a file to agent"""
    start_time = time.time()
    file_path = input_data.get("path", "")

    # Support both "file_data" and "file" field names
    file_data = input_data.get("file_data") or input_data.get("file")

    # If file is a dict with 'data' or 'content', extract it
    if isinstance(file_data, dict):
        file_data = file_data.get("data") or file_data.get("content") or file_data.get("file_data")

    if not file_path:
        return {
            "stdout": "",
            "stderr": "No file path specified",
            "exit_code": 1,
            "duration": 0,
            "error": "No file path specified"
        }

    if not file_data:
        return {
            "stdout": "",
            "stderr": "No file data provided",
            "exit_code": 1,
            "duration": 0,
            "error": "No file data provided"
        }

    try:
        # Convert list back to bytes
        if isinstance(file_data, list):
            file_bytes = bytes(file_data)
        elif isinstance(file_data, str):
            # Base64 encoded
            file_bytes = base64.b64decode(file_data)
        else:
            file_bytes = file_data

        # Create parent directories if needed
        dir_path = os.path.dirname(file_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

        # Write file
        with open(file_path, 'wb') as f:
            f.write(file_bytes)

        # Verify file
        file_size = len(file_bytes)
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        duration = int((time.time() - start_time) * 1000)

        return {
            "stdout": f"File uploaded successfully: {file_path} ({file_size} bytes, hash: {file_hash})",
            "stderr": "",
            "exit_code": 0,
            "duration": duration,
            "error": ""
        }

    except PermissionError:
        duration = int((time.time() - start_time) * 1000)
        return {
            "stdout": "",
            "stderr": f"Permission denied: {file_path}",
            "exit_code": 1,
            "duration": duration,
            "error": f"Permission denied: {file_path}"
        }

    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": 1,
            "duration": duration,
            "error": str(e)
        }


def get_command_from_server(agent_id: int):
    """Poll server for pending commands using agent ID"""
    try:
        print(f"[POLL] Requesting commands for agent {agent_id}")
        response = requests.get(
            f"{SERVER_URL}/commands",
            params={"agent_id": agent_id},
            timeout=10
        )

        print(f"[POLL] Response status: {response.status_code}")
        print(f"[POLL] Response body: {response.text[:200]}")  # First 200 chars

        if response.status_code == 200:
            data = response.json()
            print(f"[POLL] Parsed JSON: {data}")

            if data.get("no_command"):
                print(f"[POLL] No commands available")
                return None

            print(f"[POLL] Command received: {data.get('command_id', 'NO_ID')}")
            return data
        else:
            print(f"[POLL] Error getting commands: {response.status_code}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"[POLL] Failed to get commands from server: {e}")
        return None


def send_result_to_server(command_id: str, result: Dict[str, Any]):
    """Send execution result to server"""
    try:
        result["command_id"] = command_id

        response = requests.post(
            f"{SERVER_URL}/results",
            json=result,
            timeout=10
        )

        if response.status_code == 200:
            print(f"Result sent for command {command_id}")
        else:
            print(f"Error sending result: {response.status_code}")

    except requests.exceptions.RequestException as e:
        print(f"Failed to send result to server: {e}")


def register_with_server() -> Optional[int]:
    """Register agent with server on startup

    Returns:
        int: Assigned agent_id on success
        None: On failure
    """
    try:
        # Build registration data with optional fields
        registration_data = {
            "hostname": socket.gethostname(),
            "os": platform.system().lower(),
            "arch": platform.machine(),
            "version": "1.0.0"
        }

        # Add optional fields if set
        if AGENT_DESCRIPTION:
            registration_data["description"] = AGENT_DESCRIPTION
        if AGENT_DOMAIN:
            registration_data["domain"] = AGENT_DOMAIN

        response = requests.post(
            f"{SERVER_URL}/register",
            json=registration_data,
            timeout=10  # Increased timeout for ACK wait
        )

        if response.status_code == 200:
            result = response.json()
            agent_id = result.get('agent_id')
            if agent_id:
                print(f"Registration successful: {result.get('message')}")
                print(f"Assigned agent ID: {agent_id}")
                return agent_id
            else:
                print(f"Registration response missing agent_id: {result}")
                return None
        else:
            print(f"Registration failed: {response.status_code}")
            try:
                error_data = response.json()
                print(f"Error: {error_data.get('error') or error_data.get('message')}")
            except:
                pass
            return None

    except requests.exceptions.RequestException as e:
        print(f"Failed to register with server: {e}")
        return None


def main():
    """Main agent loop"""
    print("=" * 50)
    print("  TelePAT Python Agent")
    print("=" * 50)
    print()
    print(f"Server URL:     {SERVER_URL}")
    print(f"Poll Interval:  {POLL_INTERVAL}s")
    print(f"ID File:        {AGENT_ID_FILE}")
    if AGENT_DESCRIPTION:
        print(f"Description:    {AGENT_DESCRIPTION}")
    if AGENT_DOMAIN:
        print(f"Domain:         {AGENT_DOMAIN}")
    print()

    # Check if we have an existing agent ID
    agent_id = read_agent_id()

    if agent_id is None:
        # First run - need to register and get assigned ID
        print("No existing agent ID found. Registering...")

        # Register with server (retry a few times)
        agent_id = None
        for attempt in range(5):
            agent_id = register_with_server()
            if agent_id:
                break
            print(f"Registration attempt {attempt + 1} failed, retrying in 2 seconds...")
            time.sleep(2)

        if agent_id is None:
            print("Error: Could not register with server and get agent ID. Exiting.")
            print("Please check:")
            print("  1. Server.py is running and connected to relay")
            print("  2. Relay is connected to core")
            print("  3. Core is processing registrations")
            return

        # Save the agent ID for future runs
        save_agent_id(agent_id)
        print(f"Agent ID {agent_id} saved for future runs")
    else:
        print(f"Using existing agent ID: {agent_id}")

    print()
    print("Starting agent...")
    print("(Press Ctrl+C to stop)")
    print()

    try:
        while True:
            # Poll server for commands using our agent ID
            command_data = get_command_from_server(agent_id)

            if command_data:
                command_id = command_data.get("command_id")
                command_type = command_data.get("command_type")
                input_data = command_data.get("input_data", {})
                timeout = command_data.get("timeout", 0)

                print(f"[EXECUTE] Received command: {command_type} (ID: {command_id})")
                print(f"[EXECUTE] Input data: {input_data}")

                # Execute command based on type
                if command_type == "execute":
                    result = execute_command(input_data, timeout)
                elif command_type == "download":
                    result = download_file(input_data, timeout)
                elif command_type == "upload":
                    result = upload_file(input_data, timeout)
                else:
                    result = {
                        "stdout": "",
                        "stderr": f"Unsupported command type: {command_type}",
                        "exit_code": 1,
                        "duration": 0,
                        "error": f"Unsupported command type: {command_type}"
                    }

                # Send result back to server
                print(f"[EXECUTE] Sending result for command {command_id}")
                send_result_to_server(command_id, result)
                print(f"[EXECUTE] Result sent successfully")

            # Wait before next poll
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\nAgent stopped by user")


if __name__ == "__main__":
    main()
