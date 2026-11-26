"""Cliente del puente Civil3DAgent (TCP 127.0.0.1 + token). Solo biblioteca estándar.

Lo usan civil_agent_mcp.py (servidor MCP) y civil_call.py (terminal).
"""
from __future__ import annotations

import glob
import json
import os
import socket

ROOT = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Civil3DAgent")
SESSION_FILE = os.environ.get("CIVIL3D_AGENT_SESSION", os.path.join(ROOT, "session.json"))
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "scripts")


class BridgeError(Exception):
    pass


def _load(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def sessions() -> list[dict]:
    """session.json primero; después session-<pid>.json (una por instancia de Civil 3D abierta)."""
    out, seen = [], set()
    for p in [SESSION_FILE] + sorted(glob.glob(os.path.join(ROOT, "session-*.json")), key=os.path.getmtime, reverse=True):
        s = _load(p)
        if s and s.get("port") and s.get("token") and (s["port"], s["token"]) not in seen:
            seen.add((s["port"], s["token"]))
            s["_file"] = p
            out.append(s)
    return out


def _send(sess: dict, payload: dict, timeout: float) -> dict:
    data = dict(payload)
    data["token"] = sess["token"]
    raw = (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")
    with socket.create_connection(("127.0.0.1", int(sess["port"])), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(raw)
        buf = bytearray()
        while True:
            chunk = s.recv(1 << 20)
            if not chunk:
                break
            buf.extend(chunk)
            if buf.endswith(b"\n"):
                break
    if not buf:
        raise BridgeError("El puente cerró la conexión sin responder.")
    return json.loads(buf.decode("utf-8"))


def call(op: str, timeout: float = 180.0, **kw) -> dict:
    """Envía una operación al add-in. Prueba cada sesión conocida hasta que una responda."""
    payload = {"op": op, **kw}
    payload.setdefault("timeout_sec", int(max(5, timeout - 5)))
    errors = []
    found = sessions()
    if not found:
        raise BridgeError(
            f"No encuentro {SESSION_FILE}. ¿Está Civil 3D abierto con el add-in Civil3DAgent cargado? "
            "En Civil 3D escribe C3DAGENT_STATUS; si no existe el comando, el bundle no se cargó.")
    for sess in found:
        try:
            resp = _send(sess, payload, timeout)
            if resp.get("code") == "unauthorized":
                errors.append(f"puerto {sess['port']}: token rechazado ({sess['_file']} es de una sesión antigua)")
                continue
            return resp
        except (OSError, ValueError) as e:
            errors.append(f"puerto {sess.get('port')}: {e}")
    raise BridgeError("No pude hablar con Civil 3D. " + "; ".join(errors))


def script(name: str) -> str:
    with open(os.path.join(SCRIPTS, name), "r", encoding="utf-8") as f:
        return f.read()
