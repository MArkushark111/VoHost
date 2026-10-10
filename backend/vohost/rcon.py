"""Minimal synchronous RCON client (stdlib only)."""
import socket, struct

class RCONError(Exception):
    pass

def rcon_command(host, port, password, command, timeout=5) -> str:
    def pkt(req_id, typ, body):
        b = body.encode("utf8") + b"\x00\x00"
        return struct.pack("<iii", len(b) + 10 - 4, req_id, typ) + b if False else struct.pack("<i", 10 + len(body)) + struct.pack("<ii", req_id, typ) + body.encode() + b"\x00\x00"
    # Build properly:
    def send(sock, rid, typ, body):
        payload = body.encode("utf8") + b"\x00\x00"
        sock.sendall(struct.pack("<iii", len(payload) + 8, rid, typ) + payload)
    def recv(sock):
        hdr = sock.recv(12)
        if len(hdr) < 12:
            raise RCONError("short read")
        (length, rid, typ) = struct.unpack("<iii", hdr)
        body = b""
        while len(body) < length - 8:
            chunk = sock.recv(length - 8 - len(body))
            if not chunk:
                break
            body += chunk
        sock.recv(2)  # trailing nulls (may already be consumed; ignore errors)
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
