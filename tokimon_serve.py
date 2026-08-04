#!/usr/bin/env python3
"""Publish the companion's feed to other devices on the local network.

The pet's state only exists on this Mac — `~/.claude/digimon/state.json` is
written by the Stop hook — so a phone or watch has nothing to read. This is the
bridge: a small HTTP server on the LAN that hands out the same snapshot the menu
bar uses.

Local network rather than a cloud service, on purpose. Token spend is not
something to publish to a third party for a toy, and this needs no account, no
hosting and no API key. The cost is that it only works at home, which is the
right trade for a pet.

    python3 tokimon_serve.py                # serve on the LAN, print pairing info
    python3 tokimon_serve.py --port 9000
    python3 tokimon_serve.py --bind 127.0.0.1   # this machine only

Every data request needs a token. It is generated once into
~/.claude/digimon/serve_token (0600) and sent as an `X-Tokimon-Key` header —
a header rather than a query parameter so it stays out of URLs, proxy logs and
browser history. Without it, anyone on the same coffee-shop wifi could read how
much you spend.
"""
import argparse
import json
import os
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digimon_lib as dl
import tokimon_feed as feed

TOKEN_PATH = os.path.join(dl.DIGIMON_DIR, "serve_token")
DEFAULT_PORT = 8787
HEADER = "X-Tokimon-Key"

# Several devices (phone + watch) poll independently and neither needs
# sub-second freshness. One cached snapshot serves them all.
CACHE_TTL = 2.0


def load_or_create_token():
    """Read the shared token, creating it on first run. 0600 so it is not
    world-readable on a shared machine."""
    os.makedirs(dl.DIGIMON_DIR, exist_ok=True)
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH) as f:
            token = f.read().strip()
        if token:
            return token
    token = secrets.token_urlsafe(18)
    fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    return token


def lan_address():
    """This machine's address on the LAN. Opening a UDP socket to a public IP
    picks the interface the OS would actually route through, without sending
    anything; hostname lookups return 127.0.0.1 too often to be useful."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))   # TEST-NET-1, guaranteed unroutable
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class FeedCache:
    def __init__(self, ttl=CACHE_TTL):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._at = 0.0
        self._payload = None

    def get(self, now=None):
        now = time.time() if now is None else now
        with self._lock:
            if self._payload is None or now - self._at >= self.ttl:
                try:
                    self._payload = feed.build_feed()
                except Exception as exc:
                    dl.log_error("tokimon_serve.build_feed")
                    self._payload = {"ok": False, "error": str(exc)}
                self._at = now
            return self._payload


class Handler(BaseHTTPRequestHandler):
    server_version = "Tokimon/1.0"
    token = ""
    cache = None
    quiet = False

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self):
        supplied = self.headers.get(HEADER, "")
        # constant-time compare so the token can't be recovered by timing
        return bool(supplied) and secrets.compare_digest(supplied, self.token)

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        # /health carries no pet data, so it needs no token — it exists so a
        # client can find the server and show "paired, wrong key" rather than a
        # bare connection failure.
        if path in ("/health", "/"):
            self._send(200, {"ok": True, "service": "tokimon", "needs_token": True})
            return
        if path != "/feed":
            self._send(404, {"ok": False, "error": "not found"})
            return
        if not self._authorised():
            self._send(401, {"ok": False, "error": f"missing or bad {HEADER}"})
            return
        self._send(200, self.cache.get())

    def log_message(self, fmt, *args):
        if not self.quiet:
            sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))


def make_server(port, bind, token, quiet=False):
    handler = type("BoundHandler", (Handler,),
                   {"token": token, "cache": FeedCache(), "quiet": quiet})
    return ThreadingHTTPServer((bind, port), handler)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Serve the Tokimon feed on the LAN")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--bind", default="0.0.0.0",
                    help="interface to bind (default all; use 127.0.0.1 for this Mac only)")
    ap.add_argument("--quiet", action="store_true", help="don't log requests")
    args = ap.parse_args(argv)

    token = load_or_create_token()
    try:
        server = make_server(args.port, args.bind, token, args.quiet)
    except OSError as exc:
        raise SystemExit(f"could not bind {args.bind}:{args.port} — {exc}")

    host = lan_address() if args.bind == "0.0.0.0" else args.bind
    print("Tokimon feed server")
    print(f"  URL     http://{host}:{args.port}/feed")
    print(f"  Header  {HEADER}: {token}")
    print(f"  Token   {TOKEN_PATH}")
    print("  Ctrl-C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
