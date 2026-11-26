# Proyectos: puentes MCP para Claude Code

Cada programa tiene su propia carpeta, con su código, su instalación y su README.

| Carpeta | Programa | Estado |
|---|---|---|
| [`civil3d/`](civil3d/README.md) | Autodesk Civil 3D 2026 + Subassembly Composer | Código escrito; falta compilar y probar en Windows |

Para añadir un MCP nuevo, crea `nombre-del-programa/` con la misma estructura (add-in o cliente, `mcp/`, `tests/` y `README.md`).
Así la instalación y los tests de un programa no dependen de los demás.
Cada servidor se registra en Claude Code con su propio nombre (por ejemplo, `civil-agent`).
