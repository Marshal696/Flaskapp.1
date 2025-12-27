
"""
TelePAT SlotSDK - Python SDK for communicating with Relay servers

This SDK handles all communication with the Relay server including:
- WebSocket connection management
- Agent registration
- Heartbeat mechanism
- Command polling
- Message handling
"""

import json
import socket
import platform
import time
import uuid
from datetime import datetime, UTC
from typing import Dict, Any, Optional, Callable
from urllib.parse import urlparse, urlunparse

try:
    import websocket
except ImportError:
    print("Error: websocket-client is not installed")
    print("Please install it with: pip install websocket-client")
    import sys
    sys.exit(1)


def _log_timestamp():
    """Return formatted timestamp for logging"""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class SlotSDK:
    """
    SlotSDK - Python SDK for TelePAT Agent-Relay communication

    This SDK manages the WebSocket connection to the Relay server and handles
    the communication protocol, allowing agents to focus on command execution.
    """

    def __init__(
        self,
        relay_url: str,
        slot_id: str,
        command_handler: Callable[[Dict[str, Any]], None],
        heartbeat_interval: int = 10,
        command_poll_interval: int = 5
    ):
        """
        Initialize the SlotSDK

        Args:
            relay_url: WebSocket URL of the relay registration endpoint (e.g., ws://localhost:8081/ws)
            slot_id: Unique identifier for this slot (server.py instance)
            command_handler: Callback function to handle command execution
            heartbeat_interval: Seconds between heartbeat messages (default: 10)
            command_poll_interval: Seconds between command poll requests (default: 5)
        """
        self.registration_url = relay_url
        self.assigned_url: Optional[str] = None
        self.slot_id = slot_id
        self.command_handler = command_handler
        self.ws: Optional[websocket.WebSocketApp] = None
        self.connected = False
        self.registered = False
        self.switching_ports = False
        self.should_run = True
        self.heartbeat_interval = heartbeat_interval
        self.last_heartbeat = 0
        self.command_poll_interval = command_poll_interval
        self.last_command_poll = 0

        # Track pending agent registrations and their responses
        self.pending_agent_registrations = {}  # message_id -> event for waiting
        self.agent_registration_responses = {}  # message_id -> agent_id or error

        # Track pending command requests and their responses (for pull-based)
        self.pending_command_requests = {}  # message_id -> event for waiting
        self.command_responses = {}  # message_id -> command data or None

    def connect(self, url: str = None):
        """
        Connect to the Relay WebSocket server

        Args:
            url: Optional specific URL to connect to (defaults to assigned_url or registration_url)
        """
        connect_url = url or (self.assigned_url if self.registered else self.registration_url)
        print(f"[{_log_timestamp()}] [SDK] Connecting to Relay at {connect_url}...")

        self.ws = websocket.WebSocketApp(
            connect_url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open
        )

        # Set max message size to None (unlimited) for large file transfers
        self.ws.max_size = None

    def on_open(self, ws):
        """Called when WebSocket connection is established"""
        self.connected = True

        if not self.registered:
            print(f"[{_log_timestamp()}] [SDK] Connected to Relay registration port")
            self.register()
        else:
            print(f"[{_log_timestamp()}] [SDK] Connected to dedicated port: {self.assigned_url}")
            print(f"[{_log_timestamp()}] [SDK] Heartbeat enabled (command polling is on-demand only)")
            # Send a heartbeat immediately after reconnecting
            self.send_heartbeat()
            # Don't automatically request commands - let agents poll when they want

    def on_message(self, ws, message):
        """Handle incoming messages from Relay"""
        try:
            msg = json.loads(message)
            msg_type = msg.get("type")

            if msg_type == "ACK":
                self.handle_ack(msg)
            elif msg_type == "COMMAND":
                self.handle_command(msg)
            else:
                print(f"[{_log_timestamp()}] [SDK] Unknown message type: {msg_type}")

        except json.JSONDecodeError as e:
            print(f"[{_log_timestamp()}] [SDK] Failed to parse message: {e}")
        except Exception as e:
            print(f"[{_log_timestamp()}] [SDK] Error handling message: {e}")

    def on_error(self, ws, error):
        """Handle WebSocket errors"""
        print(f"[{_log_timestamp()}] [SDK] WebSocket error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket connection close"""
        self.connected = False
        print(f"[{_log_timestamp()}] [SDK] Connection closed: {close_status_code} - {close_msg}")

        # If we're switching ports intentionally, don't reset
        if self.switching_ports:
            print(f"[{_log_timestamp()}] [SDK] Switching to dedicated port...")
            self.switching_ports = False
            return

        # If we were on a dedicated port, immediately reset to re-register
        if self.registered:
            print(f"[{_log_timestamp()}] [SDK] Dedicated port connection lost. Will re-register on next connection.")
            self.registered = False
            self.assigned_url = None

    def register(self):
        """Send registration message to Relay"""
        hostname = socket.gethostname()

        payload = {
            "agent_id": self.slot_id,
            "relay_id": "",
            "hostname": hostname,
            "os": platform.system().lower(),
            "arch": platform.machine(),
            "version": "1.0.0"
        }

        message = {
            "id": str(uuid.uuid4()),
            "type": "SLOT_REGISTER",
            "relay_id": "",
            "agent_id": self.slot_id,
            "payload": payload,
            "timestamp": datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        }

        self.send_message(message)
        print(f"[{_log_timestamp()}] [SDK] Registration sent: slot_id={self.slot_id}")

    def handle_ack(self, msg: Dict[str, Any]):
        """Handle acknowledgment messages"""
        payload = msg.get("payload", {})
        success = payload.get("success", False)
        message_id = payload.get("original_message_id", "")  # Original message ID from AGENT_REGISTER
        assigned_port = payload.get("assigned_port", 0)
        agent_id = payload.get("agent_id")  # For AGENT_REGISTER ACK

        print(f"[{_log_timestamp()}] [SDK] ACK received: message_id={message_id}, success={success}, agent_id={agent_id}")
        print(f"[{_log_timestamp()}] [SDK] DEBUG: Pending registrations: {list(self.pending_agent_registrations.keys())}")

        # Check if this is an agent registration ACK
        if message_id in self.pending_agent_registrations:
            if success and agent_id:
                print(f"[{_log_timestamp()}] [SDK] Agent registration successful: agent_id={agent_id}")
                self.agent_registration_responses[message_id] = agent_id
            else:
                error = payload.get("error", "Unknown error")
                print(f"[{_log_timestamp()}] [SDK] Agent registration failed: {error}")
                self.agent_registration_responses[message_id] = {"error": error}

            # Signal the waiting thread
            if message_id in self.pending_agent_registrations:
                self.pending_agent_registrations[message_id].set()
            return

        if not success:
            error = payload.get("error", "")
            print(f"[{_log_timestamp()}] [SDK] ACK error: {error}")
            return

        # Check if this is a slot registration ACK with port assignment
        if assigned_port > 0 and not self.registered:
            print(f"[{_log_timestamp()}] [SDK] Port assigned: {assigned_port}")

            # Parse the registration URL to replace port
            parsed = urlparse(self.registration_url)

            # Replace the port in the URL
            netloc_parts = parsed.netloc.split(':')
            if len(netloc_parts) > 1:
                # Has explicit port
                new_netloc = f"{netloc_parts[0]}:{assigned_port}"
            else:
                # No port specified, add it
                new_netloc = f"{parsed.netloc}:{assigned_port}"

            self.assigned_url = urlunparse((
                parsed.scheme,
                new_netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))

            print(f"[{_log_timestamp()}] [SDK] Assigned URL: {self.assigned_url}")
            print(f"[{_log_timestamp()}] [SDK] Disconnecting from registration port...")

            # Close current connection and reconnect to assigned port
            self.registered = True
            self.switching_ports = True
            self.connected = False
            if self.ws:
                self.ws.close()
                # Relay starts dedicated server instantly, no wait needed

    def handle_command(self, msg: Dict[str, Any]):
        """
        Handle command execution request by calling the command handler

        First checks if this is a response to a pending pull request.
        If not, passes to command handler (for backward compatibility).
        """
        try:
            # Log all incoming COMMAND messages
            msg_id = msg.get("id")
            print(f"[{_log_timestamp()}] [SDK] Received COMMAND message: id={msg_id}")

            # Check if this is a response to a pending command request (pull-based)
            # The relay sets the COMMAND message ID to match our GET_COMMANDS request ID
            print(f"[{_log_timestamp()}] [SDK] Checking if message ID {msg_id} is a pending request")

            if msg_id in self.pending_command_requests:
                # This is a response to a synchronous request_commands() call
                print(f"[{_log_timestamp()}] [SDK] This is a response to our GET_COMMANDS request")
                print(f"[{_log_timestamp()}] [SDK] Received command response for request: {msg_id}")

                # Check if it's a "no commands" response
                payload = msg.get("payload", {})
                if payload.get("no_command"):
                    print(f"[{_log_timestamp()}] [SDK] Relay says no commands available")
                    self.command_responses[msg_id] = None
                else:
                    print(f"[{_log_timestamp()}] [SDK] Relay returned command: {payload.get('command_id')}")
                    self.command_responses[msg_id] = payload

                # Signal the waiting thread
                self.pending_command_requests[msg_id].set()
                return

            # If no original_message_id or not a pending request, treat as unsolicited
            # This shouldn't happen in pure pull-based mode, but handle for backward compatibility
            print(f"[{_log_timestamp()}] [SDK] Warning: Received unsolicited COMMAND message (not pull-based): {msg.get('id')}")

            # Call the command handler provided by the agent
            self.command_handler(msg)

        except Exception as e:
            print(f"[{_log_timestamp()}] [SDK] Error in command handler: {e}")
            # Send error result
            payload = msg.get("payload", {})
            error_command_id = payload.get("command_id", msg.get("id"))
            error_result = {
                "stdout": "",
                "stderr": str(e),
                "exit_code": 1,
                "duration": 0,
                "error": str(e)
            }
            self.send_result(error_command_id, error_result)

    def send_message(self, message: Dict[str, Any]):
        """Send a message to Relay"""
        if self.ws and self.connected:
            try:
                self.ws.send(json.dumps(message))
            except Exception as e:
                print(f"[{_log_timestamp()}] [SDK] Failed to send message: {e}")

    def send_result(self, command_id: str, result: Dict[str, Any]):
        """Send command execution result to Relay (relay will lookup agent from command_id)"""
        result["command_id"] = command_id

        message = {
            "id": str(uuid.uuid4()),
            "type": "RESULT",
            "relay_id": "",
            "agent_id": self.slot_id,
            "payload": result,
            "timestamp": datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        }

        self.send_message(message)
        print(f"[{_log_timestamp()}] [SDK] Result sent: command_id={command_id}, exit_code={result.get('exit_code', 'N/A')}")

    def send_heartbeat(self):
        """Send heartbeat to Relay"""
        payload = {
            "agent_id": self.slot_id,
            "hostname": socket.gethostname(),
            "uptime_seconds": 0,
            "cpu_percent": 0,
            "memory_mb": 0,
            "disk_free_gb": 0
        }

        message = {
            "id": str(uuid.uuid4()),
            "type": "SLOT_HEARTBEAT",
            "relay_id": "",
            "agent_id": self.slot_id,
            "payload": payload,
            "timestamp": datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        }

        self.send_message(message)
        self.last_heartbeat = time.time()

    def send_status_update(self, command_id: str, status: str):
        """Send command status update to Relay"""
        payload = {
            "command_id": command_id,
            "agent_id": self.slot_id,
            "status": status
        }

        message = {
            "id": str(uuid.uuid4()),
            "type": "COMMAND_STATUS_UPDATE",
            "relay_id": "",
            "agent_id": self.slot_id,
            "payload": payload,
            "timestamp": datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        }

        self.send_message(message)
        print(f"[{_log_timestamp()}] [SDK] Status update sent: command_id={command_id}, status={status}")

    def send_agent_registration(self, description: str = None, hostname: str = None, os_name: str = None, arch: str = None, domain: str = None, version: str = "1.0.0", timeout: int = 10):
        """Send individual agent registration to Relay (will be forwarded to Core)

        All fields are optional except slot_id and version.
        Core will assign an auto-increment agent_id and send back an ACK.

        Returns:
            int: Assigned agent_id on success
            dict: {"error": "message"} on failure
            None: On timeout
        """
        import threading

        payload = {
            "slot_id": self.slot_id,  # Slot ID (this server.py instance)
            "version": version
        }

        # Add optional fields only if provided
        if description:
            payload["description"] = description
        if hostname:
            payload["hostname"] = hostname
        if os_name:
            payload["os"] = os_name
        if arch:
            payload["arch"] = arch
        if domain:
            payload["domain"] = domain

        message_id = str(uuid.uuid4())
        message = {
            "id": message_id,
            "type": "AGENT_REGISTER",
            "relay_id": "",
            "agent_id": self.slot_id,
            "payload": payload,
            "timestamp": datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        }

        # Create event for waiting
        event = threading.Event()
        self.pending_agent_registrations[message_id] = event

        # Send message
        self.send_message(message)
        print(f"[{_log_timestamp()}] [SDK] Agent registration sent: message_id={message_id}, slot_id={self.slot_id}, description={description or 'none'}")

        # Wait for ACK response
        if event.wait(timeout=timeout):
            # Got response
            response = self.agent_registration_responses.pop(message_id, None)
            self.pending_agent_registrations.pop(message_id, None)

            if isinstance(response, int):
                print(f"[{_log_timestamp()}] [SDK] Agent registration completed: agent_id={response}")
                return response
            elif isinstance(response, dict) and "error" in response:
                print(f"[{_log_timestamp()}] [SDK] Agent registration error: {response['error']}")
                return response
            else:
                print(f"[{_log_timestamp()}] [SDK] Unexpected response: {response}")
                return {"error": "Unexpected response format"}
        else:
            # Timeout
            self.pending_agent_registrations.pop(message_id, None)
            print(f"[{_log_timestamp()}] [SDK] Agent registration timeout after {timeout}s")
            return None

    def request_commands(self, agent_id: int, count: int = 1, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """Request pending commands from Relay for a specific agent (pull-based, synchronous)

        Args:
            agent_id: The agent ID to request commands for
            count: Number of commands to request (default: 1)
            timeout: Timeout in seconds to wait for response (default: 5)

        Returns:
            Dict with command data if available, None if no commands or timeout
        """
        import threading

        print(f"[{_log_timestamp()}] [SDK] Requesting {count} commands for agent {agent_id}, timeout={timeout}s")

        payload = {
            "agent_id": agent_id,
            "count": count
        }

        message_id = str(uuid.uuid4())
        message = {
            "id": message_id,
            "type": "GET_COMMANDS",
            "relay_id": "",
            "agent_id": str(agent_id),
            "payload": payload,
            "timestamp": datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        }

        # Create event for waiting
        event = threading.Event()
        self.pending_command_requests[message_id] = event

        # Send message
        self.send_message(message)
        print(f"[{_log_timestamp()}] [SDK] GET_COMMANDS sent: message_id={message_id}, agent_id={agent_id}, count={count}")

        # Wait for response
        print(f"[{_log_timestamp()}] [SDK] Waiting for relay response...")
        if event.wait(timeout=timeout):
            # Got response
            response = self.command_responses.pop(message_id, None)
            self.pending_command_requests.pop(message_id, None)

            print(f"[{_log_timestamp()}] [SDK] Got response: {response}")

            if response is None:
                print(f"[{_log_timestamp()}] [SDK] No commands available for agent {agent_id}")
                return None
            else:
                print(f"[{_log_timestamp()}] [SDK] Command received for agent {agent_id}: {response.get('command_id')}")
                return response
        else:
            # Timeout
            self.pending_command_requests.pop(message_id, None)
            print(f"[{_log_timestamp()}] [SDK] Timeout waiting for relay response after {timeout}s")
            return None

    def heartbeat_loop(self):
        """Send periodic heartbeats (only when registered on dedicated port)"""
        while self.should_run:
            if self.registered and self.connected and (time.time() - self.last_heartbeat) >= self.heartbeat_interval:
                self.send_heartbeat()
            time.sleep(1)

    def command_poll_loop(self):
        """Poll for pending commands (pull-based)"""
        while self.should_run:
            if self.registered and self.connected and (time.time() - self.last_command_poll) >= self.command_poll_interval:
                self.request_commands()
            time.sleep(1)

    def run(self):
        """Run the SDK with automatic reconnection"""
        import threading

        # Start heartbeat thread
        heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        heartbeat_thread.start()

        # Don't start automatic command polling thread - commands are requested on-demand when agents poll

        reconnect_delay = 1
        max_reconnect_delay = 300  # 5 minutes

        while self.should_run:
            try:
                self.connect()
                self.ws.run_forever()

                # Connection lost, attempt reconnection
                if self.should_run:
                    print(f"[{_log_timestamp()}] [SDK] Reconnecting in {reconnect_delay} seconds...")
                    time.sleep(reconnect_delay)

                    # Exponential backoff (but faster for registration)
                    if self.registered:
                        reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
                    else:
                        # Faster retry for registration
                        reconnect_delay = 1

            except KeyboardInterrupt:
                print(f"\n[{_log_timestamp()}] [SDK] Shutting down SDK...")
                self.should_run = False
                break
            except Exception as e:
                print(f"[{_log_timestamp()}] [SDK] SDK error: {e}")
                if self.should_run:
                    print(f"[{_log_timestamp()}] [SDK] Reconnecting in {reconnect_delay} seconds...")
                    time.sleep(reconnect_delay)

                    # Exponential backoff (but faster for registration)
                    if self.registered:
                        reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
                    else:
                        reconnect_delay = 1

    def stop(self):
        """Stop the SDK and close connections"""
        self.should_run = False
        if self.ws:
            self.ws.close()