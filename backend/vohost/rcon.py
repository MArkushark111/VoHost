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
        # NOTE: read_body already consumed the ENTIRE packet (body + 2 trailing
        # nulls). Do NOT read further here: vanilla sends exactly one packet per
        # request, so an extra recv() blocks until timeout ("auth read failed:
        # timed out") or eats the next packet's bytes.
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
            except Exception:
                pass
        return rid, typ, body[:-2].decode("utf8", "replace") if len(body) >= 2 else body.decode("utf8", "replace")
    try:
        s = socket.create_connection((host, port), timeout=timeout)
    except Exception as e:
        raise RCONError(f"connect {host}:{port} failed: {e}")
    try:
        s.settimeout(timeout)
        send(s, 1, 3, password)  # SERVERDATA_AUTH
        try:
            rid, typ, _ = recv(s)
        except Exception as e:
            raise RCONError(f"auth read failed ({host}:{port}): {e}")
        if rid == -1:
            raise RCONError(f"bad rcon password ({host}:{port})")
        send(s, 2, 2, command)  # SERVERDATA_EXECCOMMAND
        try:
            _, _, out = recv(s)
        except Exception as e:
            raise RCONError(f"command read failed ({host}:{port}): {e}")
        return out
    finally:
        try:
            s.close()
        except Exception:
            pass
