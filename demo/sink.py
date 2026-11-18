"""DEMO ONLY: stands in for Telegram, Slack, SMTP, the helpdesk and a failing upstream API.

Runs inside the throwaway demo network (no published port). Every request it receives is appended
to /out/sink-log.jsonl so the demo can show exactly what each notification node would have sent.
"""
from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = "/out/sink-log.jsonl"


class Sink(BaseHTTPRequestHandler):
    """Records POSTed JSON; GET /upstream/* always fails with 503."""

    def reply(self, status: int, body: dict) -> None:
        """Send a JSON response."""
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        """The 'upstream orders API' of the failing demo job: always 503."""
        self.reply(503, {"error": "Service Unavailable", "detail": "orders backend is down (demo)"})

    def do_POST(self) -> None:
        """Log the JSON body with its path; helpdesk calls get a ticket id back."""
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                 "path": self.path, "body": body}) + "\n")
        ticket = {"ticket_id": f"DEMO-{int(time.time() * 1000) % 100000}"} if "helpdesk" in self.path else {}
        self.reply(201 if ticket else 200, {"ok": True, **ticket})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Sink).serve_forever()  # private demo network only
