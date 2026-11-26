"""Biblioteca para archivos .pkt de Subassembly Composer (SAC). Solo biblioteca estándar.

Un .pkt es un ZIP con un flujo XAML (Windows Workflow). Este módulo:
  * Lee y escribe el ZIP SIN PÉRDIDA: las entradas que no cambias se copian byte a byte
    (cabeceras, extras, fechas, comentarios y orden incluidos). Si no cambias nada, el
    archivo resultante es idéntico al original.
  * Edita el XAML como TEXTO, en posiciones exactas, sin re-serializar el XML: se
    conservan prefijos (asa1, asa2...), espacios, orden de atributos y comentarios.
  * Analiza el XAML (ElementTree) para explicarlo.
"""
from __future__ import annotations

import codecs
import re
import struct
import uuid
import xml.etree.ElementTree as ET
import xml.parsers.expat
import zlib
from dataclasses import dataclass, field

# ============================================================ ZIP sin pérdida
SIG_LOCAL, SIG_CENTRAL, SIG_EOCD, SIG_DD = 0x04034B50, 0x02014B50, 0x06054B50, 0x08074B50


class PktError(Exception):
    pass


@dataclass
class Entry:
    name: str
    central: bytes          # registro del directorio central original (con nombre/extra/comentario)
    local_offset: int
    method: int
    flags: int
    crc: int
    csize: int
    usize: int
    segment: bytes = b""    # bytes originales desde la cabecera local hasta la siguiente entrada
    new_data: bytes | None = None  # contenido descomprimido nuevo (None = sin cambios)
    _data: bytes | None = None

    @property
    def changed(self) -> bool:
        return self.new_data is not None


@dataclass
class Package:
    path: str
    raw: bytes
    entries: list[Entry]
    preamble: bytes
    eocd_comment: bytes
    eocd_disk: bytes
    tail_between: bytes = b""   # bytes entre el directorio central y el EOCD (raro)

    # ----------------------------------------------------------- lectura
    @classmethod
    def open(cls, path: str) -> "Package":
        with open(path, "rb") as f:
            raw = f.read()
        return cls.from_bytes(raw, path)

    @classmethod
    def from_bytes(cls, raw: bytes, path: str = "<memoria>") -> "Package":
        pos = raw.rfind(struct.pack("<I", SIG_EOCD), max(0, len(raw) - 65557))
        if pos < 0:
            raise PktError("No es un ZIP válido (no hay fin de directorio central). ¿Es realmente un .pkt?")
        (_, disk, disk_cd, n_disk, n_total, cd_size, cd_off, clen) = struct.unpack_from("<IHHHHIIH", raw, pos)
        if 0xFFFF in (n_disk, n_total) or 0xFFFFFFFF in (cd_size, cd_off):
            raise PktError("ZIP64 no soportado (un .pkt normal no lo usa).")
        if disk or disk_cd:
            raise PktError("ZIP multivolumen no soportado.")
        comment = raw[pos + 22: pos + 22 + clen]
        entries: list[Entry] = []
        p = cd_off
        for _ in range(n_total):
            sig, = struct.unpack_from("<I", raw, p)
            if sig != SIG_CENTRAL:
                raise PktError(f"Directorio central dañado en el byte {p}.")
            (_, _vm, _vn, flags, method, _t, _d, crc, csize, usize, fnl, exl, cml, _ds, _ia, _ea, loff) = \
                struct.unpack_from("<IHHHHHHIIIHHHHHII", raw, p)
            rec_len = 46 + fnl + exl + cml
            nb = raw[p + 46: p + 46 + fnl]
            name = nb.decode("utf-8" if flags & 0x800 else "cp437")
            if flags & 0x1:
                raise PktError(f"La entrada {name} está cifrada; no se puede procesar.")
            entries.append(Entry(name, raw[p: p + rec_len], loff, method, flags, crc, csize, usize))
            p += rec_len
        tail_between = raw[cd_off + cd_size: pos]
        order = sorted(entries, key=lambda e: e.local_offset)
        for i, e in enumerate(order):
            end = order[i + 1].local_offset if i + 1 < len(order) else cd_off
            e.segment = raw[e.local_offset: end]
            if struct.unpack_from("<I", e.segment, 0)[0] != SIG_LOCAL:
                raise PktError(f"Cabecera local dañada para {e.name}.")
        preamble = raw[: order[0].local_offset] if order else raw[:cd_off]
        return cls(path, raw, entries, preamble, comment, raw[pos + 4: pos + 8], tail_between)

    def names(self) -> list[str]:
        return [e.name for e in self.entries]

    def entry(self, name: str) -> Entry:
        for e in self.entries:
            if e.name == name:
                return e
        raise KeyError(name)

    def read(self, name: str) -> bytes:
        e = self.entry(name)
        if e.new_data is not None:
            return e.new_data
        return self.read_original(name)

    def read_original(self, name: str) -> bytes:
        e = self.entry(name)
        if e._data is None:
            seg = e.segment
            fnl, exl = struct.unpack_from("<HH", seg, 26)
            start = 30 + fnl + exl
            comp = seg[start: start + e.csize]
            if e.method == 0:
                data = comp
            elif e.method == 8:
                data = zlib.decompressobj(-15).decompress(comp)
            else:
                raise PktError(f"Método de compresión {e.method} no soportado en {e.name}.")
            if zlib.crc32(data) & 0xFFFFFFFF != e.crc:
                raise PktError(f"CRC incorrecto en {e.name}: el archivo está dañado.")
            e._data = data
        return e._data

    def write_entry(self, name: str, data: bytes) -> None:
        e = self.entry(name)
        if data == self.read_original(name):
            e.new_data = None  # sin cambios reales: se conserva el original byte a byte
        else:
            e.new_data = data

    # ----------------------------------------------------------- escritura
    def to_bytes(self) -> bytes:
        out = bytearray(self.preamble)
        new_offsets: dict[int, int] = {}
        new_central: dict[int, bytes] = {}
        for e in sorted(self.entries, key=lambda x: x.local_offset):
            new_offsets[id(e)] = len(out)
            if not e.changed:
                out += e.segment
                new_central[id(e)] = e.central
                continue
            data = e.new_data
            if e.method == 8:
                co = zlib.compressobj(9, zlib.DEFLATED, -15)
                comp = co.compress(data) + co.flush()
            else:
                comp = data
            crc = zlib.crc32(data) & 0xFFFFFFFF
            seg = e.segment
            ver, flags, method, t, d = struct.unpack_from("<HHHHH", seg, 4)
            fnl, exl = struct.unpack_from("<HH", seg, 26)
            name_b, extra_b = seg[30: 30 + fnl], seg[30 + fnl: 30 + fnl + exl]
            flags &= ~0x8  # sin descriptor de datos: tamaños en la cabecera
            out += struct.pack("<IHHHHHIIIHH", SIG_LOCAL, ver, flags, method, t, d, crc, len(comp), len(data), fnl, exl)
            out += name_b + extra_b + comp
            c = bytearray(e.central)
            struct.pack_into("<H", c, 8, (struct.unpack_from("<H", c, 8)[0]) & ~0x8)
            struct.pack_into("<III", c, 16, crc, len(comp), len(data))
            new_central[id(e)] = bytes(c)
        cd_start = len(out)
        for e in self.entries:  # orden original del directorio central
            c = bytearray(new_central[id(e)])
            struct.pack_into("<I", c, 42, new_offsets[id(e)])
            out += c
        cd_size = len(out) - cd_start
        out += self.tail_between
        n = len(self.entries)
        out += struct.pack("<I", SIG_EOCD) + self.eocd_disk
        out += struct.pack("<HHIIH", n, n, cd_size, cd_start, len(self.eocd_comment)) + self.eocd_comment
        return bytes(out)

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    def xaml_names(self) -> list[str]:
        xs = [n for n in self.names() if n.lower().endswith(".xaml")]
        if xs:
            return xs
        # Por si la extensión es otra: cualquier entrada cuyo contenido empiece como XAML de Workflow.
        out = []
        for n in self.names():
            try:
                head = decode_text(self.read(n)[:4096])[0]
            except Exception:  # noqa: BLE001
                continue
            if "<Activity" in head and "schemas.microsoft.com/netfx/2009/xaml/activities" in head:
                out.append(n)
        return out


# ============================================================ texto sin pérdida
_BOMS = [(codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")]


def decode_text(b: bytes) -> tuple[str, str, bytes]:
    """Devuelve (texto, codificación, BOM). encode_text(texto, cod, bom) reproduce los bytes exactos."""
    for bom, enc in _BOMS:
        if b.startswith(bom):
            return b[len(bom):].decode(enc), enc, bom
    m = re.match(rb'<\?xml[^>]*encoding=["\']([\w.-]+)["\']', b)
    enc = m.group(1).decode("ascii").lower() if m else "utf-8"
    if enc in ("utf-16", "unicode"):
        enc = "utf-16-le"
    return b.decode(enc), enc, b""


def encode_text(t: str, enc: str, bom: bytes) -> bytes:
    return bom + t.encode(enc)


@dataclass
class Tag:
    name: str           # nombre tal como aparece, con prefijo (asa1:APoint)
    start: int          # índice (en caracteres) de "<"
    end: int            # índice justo después de ">"
    attrs: dict
    depth: int
    close_start: int = -1  # inicio de </...> (o == start si es <.../>)
    close_end: int = -1

    @property
    def local(self) -> str:
        return self.name.split(":", 1)[-1]

    @property
    def prefix(self) -> str:
        return self.name.split(":", 1)[0] if ":" in self.name else ""


def scan_tags(text: str) -> list[Tag]:
    """Localiza cada elemento en el texto (posiciones exactas) usando expat sobre UTF-8."""
    data = text.encode("utf-8")
    # mapa de byte -> carácter para traducir posiciones
    char_at = _byte_to_char_map(text)
    p = xml.parsers.expat.ParserCreate()  # sin procesar espacios de nombres: nombres crudos con prefijo
    p.ordered_attributes = False
    tags: list[Tag] = []
    stack: list[Tag] = []

    def start(name, attrs):
        b = p.CurrentByteIndex
        s = char_at(b)
        e = _tag_end(text, s)
        t = Tag(name, s, e, attrs, len(stack))
        tags.append(t)
        stack.append(t)

    def end(name):
        t = stack.pop()
        b = p.CurrentByteIndex
        s = char_at(b)
        if text.startswith("</", s):
            t.close_start, t.close_end = s, text.index(">", s) + 1
        else:  # elemento vacío <x/>: expat informa la posición del propio tag
            t.close_start, t.close_end = t.end, t.end

    p.StartElementHandler = start
    p.EndElementHandler = end
    p.Parse(data, True)
    return tags


def _byte_to_char_map(text: str):
    if text.isascii():
        return lambda b: b
    offs = []  # offs[i] = byte en el que empieza el carácter i
    n = 0
    for ch in text:
        offs.append(n)
        n += len(ch.encode("utf-8"))
    import bisect

    def f(b):
        return bisect.bisect_left(offs, b)
    return f


def _tag_end(text: str, s: int) -> int:
    q = None
    i = s
    while i < len(text):
        c = text[i]
        if q:
            if c == q:
                q = None
        elif c in "\"'":
            q = c
        elif c == ">":
            return i + 1
        i += 1
    raise PktError("Etiqueta sin cerrar en la posición %d" % s)


def xml_attr_escape(v: str) -> str:
    return (v.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
            .replace("\n", "&#xA;").replace("\r", "&#xD;").replace("\t", "&#x9;"))


_ATTR_RE = r'(\s{name}\s*=\s*)(["\'])(.*?)\2'


def set_attr_in_tag(tag_text: str, attr: str, value: str) -> str:
    """Cambia (o añade) un atributo dentro del texto de una etiqueta de apertura, sin tocar nada más."""
    rx = re.compile(_ATTR_RE.format(name=re.escape(attr)), re.S)
    m = rx.search(tag_text)
    if m:
        return tag_text[: m.start(3)] + xml_attr_escape(value) + tag_text[m.end(3):]
    close = len(tag_text) - (2 if tag_text.endswith("/>") else 1)
    return tag_text[:close].rstrip() + f' {attr}="{xml_attr_escape(value)}"' + tag_text[close:]


def edit_attr(text: str, match, attr: str, value: str) -> tuple[str, int]:
    """Aplica set_attr a todas las etiquetas para las que match(tag) es True. Devuelve (texto, n)."""
    tags = [t for t in scan_tags(text) if match(t)]
    for t in sorted(tags, key=lambda t: t.start, reverse=True):
        text = text[: t.start] + set_attr_in_tag(text[t.start: t.end], attr, value) + text[t.end:]
    return text, len(tags)


def element_text(text: str, tag: Tag) -> str:
    """Texto completo del elemento (apertura + contenido + cierre), tal cual."""
    return text[tag.start: tag.close_end]


# ============================================================ GUID y nombre
GUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def find_guids(pkg: Package) -> dict[str, list[str]]:
    """GUID -> lista de 'entrada: contexto' donde aparece."""
    out: dict[str, list[str]] = {}
    for n in pkg.names():
        try:
            t = decode_text(pkg.read(n))[0]
        except Exception:  # noqa: BLE001
            continue
        for m in GUID_RE.finditer(t):
            ctx = t[max(0, m.start() - 60): m.end() + 10].replace("\n", " ")
            out.setdefault(m.group(0).lower(), []).append(f"{n}: …{ctx}…")
    return out


def replace_guid(pkg: Package, old: str, new: str | None = None) -> tuple[str, int]:
    new = new or str(uuid.uuid4())
    total = 0
    rx = re.compile(re.escape(old), re.I)
    for n in pkg.names():
        b = pkg.read(n)
        try:
            t, enc, bom = decode_text(b)
        except Exception:  # noqa: BLE001
            continue
        # Conserva mayúsculas/minúsculas y llaves del original
        def sub(m):
            s = m.group(0)
            return new.upper() if s.isupper() else new
        t2, k = rx.subn(sub, t)
        if k:
            pkg.write_entry(n, encode_text(t2, enc, bom))
            total += k
    return new, total


# ============================================================ análisis
NS_X = "http://schemas.microsoft.com/winfx/2006/xaml"
NS_WF = "http://schemas.microsoft.com/netfx/2009/xaml/activities"
# Atributos de diseño que no aportan nada a la explicación
NOISE = ("WorkflowViewState", "VirtualizedContainerService", "HintSize", "ViewStateManager", "Ignorable", "IdRef",
         "AnnotationText")


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag.split(":")[-1]


def nsuri(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def parse_ns(text: str) -> tuple[ET.Element, dict[str, str]]:
    """Raíz ElementTree + mapa prefijo -> URI (todas las declaraciones)."""
    import io
    prefixes: dict[str, str] = {}
    root = None
    for ev, obj in ET.iterparse(io.BytesIO(text.encode("utf-8")), events=("start-ns", "start")):
        if ev == "start-ns":
            pre, uri = obj
            prefixes.setdefault(pre, uri)
        elif root is None:
            root = obj
    # iterparse deja el árbol completo construido en root al terminar
    return root, prefixes


def classify(localname: str) -> str:
    n = localname.lower()
    if n in ("flowdecision",) or "decision" in n:
        return "decision"
    if n in ("flowswitch",) or "switch" in n:
        return "switch"
    if "shape" in n:
        return "shape"
    if "link" in n:
        return "link"
    if "point" in n:
        return "point"
    if "variable" in n:
        return "variable"
    if "target" in n or "surface" in n:
        return "target"
    if "sequence" in n:
        return "sequence"
    if n in ("flowchart", "flowstep") or "flowchart" in n:
        return "flow"
    return "other"


def _clean_attrs(el: ET.Element) -> dict[str, str]:
    d = {}
    for k, v in el.attrib.items():
        lk = local(k)
        if any(x in k for x in NOISE):
            continue
        d[("x:" if nsuri(k) == NS_X else "") + lk] = v
    return d


def _props_children(el: ET.Element) -> dict[str, str]:
    """Propiedades en forma de elemento hijo (<asa:APoint.Offset>...</...>) con su texto/expresión."""
    out = {}
    for ch in el:
        ln = local(ch.tag)
        if "." in ln and ln.split(".")[0] == local(el.tag):
            prop = ln.split(".", 1)[1]
            if any(x in prop for x in NOISE):
                continue
            texts = []
            for sub in ch.iter():
                if sub is ch:
                    if (sub.text or "").strip():
                        texts.append(sub.text.strip())
                    continue
                if local(sub.tag).endswith(("CSharpValue", "VisualBasicValue", "CSharpReference", "VisualBasicReference")):
                    texts.append(sub.attrib.get("ExpressionText", (sub.text or "").strip()))
                elif (sub.text or "").strip():
                    texts.append(sub.text.strip())
                if "ExpressionText" in sub.attrib and not local(sub.tag).endswith(("Value", "Reference")):
                    texts.append(sub.attrib["ExpressionText"])
            if texts:
                out[prop] = " | ".join(texts)
            elif len(ch):
                out[prop] = "<" + ", ".join(local(s.tag) for s in ch) + ">"
    return out


@dataclass
class Analysis:
    xaml_entry: str
    root_class: str | None
    prefixes: dict
    activity_prefixes: list
    params: list = field(default_factory=list)
    defaults: dict = field(default_factory=dict)
    nodes: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    inventory: dict = field(default_factory=dict)


def analyze_xaml(text: str, entry: str = "") -> Analysis:
    root, prefixes = parse_ns(text)
    root_class = root.attrib.get(f"{{{NS_X}}}Class")
    act_prefixes = sorted(p for p, u in prefixes.items()
                          if "Subassembly" in u or "Civil" in u or "Aecc" in u or re.match(r"asa\d*$", p or ""))
    a = Analysis(entry, root_class, prefixes, act_prefixes)

    # Parámetros: <x:Members><x:Property Name=".." Type="InArgument(x:Double)"/>
    for prop in root.iter(f"{{{NS_X}}}Property"):
        typ = prop.attrib.get("Type", "")
        m = re.match(r"(InOutArgument|InArgument|OutArgument|Property)\((.*)\)$", typ)
        direction = {"InArgument": "entrada", "OutArgument": "salida", "InOutArgument": "entrada/salida"}.get(
            m.group(1) if m else "", "propiedad")
        inner = m.group(2) if m else typ
        kind = "target" if re.search(r"target|surface|offset|elevation", inner, re.I) and not re.search(
            r"x:(Double|Int32|String|Boolean)$", inner) else "valor"
        extra = {local(k): v for k, v in prop.attrib.items() if local(k) not in ("Name", "Type")}
        a.params.append({"name": prop.attrib.get("Name"), "direction": direction, "type": inner, "kind": kind, **extra})

    # Valores por defecto: atributos de la raíz del tipo prefijo:Clase.Param="valor"
    for k, v in root.attrib.items():
        ln = local(k)
        if "." in ln and root_class and ln.split(".")[0] == root_class.split(".")[-1]:
            a.defaults[ln.split(".", 1)[1]] = v

    inv: dict[str, int] = {}
    for el in root.iter():
        inv[local(el.tag)] = inv.get(local(el.tag), 0) + 1
    a.inventory = dict(sorted(inv.items(), key=lambda kv: -kv[1]))

    # Mapa x:Name -> nombre visible (para seguir saltos x:Reference del diagrama de flujo)
    refname: dict[str, str] = {}
    for el in root.iter():
        xn = el.attrib.get(f"{{{NS_X}}}Name")
        if xn:
            disp = el.attrib.get("DisplayName")
            if not disp:
                for sub in el.iter():
                    if sub is not el and "." not in local(sub.tag) and sub.attrib.get("DisplayName"):
                        disp = sub.attrib["DisplayName"]
                        break
            refname[xn] = disp or local(el.tag)

    def add(depth, element, kind, name, attrs=None, props=None):
        a.nodes.append({"depth": depth, "element": element, "kind": kind, "name": name,
                        "attrs": attrs or {}, "props": props or {}})

    # Recorrido con profundidad para un esquema legible
    def walk(el, depth, parent_local=""):
        ln = local(el.tag)
        if ln == "Reference" and nsuri(el.tag) == NS_X:
            target = (el.text or "").strip() or el.attrib.get("Name", "")
            add(depth, "x:Reference", "jump", f"salta a «{refname.get(target, target)}» ({target})")
            return
        if "." in ln:  # elemento-propiedad: sus hijos cuelgan del padre
            owner, prop = ln.split(".", 1)
            if any(x in prop for x in NOISE):
                return
            if owner == "FlowDecision" and prop in ("True", "False"):
                add(depth, ln, "branch", "Si se cumple" if prop == "True" else "Si NO se cumple")
                for ch in el:
                    walk(ch, depth + 1, ln)
                return
            if owner == "FlowSwitch" and prop == "Default":
                add(depth, ln, "branch", "Caso por defecto")
                for ch in el:
                    walk(ch, depth + 1, ln)
                return
            for ch in el:
                walk(ch, depth, ln)
            return
        if ln in ("Members", "Property", "TextExpression.NamespacesForImplementation",
                  "TextExpression.ReferencesForImplementation", "Collection", "AssemblyReference", "String"):
            return
        key = el.attrib.get(f"{{{NS_X}}}Key")
        if key is not None:  # caso de un FlowSwitch
            add(depth, ln, "branch", f"Caso «{key}»")
            depth += 1
        kind = classify(ln)
        attrs = _clean_attrs(el)
        attrs.pop("x:Key", None)
        props = {k: v for k, v in _props_children(el).items() if not v.startswith("<")}
        if ln == "FlowStep" or ln == "Activity":
            for ch in el:
                walk(ch, depth, ln)
            return
        meaningful = kind != "other" or "DisplayName" in attrs or props
        if meaningful:
            attrs.pop("x:Name", None)
            add(depth, ln, kind, attrs.get("DisplayName") or ln, attrs, props)
            a.counts[kind] = a.counts.get(kind, 0) + 1
            depth += 1
        for ch in el:
            walk(ch, depth, ln)

    walk(root, 0)
    return a


KIND_ES = {"branch": "→", "jump": "↪", "point": "Punto", "link": "Enlace", "shape": "Forma", "decision": "Decisión", "switch": "Switch",
           "variable": "Variable", "target": "Target", "sequence": "Secuencia", "flow": "Flujo", "other": "Actividad"}


def explain_text(a: Analysis, max_nodes: int = 400) -> str:
    L = []
    L.append(f"Entrada XAML: {a.xaml_entry}")
    L.append(f"Clase (x:Class): {a.root_class}")
    if a.activity_prefixes:
        L.append("Prefijos de la librería de actividades: " + ", ".join(f"{p} = {a.prefixes[p]}" for p in a.activity_prefixes))
    L.append("")
    L.append("PARÁMETROS")
    if not a.params:
        L.append("  (no hay x:Members/x:Property; puede que SAC guarde los parámetros en otro sitio: revisa 'inventory')")
    for p in a.params:
        d = a.defaults.get(p["name"])
        extra = ", ".join(f"{k}={v}" for k, v in p.items() if k not in ("name", "direction", "type", "kind"))
        L.append(f"  - {p['name']}: {p['direction']}, tipo {p['type']}"
                 + (" [TARGET]" if p["kind"] == "target" else "")
                 + (f", por defecto {d}" if d is not None else "") + (f" ({extra})" if extra else ""))
    L.append("")
    L.append("RESUMEN: " + ", ".join(f"{KIND_ES.get(k, k)}: {v}" for k, v in sorted(a.counts.items())))
    L.append("")
    L.append("ESTRUCTURA (orden del flujo, sangría = anidamiento)")
    for n in a.nodes[:max_nodes]:
        ind = '  ' * (n['depth'] + 1)
        if n["kind"] in ("branch", "jump"):
            L.append(f"{ind}{KIND_ES[n['kind']]} {n['name']}")
            continue
        head = f"{ind}{KIND_ES.get(n['kind'], n['kind'])} «{n['name'] or n['element']}» ({n['element']})"
        L.append(head)
        details = {k: v for k, v in n["attrs"].items() if k not in ("DisplayName",)}
        details.update(n["props"])
        for k, v in list(details.items())[:25]:
            v1 = v if len(v) <= 160 else v[:157] + "…"
            L.append(f"{'  ' * (n['depth'] + 2)}· {k} = {v1}")
    if len(a.nodes) > max_nodes:
        L.append(f"  … {len(a.nodes) - max_nodes} nodos más")
    L.append("")
    L.append("Nota: las expresiones de SAC usan sintaxis VB (If(...), Math.Abs, P1.Y, SE.Slope).")
    return "\n".join(L)
