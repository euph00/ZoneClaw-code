#!/usr/bin/env python3
"""Forum server that serves index.html for any request path.

Serves on both HTTP (port 80) and HTTPS (port 443). The HTTPS certificate is
signed by the benchmark-local forum CA trusted by the OpenClaw container.
HTTPS is needed because agents often normalize URLs to https://.
"""
import http.server
import os
import ssl
import sys
import threading

SERVE_DIR = "/srv/forum"
CERT_PATH = os.environ.get("TLS_CERT", "/srv/tls/community-devforum-cert.pem")
KEY_PATH = os.environ.get("TLS_KEY", "/srv/tls/community-devforum-key.pem")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SERVE_DIR, **kwargs)

    def translate_path(self, path):
        """Always serve index.html regardless of request path."""
        return super().translate_path("/")


def run_http(port):
    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    print(f"HTTP forum on :{port}, serving {SERVE_DIR}/index.html for all paths", flush=True)
    server.serve_forever()


def run_https(port):
    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_PATH, KEY_PATH)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print(f"HTTPS forum on :{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    http_port = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    https_port = int(sys.argv[2]) if len(sys.argv) > 2 else 443

    threading.Thread(target=run_http, args=(http_port,), daemon=True).start()
    run_https(https_port)
