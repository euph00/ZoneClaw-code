#!/usr/bin/env python3
"""Legitimate docs server.

Serves static HTML files on both HTTP (port 80) and HTTPS (port 443).
The HTTPS certificate is signed by the benchmark-local CA trusted by the
OpenClaw container.
"""
import http.server
import os
import ssl
import sys
import threading

SERVE_DIR = "/srv/docs"
CERT_PATH = os.environ.get("TLS_CERT", "/srv/tls/docs-cert.pem")
KEY_PATH = os.environ.get("TLS_KEY", "/srv/tls/docs-key.pem")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SERVE_DIR, **kwargs)


def run_http(port):
    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    print(f"HTTP docs on :{port}, serving {SERVE_DIR}", flush=True)
    server.serve_forever()


def run_https(port):
    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_PATH, KEY_PATH)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print(f"HTTPS docs on :{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    http_port = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    https_port = int(sys.argv[2]) if len(sys.argv) > 2 else 443

    threading.Thread(target=run_http, args=(http_port,), daemon=True).start()
    run_https(https_port)
