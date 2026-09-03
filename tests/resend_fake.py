"""In-process fake Resend API for tests. Implements just POST /emails over
real HTTP: records the request (headers + JSON body), returns {"id": ...}
on success. Failure modes (HTTP status / network error) are configurable
per-test — proving the backend handles Resend errors without leaking the
OTP or marking anything verified."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    server_ref = None

    def log_message(self, *args):
        pass

    def do_POST(self):
        srv = self.server_ref
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            body = {}
        srv.requests.append({"path": self.path,
                             "auth": self.headers.get("Authorization", ""),
                             "content_type": self.headers.get("Content-Type", ""),
                             "body": body})
        if srv.fail_with is not None:
            status, payload = srv.fail_with
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        data = json.dumps({"id": f"test_{len(srv.requests)}"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FakeResend:
    def __init__(self):
        _Handler.server_ref = self
        self.requests: list[dict] = []
        self.fail_with: tuple[int, dict] | None = None
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self._srv.server_address[1]
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._srv.shutdown()

    def last_to(self, email: str) -> dict | None:
        for r in reversed(self.requests):
            to = r["body"].get("to", [])
            if email in (to if isinstance(to, list) else [to]):
                return r
        return None

    def codes_to(self, email: str) -> list[str]:
        import re
        r = self.last_to(email)
        if not r:
            return []
        text = str(r["body"].get("text", "")) + "\n" + str(r["body"].get("html", ""))
        return re.findall(r"(?m)^(\d{6})\r?$", text) or re.findall(r">(\d{6})<", text)
