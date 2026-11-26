"""Simulador del add-in Civil3DAgent para probar el servidor MCP sin Civil 3D."""
import json, os, socket, threading

def serve(root, token="t0k3n"):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(5)
    port = s.getsockname()[1]
    os.makedirs(os.path.join(root, "Civil3DAgent"), exist_ok=True)
    json.dump({"port": port, "token": token, "pid": 1}, open(os.path.join(root, "Civil3DAgent", "session.json"), "w"))
    calls = []
    def handle(c):
        with c:
            buf = b""
            while not buf.endswith(b"\n"):
                d = c.recv(65536)
                if not d: return
                buf += d
            req = json.loads(buf)
            calls.append(req)
            if req.get("token") != token:
                r = {"ok": False, "code": "unauthorized", "error": "Token inválido"}
            elif req["op"] == "query" and "ERRCOMP" in req["code"]:
                r = {"ok": False, "code": "compile_error", "mode": "query", "error": "Error de compilación",
                     "diagnostics": [{"severity": "error", "id": "CS0103", "line": 2, "column": 5, "message": "No existe x"}]}
            elif req["op"] in ("query", "modify"):
                r = {"ok": True, "mode": req["op"], "committed": req["op"] == "modify", "elapsed_ms": 3,
                     "result": {"echo_len": len(req["code"])}, "console": "hola\n", "audit_file": "C:/runs/x.json"}
            elif req["op"] == "lookup":
                r = {"ok": True, "query": req["query"], "count": 1, "truncated": False,
                     "types": [{"type": "Autodesk.Civil.DatabaseServices.Alignment", "kind": "class", "assembly": "AeccDbMgd",
                                "base": "Autodesk.Civil.DatabaseServices.Feature", "members": ["method ObjectIdCollection GetProfileIds()"]}]}
            elif req["op"] == "capture":
                r = {"ok": True, "method": "preview", "width": 1, "height": 1, "file": "C:/x.png", "png_base64": "iVBORw0KGgo=", "document": "a.dwg"}
            else:
                r = {"ok": True, "pong": True}
            c.sendall((json.dumps(r) + "\n").encode())
    def loop():
        while True:
            try: c, _ = s.accept()
            except OSError: return
            threading.Thread(target=handle, args=(c,), daemon=True).start()
    threading.Thread(target=loop, daemon=True).start()
    return s, calls
