"""Minimal synchronous RCON client (stdlib only)."""
import socket, struct

class RCONError(Exception):
    pass

def rcon_command(host, port, password, command, timeout=5) -> str:
    def send(sock, rid, typ, body):
        payload = body.encode("utf8") + b"\x00\x00"
        sock.sendall(struct.pack("<iii", len(payload) + 8, rid, typ) + payload)
    def read_body(sock, length):
        body = b""
        while len(body) < length - 8:
            chunk = sock.recv(length - 8 - len(body))
            if not chunk:
                break
            body += chunk
        return body
    def recv(sock):
        hdr = sock.recv(12)
        if len(hdr) < 12:
            raise RCONError("short read")
        (length, rid, typ) = struct.unpack("<iii", hdr)
        body = read_body(sock, length)
        sock.recv(2)  # trailing nulls
        # large responses are often split across several packets with the same request id;
        # drain them so the Console/list output isn't truncated
        if length >= 4096:
            try:
                sock.settimeout(0.4)
                while True:
                    try:
                        h2 = sock.recv(12)
                    except socket.timeout:
                        break
                    if len(h2) < 12:
                        break
                    (l2, r2, _t2) = struct.unpack("<iii", h2)
                    if r2 != rid:
                        break
                    body += read_body(sock, l2)
                    sock.recv(2)
            except Exception:
                pass
        return rid, typ, body[:-2].decode("utf8", "replace") if len(body) >= 2 else body.decode("utf8", "replace")
    s = socket.create_connection((host, port), timeout=timeout)
    try:
        s.settimeout(timeout)
        send(s, 1, 3, password)  # SERVERDATA_AUTH
        try:
            rid, typ, _ = recv(s)
        except Exception as e:
            raise RCONError(f"auth read failed: {e}")
        if rid == -1:
            raise RCONError("bad rcon password")
        send(s, 2, 2, command)  # SERVERDATA_EXECCOMMAND
        _, _, out = recv(s)
        return out
    finally:
        try:
            s.close()
        except Exception:
            pass
