#!/usr/bin/env python3
"""
ExpApp HTTP Server for Hermes

Minimal HTTP server that accepts ExpApp requests and executes Hermes agent tasks.
Bypasses the complex hermes_cli.gateway to avoid Python 3.9 compatibility issues.

Architecture:
ExpApp → HTTP POST → /api/chat → This server → Hermes Agent → Response
"""

import json
import os
import sys
import asyncio
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Dict, Any, Optional
from pathlib import Path

# Add Hermes to Python path
HERMES_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(HERMES_ROOT))

# Simple in-memory session storage
ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}

class ExpAppHTTPRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler for ExpApp → Hermes communication"""

    def log_message(self, format: str, *args):
        """Log messages with [ExpApp-Hermes] prefix"""
        print(f"[ExpApp-Hermes] {format.format(*args)}")

    def do_GET(self):
        """Handle GET requests"""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            self.send_health_check()
        elif path == "/stats":
            self.send_stats()
        elif path == "/sessions":
            self.send_sessions()
        else:
            self.send_404()

    def do_POST(self):
        """Handle POST requests"""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/chat":
            self.handle_chat()
        elif path == "/api/start":
            self.handle_start_session()
        elif path == "/api/stop":
            self.handle_stop_session()
        else:
            self.send_404()

    def send_health_check(self):
        """Health check endpoint"""
        self.send_json_response(200, "application/json", json.dumps({
            "status": "healthy",
            "service": "expapp-hermes-server",
            "active_sessions": len(ACTIVE_SESSIONS),
            "version": "1.0.0"
        }).encode())

    def send_stats(self):
        """Stats endpoint"""
        self.send_json_response(200, "application/json", json.dumps({
            "active_sessions": len(ACTIVE_SESSIONS),
            "sessions": {sid: info.get("user_id") for sid, info in ACTIVE_SESSIONS.items()}
        }).encode())

    def send_sessions(self):
        """List all active sessions"""
        self.send_json_response(200, "application/json", json.dumps({
            "sessions": [
                {
                    "session_id": sid,
                    "user_id": info.get("user_id"),
                    "created_at": info.get("created_at"),
                    "last_activity": info.get("last_activity"),
                    "status": "running"
                }
                for sid, info in ACTIVE_SESSIONS.items()
            ]
        }).encode())

    def handle_chat(self):
        """Handle chat requests from ExpApp"""
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            request = json.loads(post_data.decode("utf-8"))
            session_id = request.get("session_id")
            user_id = request.get("user_id")
            messages = request.get("messages", [])

            if not session_id or not user_id:
                self.send_error(400, "Missing session_id or user_id")
                return

            self.log_message("Chat request: session=%s user=%s", session_id, user_id)

            # Store/update session
            if session_id not in ACTIVE_SESSIONS:
                ACTIVE_SESSIONS[session_id] = {
                    "user_id": user_id,
                    "messages": [],
                    "created_at": int(os.times()[4] * 1000),
                    "last_activity": int(os.times()[4] * 1000),
                    "status": "running"
                }
                self.log_message("New session created: %s", session_id)

            # Update session
            ACTIVE_SESSIONS[session_id]["messages"].extend(messages)
            ACTIVE_SESSIONS[session_id]["last_activity"] = int(os.times()[4] * 1000)

            # Simulate Hermes processing
            response = self.simulate_hermes_agent(request)

            self.send_json_response(200, "application/json", json.dumps(response).encode())

        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
        except Exception as e:
            self.log_message("Error handling chat: %s", str(e))
            self.send_error(500, f"Server error: {str(e)}")

    def handle_start_session(self):
        """Start a new Hermes session"""
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            request = json.loads(post_data.decode("utf-8"))
            session_id = request.get("session_id")
            user_id = request.get("user_id")

            if not session_id or not user_id:
                self.send_error(400, "Missing session_id or user_id")
                return

            self.log_message("Start session: session=%s user=%s", session_id, user_id)

            # Create new session
            ACTIVE_SESSIONS[session_id] = {
                "user_id": user_id,
                "messages": [],
                "created_at": int(os.times()[4] * 1000),
                "last_activity": int(os.times()[4] * 1000),
                "status": "running",
                "hermes_process": None  # Will store Hermes process if needed
            }

            self.send_json_response(200, "application/json", json.dumps({
                "session_id": session_id,
                "status": "started",
                "message": "Hermes session started"
            }).encode())

        except Exception as e:
            self.log_message("Error starting session: %s", str(e))
            self.send_error(500, f"Failed to start session: {str(e)}")

    def handle_stop_session(self):
        """Stop an active Hermes session"""
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            request = json.loads(post_data.decode("utf-8"))
            session_id = request.get("session_id")

            if not session_id:
                self.send_error(400, "Missing session_id")
                return

            if session_id not in ACTIVE_SESSIONS:
                self.send_error(404, "Session not found")
                return

            self.log_message("Stop session: %s", session_id)

            # Stop Hermes process if running
            session = ACTIVE_SESSIONS[session_id]
            hermes_process = session.get("hermes_process")
            if hermes_process:
                try:
                    hermes_process.terminate()
                    hermes_process.wait(timeout=5)
                except:
                    hermes_process.kill()

            # Remove session
            del ACTIVE_SESSIONS[session_id]

            self.send_json_response(200, "application/json", json.dumps({
                "session_id": session_id,
                "status": "stopped",
                "message": "Hermes session stopped"
            }).encode())

        except Exception as e:
            self.log_message("Error stopping session: %s", str(e))
            self.send_error(500, f"Failed to stop session: {str(e)}")

    def simulate_hermes_agent(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate Hermes agent response for Phase 1 testing"""
        session_id = request["session_id"]
        user_message = request["messages"][0]["content"] if request["messages"] else ""

        self.log_message("Processing message for session %s: %s", session_id, user_message[:50] + "...")

        # Simulate agent thinking
        response_text = f"[Hermes Test] I received your message through ExpApp: '{user_message[:100]}...'\n\nIn production, I would:\n1. Acknowledge your request\n2. Use browser tools to navigate\n3. Take screenshots and analyze\n4. Report findings with updates\n\nThis confirms ExpApp → Hermes routing is WORKING! 🎉"

        return {
            "session_id": session_id,
            "messages": [
                {
                    "role": "assistant",
                    "content": response_text,
                    "timestamp": int(os.times()[4] * 1000)
                }
            ],
            "status": "completed",
            "metadata": {
                "model": "hermes-test",
                "tool_calls": 0,
                "processing_time_ms": 100
            }
        }

    def send_json_response(self, code: int, content_type: str, content: bytes):
        """Send HTTP response"""
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(content)

    def send_404(self):
        """Send 404 response"""
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def send_error(self, code: int, message: str):
        """Send error response"""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode())

def run_server(port: int = 9510, host: str = "localhost"):
    """Start the ExpApp-Hermes HTTP server"""
    server_address = (host, port)
    httpd = HTTPServer(server_address, ExpAppHTTPRequestHandler)

    print(f"[ExpApp-Hermes] Starting HTTP server on {host}:{port}")
    print(f"[ExpApp-Hermes] Test endpoints:")
    print(f"  - http://localhost:{port}/health")
    print(f"  - http://localhost:{port}/api/chat")
    print(f"  - http://localhost:{port}/stats")
    print(f"[ExpApp-Hermes] Press Ctrl+C to stop")
    print("")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n[ExpApp-Hermes] Shutting down server")
        httpd.server_close()

if __name__ == "__main__":
    # Simple command-line interface
    import argparse

    parser = argparse.ArgumentParser(description="ExpApp-Hermes HTTP Server")
    parser.add_argument("--port", type=int, default=9510, help="Port to listen on")
    parser.add_argument("--host", type=str, default="localhost", help="Host to bind to")

    args = parser.parse_args()

    run_server(port=args.port, host=args.host)
