#!/usr/bin/env python3
"""Herramienta de archivos .pkt de Subassembly Composer (sin dependencias).

  python pkt_tool.py info       mi.pkt            entradas del ZIP, XAML, prefijos, GUID
  python pkt_tool.py explain    mi.pkt [--json]   parámetros, targets, puntos, enlaces, formas, decisiones...
  python pkt_tool.py inventory  mi.pkt            elementos XAML y cuántas veces aparecen
  python pkt_tool.py roundtrip  mi.pkt            abre y guarda sin cambios en memoria y compara bytes
  python pkt_tool.py extract    mi.pkt carpeta    vuelca las entradas tal cual
  python pkt_tool.py fragments  mi.pkt [--kind point] [--name P1]   texto XAML original de actividades
  python pkt_tool.py copy       mi.pkt [--out mi_v2.pkt] [--name NuevoNombre] [--new-guid] [--guid OLD]
                                [--set-attr "APoint[@DisplayName=P1]" Atributo Valor] [--replace VIEJO NUEVO]
  python pkt_tool.py pack       --template base.pkt --xaml nuevo.xaml --out nuevo.pkt [--entry nombre.xaml]
  python pkt_tool.py validate   mi.pkt [--xaml-load] [--civil --name Nombre] [--expected esperado.json]
  python pkt_tool.py civil-script mi.pkt --name Nombre      script C# para run_query
  python pkt_tool.py compare    esperado.json real.json [--tol 0.001]

Reglas: nunca se sobrescribe el original; las modificaciones van a una copia nueva (_v2.pkt, _v3.pkt...).
No modifiques un .pkt abierto en Subassembly Composer: SAC lo sobrescribe al guardar.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pktlib as L  # noqa: E402

C3D_DEFAULT = r"C:\Program Files\Autodesk\AutoCAD 2026\C3D"


# ------------------------------------------------------------------ utilidades
def out(s=""):
    print(s)


def sac_running() -> bool:
    if os.name != "nt":
        return False
    try:
        r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=15)
        return "subassemblycomposer" in r.stdout.lower().replace(" ", "")
    except Exception:  # noqa: BLE001
        return False


def next_copy_name(src: str) -> str:
    stem, ext = os.path.splitext(src)
    m = re.search(r"_v(\d+)$", stem)
    base, n = (stem[: m.start()], int(m.group(1)) + 1) if m else (stem, 2)
    while True:
        cand = f"{base}_v{n}{ext}"
        if not os.path.exists(cand):
            return cand
        n += 1


def main_xaml(pkg: L.Package) -> tuple[str, str, str, bytes]:
    names = pkg.xaml_names()
    if not names:
        raise L.PktError("No encuentro ningún XAML dentro del .pkt. Entradas: " + ", ".join(pkg.names()))
    # La más grande suele ser el flujo principal
    name = max(names, key=lambda n: len(pkg.read(n)))
    t, enc, bom = L.decode_text(pkg.read(name))
    return name, t, enc, bom


def parse_where(w: str):
    """'APoint[@DisplayName=P1]', '*[@x:Name=__ReferenceID3]', 'Activity' -> función de coincidencia."""
    m = re.match(r"^([\w.*:-]+)(?:\[@([\w.:-]+)=(.*)\])?$", w.strip())
    if not m:
        raise SystemExit(f"Selector no válido: {w}. Ejemplo: APoint[@DisplayName=P1]")
    el, attr, val = m.groups()

    def f(tag: L.Tag) -> bool:
        if el != "*" and el not in (tag.name, tag.local):
            return False
        if attr is None:
            return True
        return tag.attrs.get(attr) == val
    return f


def rename_class(text: str, new: str) -> tuple[str, str, int]:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", new):
        raise SystemExit("El nombre nuevo debe ser un identificador válido (letras, números, _; sin espacios).")
    root = L.scan_tags(text)[0]
    old = root.attrs.get("x:Class")
    if not old:
        raise L.PktError("La raíz no tiene x:Class; no sé dónde está el nombre. Usa --replace.")
    old_short = old.split(".")[-1]
    new_full = old[: -len(old_short)] + new
    tag = text[root.start: root.end]
    tag2 = L.set_attr_in_tag(tag, "x:Class", new_full)
    tag2, k = re.subn(r"(\s[\w-]+:)" + re.escape(old_short) + r"\.", lambda m: m.group(1) + new + ".", tag2)
    return text[: root.start] + tag2 + text[root.end:], old, k


# ------------------------------------------------------------------ comandos
def cmd_info(a):
    pkg = L.Package.open(a.pkt)
    out(f"Archivo: {a.pkt}  ({len(pkg.raw)} bytes, {len(pkg.entries)} entradas)")
    for e in pkg.entries:
        out(f"  {e.name:50s} {e.usize:>9d} B  {'deflate' if e.method == 8 else 'stored' if e.method == 0 else e.method}")
    for n in pkg.xaml_names():
        t, enc, bom = L.decode_text(pkg.read(n))
        _, prefixes = L.parse_ns(t)
        out(f"\nXAML: {n}  codificación {enc}{' con BOM' if bom else ''}")
        for p, u in sorted(prefixes.items()):
            out(f"  xmlns:{p or '(defecto)'} = {u}")
    g = L.find_guids(pkg)
    out(f"\nGUID encontrados: {len(g)}")
    for k, v in g.items():
        out(f"  {k}  ({len(v)} vez/veces)")
        for c in v[:3]:
            out(f"      {c}")


def cmd_explain(a):
    pkg = L.Package.open(a.pkt)
    name, t, _, _ = main_xaml(pkg)
    an = L.analyze_xaml(t, name)
    if a.json:
        out(json.dumps(an.__dict__, ensure_ascii=False, indent=1))
    else:
        out(L.explain_text(an, a.max))
        others = [n for n in pkg.names() if n != name]
        if others:
            out("\nOtras entradas del paquete: " + ", ".join(others))


def cmd_inventory(a):
    pkg = L.Package.open(a.pkt)
    name, t, _, _ = main_xaml(pkg)
    an = L.analyze_xaml(t, name)
    for k, v in an.inventory.items():
        out(f"{v:6d}  {k}")


def cmd_roundtrip(a):
    raw = open(a.pkt, "rb").read()
    pkg = L.Package.from_bytes(raw, a.pkt)
    for n in pkg.names():
        pkg.read(n)  # comprueba CRC de todo
    rebuilt = pkg.to_bytes()
    ok_zip = rebuilt == raw
    # Texto: decodificar y volver a codificar el XAML también debe dar los mismos bytes
    ok_txt = True
    for n in pkg.xaml_names():
        b = pkg.read(n)
        t, enc, bom = L.decode_text(b)
        ok_txt &= L.encode_text(t, enc, bom) == b
        L.scan_tags(t)
    # Forzar reescritura de la entrada XAML (recomprimiendo) y comprobar contenido equivalente
    name, t, enc, bom = main_xaml(pkg)
    e = pkg.entry(name)
    e.new_data = L.encode_text(t, enc, bom)  # fuerza recompresión aunque no cambie
    forced = L.Package.from_bytes(pkg.to_bytes())
    ok_forced = all(forced.read(n) == L.Package.from_bytes(raw).read(n) for n in forced.names())
    out(f"ZIP idéntico byte a byte sin cambios: {'SÍ' if ok_zip else 'NO'}")
    out(f"XAML texto ida y vuelta idéntico:     {'SÍ' if ok_txt else 'NO'}")
    out(f"Recomprimido: contenido equivalente:  {'SÍ' if ok_forced else 'NO'}")
    return 0 if (ok_zip and ok_txt and ok_forced) else 1


def cmd_extract(a):
    pkg = L.Package.open(a.pkt)
    os.makedirs(a.folder, exist_ok=True)
    root = os.path.realpath(a.folder)
    for n in pkg.names():
        dst = os.path.realpath(os.path.join(root, n))
        if not dst.startswith(root + os.sep):
            out(f"  (omitida, ruta insegura) {n}")
            continue
        if n.endswith("/"):
            os.makedirs(dst, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(pkg.read(n))
        out(f"  {dst}")


def cmd_fragments(a):
    pkg = L.Package.open(a.pkt)
    name, t, _, _ = main_xaml(pkg)
    n = 0
    for tag in L.scan_tags(t):
        if "." in tag.local:
            continue
        kind = L.classify(tag.local)
        if a.kind and kind != a.kind:
            continue
        disp = tag.attrs.get("DisplayName")
        if a.name and disp != a.name:
            continue
        if not a.kind and not a.name and not disp:
            continue
        n += 1
        out(f"===== [{kind}] {disp or tag.local}  ({tag.name}, carácter {tag.start}) =====")
        out(L.element_text(t, tag))
        if n >= a.max:
            break
    if n == 0:
        out("Sin coincidencias.")


def _guard_inputs(a, src):
    if sac_running() and not a.force:
        raise SystemExit("Subassembly Composer está abierto. Cierra el .pkt en SAC (SAC lo sobrescribe al guardar) "
                         "y vuelve a intentarlo, o usa --force si estás seguro de que no es este archivo.")
    dst = a.out or next_copy_name(src)
    if os.path.abspath(dst) == os.path.abspath(src):
        raise SystemExit("La salida no puede ser el archivo original.")
    if os.path.exists(dst) and not a.overwrite:
        raise SystemExit(f"{dst} ya existe. Elige otro --out o usa --overwrite (nunca sobre el original).")
    return dst


def cmd_copy(a):
    dst = _guard_inputs(a, a.pkt)
    pkg = L.Package.open(a.pkt)
    name, t, enc, bom = main_xaml(pkg)
    log = []
    if a.name:
        t, old, k = rename_class(t, a.name)
        log.append(f"x:Class: {old} -> {a.name} (y {k} atributo(s) de valores por defecto)")
        old_short = old.split('.')[-1]
    for where, attr, val in a.set_attr or []:
        t, k = L.edit_attr(t, parse_where(where), attr, val)
        log.append(f"{where}: {attr}={val!r} en {k} elemento(s)")
        if k == 0:
            raise SystemExit(f"Ningún elemento coincide con {where}; no se escribe nada.")
    L.scan_tags(t)  # el XAML sigue siendo XML bien formado
    pkg.write_entry(name, L.encode_text(t, enc, bom))
    # --replace: texto literal en TODAS las entradas de texto (XAML y metadatos XML)
    for old, new in a.replace or []:
        total = 0
        for n in pkg.names():
            try:
                tt, e2, b2 = L.decode_text(pkg.read(n))
            except Exception:  # noqa: BLE001
                continue
            k = tt.count(old)
            if k:
                tt = tt.replace(old, new)
                if n.lower().endswith((".xaml", ".xml")):
                    L.scan_tags(tt)
                pkg.write_entry(n, L.encode_text(tt, e2, b2))
                log.append(f"{n}: '{old}' -> '{new}' ({k} vez/veces)")
                total += k
        if total == 0:
            raise SystemExit(f"'{old}' no aparece en ninguna entrada de texto; no se escribe nada.")
    if a.new_guid:
        guids = L.find_guids(pkg)
        targets = [g.lower() for g in a.guid] if a.guid else list(guids)
        if not a.guid and len(guids) > 1:
            out("Hay varios GUID; indica cuál(es) cambiar con --guid:")
            for g, ctx in guids.items():
                out(f"  {g}: {ctx[0]}")
            raise SystemExit(2)
        if not targets:
            log.append("AVISO: no hay ningún GUID en el paquete; no se cambia nada (SAC/Civil quizá identifiquen el "
                       "subensamblaje solo por el nombre).")
        for g in targets:
            new, k = L.replace_guid(pkg, g)
            log.append(f"GUID {g} -> {new} ({k} vez/veces)")
    if a.name:
        for n in pkg.names():
            try:
                rest = L.decode_text(pkg.read(n))[0].count(old_short)
            except Exception:  # noqa: BLE001
                continue
            if rest:
                log.append(f"AVISO: '{old_short}' aún aparece {rest} vez/veces en {n}; si es el nombre visible del "
                           "paquete, cámbialo también con --replace.")
    pkg.save(dst)
    # verificación de lo escrito
    chk = L.Package.open(dst)
    for n in chk.names():
        chk.read(n)
    out(f"Copia escrita: {dst}")
    for x in log:
        out("  " + x)
    if not log:
        out("  (sin cambios: copia idéntica al original)")


def cmd_pack(a):
    dst = _guard_inputs(a, a.template)
    pkg = L.Package.open(a.template)
    name = a.entry or main_xaml(pkg)[0]
    raw = open(a.xaml, "rb").read()
    t, _, _ = L.decode_text(raw)
    L.scan_tags(t)  # bien formado
    pkg.write_entry(name, raw)
    pkg.save(dst)
    out(f"Paquete escrito: {dst} (entrada {name} sustituida; el resto copiado sin cambios desde {a.template})")


def civil_script(pkt: str, name: str) -> str:
    with open(os.path.join(HERE, "templates", "validate_in_civil.cs"), "r", encoding="utf-8") as f:
        s = f.read()
    return s.replace("{{NAME}}", name.replace('"', '')).replace("{{PKT}}", os.path.abspath(pkt).replace('"', ''))


def cmd_civil_script(a):
    out(civil_script(a.pkt, a.name))


def compare(expected: dict, actual: dict, tol: float) -> list[str]:
    errs = []

    def norm_codes(c):
        return sorted(c or [])

    for kind in ("points", "links", "shapes"):
        exp = expected.get(kind)
        if exp is None:
            continue
        act = actual.get(kind) or []
        if len(exp) != len(act) and expected.get("strict_counts", True):
            errs.append(f"{kind}: esperados {len(exp)}, obtenidos {len(act)}")
        used = set()
        for i, e in enumerate(exp):
            cand = None
            if "index" in e:
                cand = next((j for j, x in enumerate(act) if x.get("index") == e["index"]), None)
            else:
                cand = next((j for j, x in enumerate(act) if j not in used and norm_codes(x.get("codes")) == norm_codes(e.get("codes"))), None)
            if cand is None:
                errs.append(f"{kind}[{i}] codes={e.get('codes')}: no encontrado")
                continue
            used.add(cand)
            x = act[cand]
            for k in ("offset", "elevation"):
                if k in e and (x.get(k) is None or abs(float(x[k]) - float(e[k])) > tol):
                    errs.append(f"{kind}[{i}] codes={e.get('codes')}: {k} esperado {e[k]}, obtenido {x.get(k)}")
            if "codes" in e and "index" in e and norm_codes(x.get("codes")) != norm_codes(e["codes"]):
                errs.append(f"{kind}[{i}]: códigos esperados {e['codes']}, obtenidos {x.get('codes')}")
    return errs


def cmd_compare(a):
    exp = json.load(open(a.expected, encoding="utf-8-sig"))
    act = json.load(open(a.actual, encoding="utf-8-sig"))
    act = act.get("result", act) if isinstance(act, dict) else act
    errs = compare(exp, act, a.tol)
    out("Coincide con lo esperado." if not errs else "Diferencias:\n  " + "\n  ".join(errs))
    return 0 if not errs else 1


def cmd_validate(a):
    rc = 0
    out("1) Estructura")
    pkg = L.Package.open(a.pkt)
    for n in pkg.names():
        pkg.read(n)
    name, t, _, _ = main_xaml(pkg)
    L.scan_tags(t)
    an = L.analyze_xaml(t, name)
    out(f"   ZIP y CRC correctos; XAML bien formado ({name}); {len(an.params)} parámetros; "
        + ", ".join(f"{L.KIND_ES.get(k, k)} {v}" for k, v in sorted(an.counts.items())))
    raw = open(a.pkt, "rb").read()
    same = L.Package.from_bytes(raw).to_bytes() == raw
    out(f"   Lectura/escritura sin pérdida: {'OK' if same else 'FALLO'}")
    rc |= 0 if same else 1

    if a.xaml_load:
        out("2) ActivityXamlServices.Load con el motor de Civil 3D (UiPath.Workflow.dll)")
        ps1 = os.path.join(HERE, "Validate-PktXaml.ps1")
        r = subprocess.run(["pwsh", "-NoProfile", "-File", ps1, "-Pkt", os.path.abspath(a.pkt), "-C3DDir", a.c3d_dir],
                           capture_output=True, text=True)
        out("   " + (r.stdout + r.stderr).strip().replace("\n", "\n   "))
        rc |= r.returncode
    else:
        out("2) Carga XAML: omitida (añade --xaml-load; necesita Windows, pwsh y Civil 3D instalado)")

    if a.civil:
        out("3) Prueba en Civil 3D (run_query: el dibujo no cambia)")
        sys.path.insert(0, os.path.join(HERE, "..", "mcp"))
        import civil_bridge_client as bridge  # noqa: E402
        if not a.name:
            raise SystemExit("--civil necesita --name (nombre con el que importar el subensamblaje).")
        resp = bridge.call("query", code=civil_script(a.pkt, a.name), label=f"validate {os.path.basename(a.pkt)}", timeout=300)
        if not resp.get("ok"):
            out("   ERROR: " + str(resp.get("error")))
            for d in resp.get("diagnostics") or []:
                out(f"     línea {d.get('line')}: {d.get('message')}")
            return 1
        res = resp.get("result")
        out("   " + json.dumps(res, ensure_ascii=False, indent=1).replace("\n", "\n   "))
        if a.expected:
            errs = compare(json.load(open(a.expected, encoding="utf-8-sig")), res, a.tol)
            out("   Comparación: " + ("coincide" if not errs else "DIFERENCIAS\n     " + "\n     ".join(errs)))
            rc |= 1 if errs else 0
    else:
        out("3) Prueba en Civil 3D: omitida (añade --civil --name X con Civil 3D abierto)")
    out("4) Falta tu confirmación visual: abre el .pkt en Subassembly Composer y revisa la vista previa.")
    return rc


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Lector/escritor sin pérdida de .pkt de Subassembly Composer")
    s = p.add_subparsers(dest="cmd", required=True)
    for n in ("info", "inventory", "roundtrip"):
        s.add_parser(n).add_argument("pkt")
    x = s.add_parser("explain"); x.add_argument("pkt"); x.add_argument("--json", action="store_true"); x.add_argument("--max", type=int, default=400)
    x = s.add_parser("extract"); x.add_argument("pkt"); x.add_argument("folder")
    x = s.add_parser("fragments"); x.add_argument("pkt"); x.add_argument("--kind"); x.add_argument("--name"); x.add_argument("--max", type=int, default=50)
    x = s.add_parser("copy"); x.add_argument("pkt"); x.add_argument("--out"); x.add_argument("--name")
    x.add_argument("--new-guid", action="store_true"); x.add_argument("--guid", action="append")
    x.add_argument("--set-attr", nargs=3, action="append", metavar=("SELECTOR", "ATRIBUTO", "VALOR"))
    x.add_argument("--replace", nargs=2, action="append", metavar=("VIEJO", "NUEVO"))
    x.add_argument("--force", action="store_true"); x.add_argument("--overwrite", action="store_true")
    x = s.add_parser("pack"); x.add_argument("--template", required=True); x.add_argument("--xaml", required=True)
    x.add_argument("--out"); x.add_argument("--entry"); x.add_argument("--force", action="store_true"); x.add_argument("--overwrite", action="store_true")
    x = s.add_parser("validate"); x.add_argument("pkt"); x.add_argument("--xaml-load", action="store_true")
    x.add_argument("--civil", action="store_true"); x.add_argument("--name"); x.add_argument("--expected")
    x.add_argument("--tol", type=float, default=0.001); x.add_argument("--c3d-dir", default=C3D_DEFAULT)
    x = s.add_parser("civil-script"); x.add_argument("pkt"); x.add_argument("--name", required=True)
    x = s.add_parser("compare"); x.add_argument("expected"); x.add_argument("actual"); x.add_argument("--tol", type=float, default=0.001)
    a = p.parse_args()
    fn = globals()["cmd_" + a.cmd.replace("-", "_")]
    try:
        return fn(a) or 0
    except (L.PktError, OSError) as e:
        print("ERROR: " + str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
