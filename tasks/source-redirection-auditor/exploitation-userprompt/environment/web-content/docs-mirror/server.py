#!/usr/bin/env python3
"""Mirror docs server with request logging.

Serves static HTML files on both HTTP (port 80) and HTTPS (port 443) and logs
every request to a JSONL file for verification by the exploitation verifier.
The HTTPS certificate is signed by the benchmark-local CA trusted by the
OpenClaw container.

HTTPS is needed because agents often normalize http:// URLs to https://
when writing them to memory, so the mirror must accept both schemes.
"""
import http.server
import json
import os
import ssl
import sys
import threading
from datetime import datetime, timezone

LOG_PATH = os.environ.get("MIRROR_LOG", "/var/log/mirror-access.log")
SERVE_DIR = os.path.dirname(os.path.abspath(__file__))
CERT_PATH = os.environ.get("TLS_CERT", "/srv/tls/mirror-cert.pem")
KEY_PATH = os.environ.get("TLS_KEY", "/srv/tls/mirror-key.pem")


class LoggingHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SERVE_DIR, **kwargs)

    def log_request(self, code="-", size="-"):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "method": self.command,
            "path": self.path,
            "code": code,
            "headers": dict(self.headers),
        }
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
        super().log_request(code, size)


def run_http(port):
    server = http.server.HTTPServer(("0.0.0.0", port), LoggingHandler)
    print(f"HTTP mirror on :{port}, logging to {LOG_PATH}", flush=True)
    server.serve_forever()


def run_https(port):
    server = http.server.HTTPServer(("0.0.0.0", port), LoggingHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_PATH, KEY_PATH)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print(f"HTTPS mirror on :{port}, logging to {LOG_PATH}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    http_port = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    https_port = int(sys.argv[2]) if len(sys.argv) > 2 else 443

    # HTTP in a background thread, HTTPS on main thread
    threading.Thread(target=run_http, args=(http_port,), daemon=True).start()
    run_https(https_port)
