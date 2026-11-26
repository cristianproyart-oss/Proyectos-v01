#!/usr/bin/env python3
"""Servidor MCP "civil-agent" (stdio, JSON-RPC 2.0, sin dependencias externas).

Expone el add-in Civil3DAgent de Civil 3D a Claude Code:
  get_context, run_query, run_modify, lookup_api, capture_view
Registro (ámbito usuario):
  claude mcp add --scope user civil-agent -- python "%LOCALAPPDATA%\\Civil3DAgent\\mcp\\civil_agent_mcp.py"
"""
from __future__ import annotations

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import civil_bridge_client as bridge  # noqa: E402

SERVER_NAME = "civil-agent"
SERVER_VERSION = "1.0.0"
SUPPORTED_PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]
SAC_TOOL = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sac", "pkt_tool.py"))

INSTRUCTIONS = f"""Puente en vivo con Civil 3D (documento activo). Habla en español con el usuario.
Flujo de trabajo:
1. Empieza SIEMPRE con get_context para saber qué dibujo está abierto y qué contiene.
2. Ante cualquier duda sobre un tipo, propiedad o firma de la API de AutoCAD/Civil 3D, usa lookup_api antes de escribir código. No inventes la API.
3. Para leer o analizar usa run_query (la transacción se aborta siempre: el dibujo no cambia).
4. run_modify hace commit y CAMBIA el dibujo: úsalo solo después de explicar al usuario qué vas a cambiar y recibir su confirmación explícita. Prefiere trabajar sobre una copia del DWG, nunca sobre originales de proyecto.
Scripts C#: son el cuerpo de un método con doc, db, ed, civ (CivilDocument) y tr (Transaction ya abierta; no hagas Commit tú).
Devuelve datos simples con 'return' (texto, números, listas, objetos anónimos) y usa Console.WriteLine para trazas. Abre objetos con tr.GetObject(id, OpenMode.ForRead).
Helpers: T(() => expr) captura excepciones por dato; Props(obj) vuelca propiedades simples por reflexión.
Si un error de compilación indica una línea, corrige esa línea (cuentan desde 1 en tu script).
Si la API no permite algo, dilo claramente y propone alternativa (otro método, un comando de AutoCAD o un paso manual).
Subassembly Composer (.pkt): no hay API en vivo; usa la herramienta de archivos {SAC_TOOL} (explain, inventory, roundtrip, copy, validate). Modifica siempre una copia nueva (_v2.pkt) y pide al usuario que cierre el .pkt en SAC antes.
"""

TOOLS = [
    {
        "name": "get_context",
        "description": "Resumen del documento activo de Civil 3D: versión, archivo, unidades, sistema de coordenadas, "
                       "alineamientos (con perfiles), superficies, corredores, ensamblajes, subensamblajes y la selección actual. "
                       "Úsalo primero en cada tarea. No cambia el dibujo.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "title": "Contexto de Civil 3D"},
    },
    {
        "name": "run_query",
        "description": "Compila y ejecuta C# en el documento activo en modo QUERY: la transacción se aborta siempre, así que el dibujo "
                       "nunca cambia. El código es el cuerpo de un método con doc, db, ed, civ (CivilDocument) y tr (Transaction). "
                       "Devuelve el valor de 'return' como JSON, la salida de Console y los errores de compilación con número de línea.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Cuerpo C#. Puede empezar con líneas 'using X;'."},
                "label": {"type": "string", "description": "Descripción breve para el registro de auditoría."},
                "timeout_sec": {"type": "integer", "minimum": 5, "maximum": 3600, "default": 120},
            },
            "required": ["code"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "title": "Consulta C# (solo lectura)"},
    },
    {
        "name": "run_modify",
        "description": "Ejecuta C# en modo MODIFY: hace commit y CAMBIA el dibujo activo. Úsalo SOLO tras explicar el cambio al usuario "
                       "y recibir su confirmación explícita en la conversación; pon confirmed=true únicamente en ese caso. "
                       "Trabaja sobre una copia del DWG, nunca sobre originales. Mismas variables que run_query; no hagas tr.Commit() tú.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "confirmed": {"type": "boolean", "description": "true solo si el usuario confirmó este cambio concreto."},
                "summary": {"type": "string", "description": "Qué cambia, en una frase (queda en la auditoría)."},
                "timeout_sec": {"type": "integer", "minimum": 5, "maximum": 3600, "default": 300},
            },
            "required": ["code", "confirmed", "summary"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "title": "Modificar dibujo (requiere confirmación)"},
    },
    {
        "name": "lookup_api",
        "description": "Busca por reflexión tipos, miembros y firmas reales en las DLL de AutoCAD y Civil 3D cargadas. "
                       "Ejemplos: 'Subassembly', 'Alignment.GetProfileIds', 'SubassemblyCollection.Import', '.ImportSACSubassembly', "
                       "o un nombre completo 'Autodesk.Civil.DatabaseServices.Corridor'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max": {"type": "integer", "default": 40, "minimum": 1, "maximum": 500},
                "members": {"type": "boolean", "default": True, "description": "Incluir miembros cuando la búsqueda es concreta."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "title": "Buscar en la API"},
    },
    {
        "name": "capture_view",
        "description": "Captura PNG de la vista actual del dibujo activo. method: 'preview' (render de la vista), 'screen' "
                       "(copia de la ventana tal como se ve) o 'auto'. También se guarda en la carpeta runs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "width": {"type": "integer", "default": 1600},
                "height": {"type": "integer", "default": 1000},
                "method": {"type": "string", "enum": ["auto", "preview", "screen"], "default": "auto"},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "title": "Captura de la vista"},
    },
]


# ---------------------------------------------------------------- formato
def _fmt_run(resp: dict) -> tuple[str, bool]:
    ok = bool(resp.get("ok"))
    parts = []
    if ok:
        parts.append(f"OK ({resp.get('mode')}, {resp.get('elapsed_ms')} ms, commit={resp.get('committed')})")
    else:
        parts.append(f"ERROR [{resp.get('code')}]: {resp.get('error')}")
    diags = resp.get("diagnostics") or []
    errs = [d for d in diags if d.get("severity") == "error"]
    warns = [d for d in diags if d.get("severity") != "error"]
    if errs:
        parts.append("Errores de compilación:\n" + "\n".join(
            f"  línea {d.get('line')}, col {d.get('column')}: {d.get('id')} {d.get('message')}" for d in errs))
    if warns and not ok:
        parts.append("Avisos:\n" + "\n".join(f"  línea {d.get('line')}: {d.get('id')} {d.get('message')}" for d in warns[:20]))
    if resp.get("stack"):
        parts.append("Traza:\n" + resp["stack"])
    if "result" in resp and resp["result"] is not None:
        r = resp["result"]
        parts.append("Resultado:\n" + (r if isinstance(r, str) else json.dumps(r, ensure_ascii=False, indent=1)))
    if resp.get("console"):
        parts.append("Consola:\n" + resp["console"])
    if resp.get("audit_file"):
        parts.append(f"Auditoría: {resp['audit_file']}")
    return "\n\n".join(parts), not ok


def _text(t: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": t}], "isError": is_error}


# ---------------------------------------------------------------- herramientas
def tool_get_context(args: dict) -> dict:
    resp = bridge.call("query", code=bridge.script("get_context.cs"), label="get_context", timeout=120)
    if resp.get("ok"):
        r = resp.get("result")
        return _text(json.dumps(r, ensure_ascii=False, indent=1) if not isinstance(r, str) else r)
    txt, _ = _fmt_run(resp)
    return _text("get_context falló (el script está en mcp/scripts/get_context.cs; corrígelo con lookup_api si una firma "
                 "no existe en esta versión).\n\n" + txt, True)


def tool_run_query(args: dict) -> dict:
    t = int(args.get("timeout_sec") or 120)
    resp = bridge.call("query", code=args["code"], label=args.get("label"), timeout=t + 10, timeout_sec=t)
    return _text(*_fmt_run(resp))


def tool_run_modify(args: dict) -> dict:
    if args.get("confirmed") is not True:
        return _text("No ejecutado: run_modify exige confirmed=true, y solo después de que el usuario haya confirmado "
                     "este cambio concreto. Explícale qué vas a cambiar y pídele confirmación.", True)
    t = int(args.get("timeout_sec") or 300)
    resp = bridge.call("modify", code=args["code"], label="MODIFY: " + str(args.get("summary", "")), timeout=t + 10, timeout_sec=t)
    return _text(*_fmt_run(resp))


def tool_lookup_api(args: dict) -> dict:
    resp = bridge.call("lookup", query=args["query"], max=int(args.get("max") or 40),
                       members=bool(args.get("members", True)), timeout=60)
    if not resp.get("ok"):
        return _text("ERROR: " + str(resp.get("error")), True)
    lines = [f"{resp.get('count')} tipo(s) para '{resp.get('query')}'" + (" (recortado)" if resp.get("truncated") else "")]
    for t in resp.get("types", []):
        lines.append(f"\n{t['kind']} {t['type']}  [{t['assembly']}]" + (f" : {t['base']}" if t.get("base") else ""))
        for m in t.get("members", []):
            lines.append("    " + m)
    if resp.get("hint"):
        lines.append(resp["hint"])
    return _text("\n".join(lines))


def tool_capture_view(args: dict) -> dict:
    resp = bridge.call("capture", width=int(args.get("width") or 1600), height=int(args.get("height") or 1000),
                       method=args.get("method") or "auto", timeout=90)
    if not resp.get("ok"):
        return _text("ERROR: " + str(resp.get("error")), True)
    return {"content": [
        {"type": "image", "data": resp["png_base64"], "mimeType": "image/png"},
        {"type": "text", "text": f"Captura ({resp.get('method')}, {resp.get('width')}x{resp.get('height')}) de "
                                 f"{resp.get('document')}. Guardada en {resp.get('file')}"},
    ], "isError": False}


HANDLERS = {
    "get_context": tool_get_context,
    "run_query": tool_run_query,
    "run_modify": tool_run_modify,
    "lookup_api": tool_lookup_api,
    "capture_view": tool_capture_view,
}


# ---------------------------------------------------------------- JSON-RPC
def handle(msg: dict) -> dict | None:
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    is_notification = "id" not in msg

    def ok(result):
        return None if is_notification else {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, message):
        return None if is_notification else {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    if method == "initialize":
        req = params.get("protocolVersion")
        return ok({
            "protocolVersion": req if req in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        })
    if method in ("notifications/initialized", "notifications/cancelled", "initialized"):
        return None
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        h = HANDLERS.get(name)
        if not h:
            return err(-32602, f"Herramienta desconocida: {name}")
        try:
            return ok(h(args))
        except bridge.BridgeError as e:
            return ok(_text(str(e), True))
        except KeyError as e:
            return ok(_text(f"Falta el argumento {e}", True))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            return ok(_text(f"Error interno del servidor MCP: {type(e).__name__}: {e}", True))
    if method in ("resources/list",):
        return ok({"resources": []})
    if method in ("prompts/list",):
        return ok({"prompts": []})
    return err(-32601, f"Método no soportado: {method}")


def main() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw.decode("utf-8"))
        except ValueError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON inválido"}}
        else:
            if isinstance(msg, list):  # lotes (protocolo antiguo)
                outs = [o for o in (handle(m) for m in msg) if o is not None]
                out = outs or None
            else:
                out = handle(msg)
        if out is not None:
            stdout.write((json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8"))
            stdout.flush()


if __name__ == "__main__":
    main()
