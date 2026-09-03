"""Minimal in-process SMTP sink for tests. Speaks just enough SMTP
(EHLO, MAIL FROM, RCPT TO, DATA, RSET, NOOP, QUIT) to receive real messages
sent by smtplib through an actual TCP connection — proving the backend
really transmits mail to the configured host."""
import re
import socket
import threading


class SmtpSink:
    def __init__(self):
        self.inbox: list[dict] = []  # {mail_from, rcpt_tos, data}
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        try:
            socket.create_connection(("127.0.0.1", self.port), timeout=2).close()
        except OSError:
            pass
        self._thread.join(timeout=5)

    def _serve(self):
        self._sock.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket):
        mail_from, rcpts, in_data, buf = "", [], False, b""
        try:
            conn.sendall(b"220 industria-x-test ESMTP\r\n")
            f = conn.makefile("rb")
            while True:
                line = f.readline(4096)
                if not line:
                    break
                if in_data:
                    buf += line
                    if buf.endswith(b"\r\n.\r\n"):
                        self.inbox.append({"mail_from": mail_from,
                                           "rcpt_tos": list(rcpts),
                                           "data": buf[:-5].decode("utf-8", "replace")})
                        buf, in_data = b"", False
                        conn.sendall(b"250 OK: queued\r\n")
                    continue
                parts = line.decode("utf-8", "replace").strip().split(" ", 1)
                verb = parts[0].upper()
                arg = parts[1] if len(parts) > 1 else ""
                if verb in ("EHLO", "HELO"):
                    conn.sendall(b"250-Hello\r\n250 8BITMIME\r\n")
                elif verb == "MAIL":
                    m = re.search(r"FROM:\s*<([^>]*)>", arg, re.I)
                    mail_from = m.group(1) if m else arg
                    conn.sendall(b"250 OK\r\n")
                elif verb == "RCPT":
                    m = re.search(r"TO:\s*<([^>]*)>", arg, re.I)
                    rcpts.append(m.group(1) if m else arg)
                    conn.sendall(b"250 OK\r\n")
                elif verb == "DATA":
                    in_data = True
                    conn.sendall(b"354 End data with <CR><LF>.<CR><LF>\r\n")
                elif verb in ("RSET", "NOOP"):
                    conn.sendall(b"250 OK\r\n")
                elif verb == "QUIT":
                    conn.sendall(b"221 Bye\r\n")
                    break
                else:
                    conn.sendall(b"502 Command not implemented\r\n")
        except (OSError, ValueError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def last_to(self, email: str) -> dict | None:
        for m in reversed(self.inbox):
            if email in m["rcpt_tos"]:
                return m
        return None

    def codes_to(self, email: str) -> list[str]:
        m = self.last_to(email)
        if not m:
            return []
        return re.findall(r"(?m)^(\d{6})\r?$", m["data"])
