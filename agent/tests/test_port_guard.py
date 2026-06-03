"""Tests for the server port-conflict guard (agent/port_guard.py).

Pure stdlib — no app import, no model — so these run anywhere, including CI.
"""
import http.server
import json
import socket
import sys
import threading
import time
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import port_guard  # noqa: E402

HOST = "127.0.0.1"


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((HOST, 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _listener(port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, port))
    s.listen(1)
    return s


def test_free_port_is_available_and_starts():
    port = _free_port()
    assert port_guard.is_port_available(HOST, port) is True
    decision = port_guard.resolve_serve_port(HOST, port)
    assert decision["action"] == "start"
    assert decision["port"] == port


def test_busy_port_is_not_available():
    port = _free_port()
    sock = _listener(port)
    try:
        assert port_guard.is_port_available(HOST, port) is False
    finally:
        sock.close()


def test_foreign_process_relocates_to_free_port():
    port = _free_port()
    sock = _listener(port)
    try:
        decision = port_guard.resolve_serve_port(HOST, port)
        assert decision["action"] == "relocated"
        assert decision["port"] != port
        assert port_guard.is_port_available(HOST, decision["port"]) is True
    finally:
        sock.close()


def test_invalid_port_not_available():
    assert port_guard.is_port_available(HOST, 0) is False
    assert port_guard.is_port_available(HOST, 70000) is False


def test_probe_layla_false_on_plain_listener():
    port = _free_port()
    sock = _listener(port)
    try:
        # A raw TCP listener that never answers HTTP must not look like Layla.
        assert port_guard.probe_layla(HOST, port, timeout=0.5) is False
    finally:
        sock.close()


def test_probe_layla_true_on_health_signature():
    port = _free_port()

    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({
                "status": "ok",
                "tools_registered": 195,
                "study_plans": 2,
                "vector_store": "enabled",
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    httpd = http.server.HTTPServer((HOST, port), _H)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        time.sleep(0.1)
        assert port_guard.probe_layla(HOST, port, timeout=1.5) is True
        decision = port_guard.resolve_serve_port(HOST, port)
        assert decision["action"] == "already_running"
        assert decision["port"] == port
    finally:
        httpd.shutdown()


def test_probe_layla_false_on_non_layla_http():
    port = _free_port()

    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"hello": "world"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    httpd = http.server.HTTPServer((HOST, port), _H)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        time.sleep(0.1)
        assert port_guard.probe_layla(HOST, port, timeout=1.0) is False
    finally:
        httpd.shutdown()
