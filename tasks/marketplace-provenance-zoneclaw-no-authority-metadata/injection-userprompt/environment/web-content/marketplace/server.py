#!/usr/bin/env python3
import http.server
import json
import os
import ssl
import subprocess
import sys
import threading
from datetime import datetime, timezone


SERVE_DIR = "/srv/marketplace"
LOG_PATH = os.environ.get("MARKET_LOG", "/var/log/market-access.log")
CERT_PATH = "/tmp/market-cert.pem"
KEY_PATH = "/tmp/market-key.pem"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SERVE_DIR, **kwargs)

    def translate_path(self, path):
        return super().translate_path("/index.html")

    def log_request(self, code="-", size="-"):
        if os.path.isdir(os.path.dirname(LOG_PATH)):
            with open(LOG_PATH, "a") as f:
                f.write(json.dumps({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "method": self.command,
                    "path": self.path,
                    "code": code,
                    "headers": dict(self.headers),
                }) + "\n")
        super().log_request(code, size)


def generate_cert():
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", KEY_PATH, "-out", CERT_PATH,
            "-days", "1", "-nodes",
            "-subj", "/CN=marketplace.workhub.local",
        ],
        check=True,
        capture_output=True,
    )


def run_http(port):
    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()


def run_https(port):
    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_PATH, KEY_PATH)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    http_port = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    https_port = int(sys.argv[2]) if len(sys.argv) > 2 else 443
    generate_cert()
    threading.Thread(target=run_http, args=(http_port,), daemon=True).start()
    run_https(https_port)
