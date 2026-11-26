#!/usr/bin/env python3
"""Llama al puente Civil3DAgent desde la terminal.

  python civil_call.py ping
  python civil_call.py context
  python civil_call.py query  script.cs        (o "-" para leer de stdin)
  python civil_call.py query  -e "return civ.GetAlignmentIds().Count;"
  python civil_call.py modify script.cs --yes  (cambia el dibujo: pide --yes)
  python civil_call.py lookup Alignment.GetProfileIds
  python civil_call.py capture vista.png [--method preview|screen|auto]
  python civil_call.py refs                    (DLL usadas para compilar scripts)
Salida: JSON de la respuesta. Código de salida 0 si ok, 1 si error.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import civil_bridge_client as bridge  # noqa: E402


def _code(a) -> str:
    if a.e:
        return a.e
    if not a.file:
        sys.exit("Indica un archivo .cs, '-' o -e \"código\"")
    if a.file == "-":
        return sys.stdin.read()
    with open(a.file, "r", encoding="utf-8-sig") as f:
        return f.read()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Cliente de terminal del puente Civil3DAgent")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping")
    sub.add_parser("context")
    sub.add_parser("refs")
    for name in ("query", "modify"):
        q = sub.add_parser(name)
        q.add_argument("file", nargs="?")
        q.add_argument("-e", help="código C# en línea")
        q.add_argument("--timeout", type=int, default=120)
        q.add_argument("--label")
        if name == "modify":
            q.add_argument("--yes", action="store_true", help="confirmo que este script puede cambiar el dibujo")
    lk = sub.add_parser("lookup")
    lk.add_argument("query")
    lk.add_argument("--max", type=int, default=40)
    cp = sub.add_parser("capture")
    cp.add_argument("out", nargs="?", default="captura.png")
    cp.add_argument("--method", default="auto", choices=["auto", "preview", "screen"])
    cp.add_argument("--width", type=int, default=1600)
    cp.add_argument("--height", type=int, default=1000)
    a = p.parse_args()

    try:
        if a.cmd == "ping":
            r = bridge.call("ping", timeout=10)
        elif a.cmd == "refs":
            r = bridge.call("refs", timeout=60)
        elif a.cmd == "context":
            r = bridge.call("query", code=bridge.script("get_context.cs"), label="get_context (terminal)")
        elif a.cmd in ("query", "modify"):
            if a.cmd == "modify" and not a.yes:
                print("modify cambia el dibujo activo. Repite con --yes si estás seguro (y trabaja sobre una copia).", file=sys.stderr)
                return 2
            r = bridge.call(a.cmd, code=_code(a), label=a.label, timeout=a.timeout + 10, timeout_sec=a.timeout)
        elif a.cmd == "lookup":
            r = bridge.call("lookup", query=a.query, max=a.max, members=True, timeout=60)
        elif a.cmd == "capture":
            r = bridge.call("capture", width=a.width, height=a.height, method=a.method, timeout=90)
            if r.get("ok"):
                with open(a.out, "wb") as f:
                    f.write(base64.b64decode(r.pop("png_base64")))
                r["saved_to"] = os.path.abspath(a.out)
        else:
            return 2
    except bridge.BridgeError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=1))
        return 1
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
