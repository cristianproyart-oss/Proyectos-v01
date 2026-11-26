// Validación de un .pkt dentro de Civil 3D. Ejecutar SIEMPRE con run_query (la transacción se aborta:
// el subensamblaje importado desaparece y el dibujo no cambia).
// pkt_tool.py sustituye {{NAME}} y {{PKT}}. Las colecciones se leen por reflexión para tolerar
// diferencias de API entre versiones (Get/Items/T son helpers del add-in); si algo falla, el campo muestra "!Error: ...".
string name = "{{NAME}}";
string pkt = @"{{PKT}}";
if (!File.Exists(pkt)) return "No existe el archivo: " + pkt;

List<string> Codes(object o)
{
    var c = Get(o, "Codes");
    if (c is System.Collections.IEnumerable e && !(c is string)) return e.Cast<object>().Select(x => x?.ToString()).ToList();
    return c == null ? new List<string>() : new List<string> { c.ToString() };
}
double? Num(object o, string prop) { var v = Get(o, prop); return v == null ? (double?)null : Math.Round(Convert.ToDouble(v), 6); }

// 1) Importar el .pkt como subensamblaje (en un punto lejos de todo)
ObjectId id = civ.SubassemblyCollection.ImportSACSubassembly(name, pkt, new Point3d(0, 0, 0));
var sub = (Subassembly)tr.GetObject(id, OpenMode.ForWrite);

// 2) Parámetros de entrada (para saber con qué valores se calculó)
var parms = new Dictionary<string, object>();
foreach (var collName in new[] { "ParamsDouble", "ParamsLong", "ParamsString", "ParamsBool" })
{
    var r = T(() => { foreach (var p in Items(Get(sub, collName)))
                        { var k = Get(p, "Key") ?? Get(p, "DisplayName"); parms[k?.ToString() ?? "?"] = Get(p, "Value"); }
                      return 0; });
}
// Para probar con otros valores, descomenta y ajusta (los nombres son los de tus parámetros de SAC):
// sub.ParamsDouble["Width"].Value = 3.5;

// 3) Ejecutar la geometría
var runResult = T(() => { sub.Run(); return "ok"; });

// 4) Leer puntos, enlaces y formas
var pts = Items(Get(sub, "Points")).Select((p, i) => (object)new
{
    index = i, codes = Codes(p), offset = Num(p, "Offset"), elevation = Num(p, "Elevation"),
}).ToList();

var links = Items(Get(sub, "Links")).Select((l, i) => (object)new
{
    index = i, codes = Codes(l),
    points = T(() => Items(Get(l, "Points")).Select(p => new { offset = Num(p, "Offset"), elevation = Num(p, "Elevation") }).ToList()),
}).ToList();

var shapes = Items(Get(sub, "Shapes")).Select((s, i) => (object)new
{
    index = i, codes = Codes(s),
    links = T(() => Items(Get(s, "Links")).Count),
    area = T(() => Get(s, "Area")),
}).ToList();

return new
{
    name, pkt, run = runResult,
    // sub.Side lanza excepción si !sub.HasSide: por eso se comprueba antes
    side = T(() => sub.HasSide ? sub.Side.ToString() : "(sin lado)"),
    parameters = parms,
    counts = new { points = pts.Count, links = links.Count, shapes = shapes.Count },
    points = pts, links, shapes,
    note = "Modo query: este subensamblaje no queda en el dibujo. En layout, ΔY con punto de referencia es vertical, no perpendicular."
};
