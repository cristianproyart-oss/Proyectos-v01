# Puente MCP Claude Code ↔ Civil 3D 2026 + Subassembly Composer

Escrito sin acceso a Civil 3D: **nada de esto se ha compilado ni probado todavía en Windows**.
Las partes en Python (servidor MCP, cliente y herramienta de .pkt) sí tienen pruebas automáticas que pasan.
El C# se escribió contra la API documentada; abajo está la lista de firmas que hay que confirmar.

## Qué hay y dónde queda

| En el repo | Instalado en | Qué es |
|---|---|---|
| `addin/src/*.cs` | `%APPDATA%\Autodesk\ApplicationPlugins\Civil3DAgent.bundle\Contents\Civil3DAgent.dll` | Add-in: servidor TCP solo en 127.0.0.1 (8791–8799), token por sesión, compila C# con Roslyn y lo ejecuta en el documento activo |
| `addin/bundle/PackageContents.xml` | `...\Civil3DAgent.bundle\PackageContents.xml` | Carga automática al abrir Civil 3D (R25.1 = 2026) |
| `mcp/civil_agent_mcp.py` | `%LOCALAPPDATA%\Civil3DAgent\mcp\` | Servidor MCP `civil-agent` (stdio, sin dependencias) |
| `mcp/civil_call.py` | igual | Llamar al puente desde la terminal |
| `mcp/scripts/get_context.cs` | igual | Script de `get_context` (se puede corregir sin recompilar) |
| `sac/pkt_tool.py`, `sac/pktlib.py` | `%LOCALAPPDATA%\Civil3DAgent\sac\` | Lector/escritor de .pkt sin pérdida, explicar, copiar, validar |
| `sac/Validate-PktXaml.ps1` | igual | Carga el XAML con `UiPath.Workflow.dll` de Civil 3D |
| `sac/templates/validate_in_civil.cs` | igual | Importa el .pkt en Civil 3D, ejecuta `Run()` y lee Points/Links/Shapes |
| (lo genera el add-in) | `%LOCALAPPDATA%\Civil3DAgent\session.json` | Puerto + token de la sesión abierta |
| (lo genera el add-in) | `%LOCALAPPDATA%\Civil3DAgent\runs\` | Auditoría: cada script `.cs` y su resultado `.json`, y las capturas |

## Instalación (en tu PC, cuando quieras)

1. **Revisar el equipo** (solo lectura): `pwsh -File check_env.ps1`.
   Comprueba Civil 3D, el runtime .NET 8, el SDK (opcional), el Roslyn de AutoCAD, Python 3 y `claude`.
2. **Cerrar Civil 3D** y compilar e instalar:
   `pwsh -File build.ps1 -Install -RegisterMcp`
   - Compila con el Roslyn que trae PowerShell 7, contra el runtime .NET 8 y las DLL de AutoCAD/Civil. No hace falta el SDK.
   - `-RegisterMcp` ejecuta `claude mcp add --scope user civil-agent -- python ...\civil_agent_mcp.py`.
   - Otra versión: `-AcadDir "C:\Program Files\Autodesk\AutoCAD 2025" -Series R25.0`.
3. Abrir Civil 3D. En la línea de comandos debe aparecer `Civil3DAgent: puente MCP escuchando en 127.0.0.1:8791`.

**Para recompilar hay que cerrar Civil 3D**, porque la DLL queda bloqueada. `build.ps1 -Install` lo comprueba.

## Comprobar que el puente está vivo

- En Civil 3D: `C3DAGENT_STATUS`
- En la terminal:
  ```
  python %LOCALAPPDATA%\Civil3DAgent\mcp\civil_call.py ping
  python %LOCALAPPDATA%\Civil3DAgent\mcp\civil_call.py context
  python %LOCALAPPDATA%\Civil3DAgent\mcp\civil_call.py refs      (DLL usadas al compilar scripts)
  ```
- En Claude Code: `claude mcp list` debe mostrar `civil-agent`. Pide "usa get_context".
- Si algo falla: `%LOCALAPPDATA%\Civil3DAgent\agent.log`.

## Prueba final de la Parte 1

1. Con un dibujo tuyo abierto: `run_query` con `mcp/scripts/examples/listar_objetos.cs` (alineamientos, superficies, corredores) y luego `capture_view`.
2. `run_modify`: **solo en una copia** del DWG cuyo nombre contenga `_prueba`. Haz una copia ligera, sin láminas de planimetría y copiando también los `.grs` de las superficies. `examples/prueba_modify.cs` se niega a ejecutarse si el nombre del archivo no contiene `_prueba`.

## Cómo funcionan los scripts

El código es el **cuerpo de un método** con `doc`, `db`, `ed`, `civ` (CivilDocument) y `tr` (transacción ya abierta).
- `return` devuelve JSON (texto, números, listas, objetos anónimos). `Console.WriteLine` se devuelve como consola.
- **query** siempre aborta la transacción. **modify** hace commit (no llames tú a `tr.Commit()`).
- Helpers: `T(() => expr)` captura el error de un dato sin abortar; `Get(obj,"Prop")`, `Items(coll)` y `Props(obj)` usan reflexión.
- Las líneas iniciales `using X;` se mueven fuera del método. Para funciones auxiliares, usa funciones locales.
- Los errores de compilación traen línea y columna de tu script.

Límites conocidos:
- Un script con un bucle infinito congela Civil 3D: no se puede abortar código en el hilo principal.
- query deshace los cambios en la base de datos, pero no los efectos externos (guardar archivos, `SendStringToExecute`, etc.).
- Si hay un comando en curso o un cuadro de diálogo abierto, la petición se rechaza o caduca. Si caduca antes de empezar, **no** se ejecuta.

## Parte 2: Subassembly Composer (.pkt)

SAC no tiene API: se trabaja sobre archivos. Lo primero, con un .pkt tuyo real:
```
python pkt_tool.py info mi.pkt          (entradas del ZIP, XAML, prefijos asa1/asa2..., GUID)
python pkt_tool.py roundtrip mi.pkt     (abrir y guardar sin cambios debe dar los mismos bytes)
python pkt_tool.py explain mi.pkt       (parámetros, targets, puntos, enlaces, formas, decisiones, switches)
python pkt_tool.py inventory mi.pkt     (todos los elementos XAML: sirve para afinar explain al formato real)
```
- **Modificar**, siempre sobre una copia nueva: `copy mi.pkt --name NuevoNombre --new-guid --set-attr "APoint[@DisplayName=P1]" DeltaX "[Ancho*2]"`.
  Crea `mi_v2.pkt` y nunca sobrescribe el original. Si SAC está abierto, se niega: ciérralo antes, porque SAC sobrescribe el archivo al guardar.
- **Crear desde cero**: se parte de un .pkt tuyo como plantilla. `fragments` saca el texto XAML original de cada actividad (se conserva tal cual, con su prefijo) y `pack --template base.pkt --xaml nuevo.xaml` lo empaqueta. Si falta una medida, Claude debe preguntarte, no inventarla.
- **Validar**: `validate nuevo.pkt --xaml-load --civil --name Prueba --expected esperado.json`
  1. ZIP, CRC y XAML bien formado, y lectura/escritura sin pérdida.
  2. `ActivityXamlServices.Load` con `C3D\SACRuntime\UiPath.Workflow.dll`.
  3. En Civil 3D (modo query, el dibujo no cambia): `ImportSACSubassembly` + `Run()`, y se comparan Points (Offset/Elevation/Codes), Links y Shapes con lo esperado.
  4. Lo abres en SAC y confirmas que se ve bien.

`esperado.json`: `{"points":[{"codes":["ETW"],"offset":0.6,"elevation":-0.3}], "links":[{"codes":["Top"]}]}`

## Desinstalar

Cierra Civil 3D y ejecuta `pwsh -File uninstall.ps1` (con `-KeepRuns` conservas la auditoría).
Borra el bundle, `%LOCALAPPDATA%\Civil3DAgent` y el registro `civil-agent` de Claude Code.

## Seguridad

- Solo escucha en 127.0.0.1 y rechaza conexiones que no vengan de loopback.
- Token aleatorio de 256 bits por sesión, en `session.json` dentro de tu perfil. Se compara en tiempo constante.
- `run_modify` exige `confirmed=true` y su descripción dice a Claude que solo lo use tras tu confirmación.
- Todo lo que se ejecuta queda en `runs\`.

## Por confirmar en tu PC (no se pudo verificar sin Civil 3D)

Si algo de esto falla, el error de compilación dirá la línea. Se corrige con `lookup_api`:
- `Document.CapturePreviewImage(uint, uint)`: se llama por reflexión. Si no existe, se usa la captura de ventana.
- `get_context.cs`: `Alignment.SiteId`, `Profile.ProfileType`, `Surface.GetGeneralProperties()`, `Baseline.Name`, `BaselineRegion.AssemblyId`, `Corridor.CorridorSurfaces`, `UnitZoneSettings.CoordinateSystemCode`/`AngularUnits`. Es un script: se arregla sin recompilar.
- `validate_in_civil.cs`: el tipo de retorno de `SubassemblyCollection.ImportSACSubassembly(nombre, ruta, Point3d)` (se asume `ObjectId`), `Subassembly.Run()` y `ParamsDouble`/`Points`/`Links`/`Shapes` (estos se leen por reflexión).
- `PackageContents.xml`: `Platform="Civil3D"`. Si no carga, prueba `Platform="AutoCAD*"`.
- Estructura interna del .pkt: no conozco los nombres exactos de las entradas ni de los elementos de SAC. `explain` clasifica por nombre (Point/Link/Shape/Decision/Switch), y `inventory` muestra todo para afinarlo con tu archivo real.
- `build.ps1` usa el Roslyn de PowerShell 7 (`$PSHOME`). Si fallara, usa el de la carpeta de AutoCAD.

## Pruebas (sin Civil 3D)

`python -m unittest tests/test_all.py`: comprueba la lectura/escritura sin pérdida (también con descriptores de datos), la edición conservando comentarios y prefijos, el análisis, el cambio de nombre, la comparación y el protocolo MCP completo contra un simulador del add-in (`tests/fake_bridge.py`), incluido el rechazo de token y de `run_modify` sin confirmar.
El .pkt de las pruebas es **sintético** (`tests/make_sample.py`), no es un archivo real de SAC.
