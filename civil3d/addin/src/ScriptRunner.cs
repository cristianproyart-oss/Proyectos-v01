// Compila C# en memoria con Roslyn y lo ejecuta en el documento activo.
// El script es el CUERPO de un método con estas variables disponibles:
//   doc (Document), db (Database), ed (Editor), civ (CivilDocument), tr (Transaction)
// Puede usar "return algo;" (texto, número, lista, objeto anónimo... se devuelve como JSON)
// y Console.WriteLine(...) (se devuelve como salida de consola). Para funciones auxiliares
// usa funciones locales de C#. Si necesitas "using" extra, ponlos al principio del script:
// las líneas iniciales que empiezan por "using " y terminan en ";" se mueven fuera del método.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.Loader;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.Civil.ApplicationServices;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;

namespace Civil3DAgent
{
    public static class ScriptRunner
    {
        static List<MetadataReference> _refs;
        static readonly object _refsLock = new object();

        const string DefaultUsings = @"using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Civil;
using Autodesk.Civil.ApplicationServices;
using Autodesk.Civil.DatabaseServices;
using Autodesk.Civil.DatabaseServices.Styles;
using Application = Autodesk.AutoCAD.ApplicationServices.Core.Application;
using Entity = Autodesk.AutoCAD.DatabaseServices.Entity;
using DBObject = Autodesk.AutoCAD.DatabaseServices.DBObject;
using ObjectId = Autodesk.AutoCAD.DatabaseServices.ObjectId;
using Point = Autodesk.Civil.DatabaseServices.Point;
using Surface = Autodesk.Civil.DatabaseServices.Surface;
using Section = Autodesk.Civil.DatabaseServices.Section;
using Exception = System.Exception;
using static Civil3DAgent.ScriptHelpers;
";
        // Nota: Point, Surface y Section existen en AutoCAD y en Civil; los alias de arriba fijan los de Civil.
        // Para geometría usa Point3d/Point2d; para el sólido de AutoCAD, Autodesk.AutoCAD.DatabaseServices.Surface.
        // "using static Civil3DAgent.ScriptHelpers" permite usar T(...) y Props(...) directamente.

        public static List<MetadataReference> References
        {
            get { lock (_refsLock) return _refs ??= BuildReferences(out _); }
        }

        /// <summary>Lista de referencias: runtime .NET 8 (NETCore + WindowsDesktop) + DLL de AutoCAD/Civil.</summary>
        public static List<MetadataReference> BuildReferences(out List<string> report)
        {
            report = new List<string>();
            var files = new List<string>();
            string netcore = Path.GetDirectoryName(typeof(object).Assembly.Location);
            string desktop = Path.GetDirectoryName(typeof(System.Windows.Forms.Form).Assembly.Location);
            string acad = Path.GetDirectoryName(typeof(Database).Assembly.Location); // ...\AutoCAD 2026
            foreach (var dir in new[] { netcore, desktop }.Distinct(StringComparer.OrdinalIgnoreCase))
                files.AddRange(Directory.GetFiles(dir, "*.dll"));
            foreach (var rel in new[] { "acdbmgd.dll", "acmgd.dll", "accoremgd.dll",
                                        @"C3D\AeccDbMgd.dll", @"ACA\AecBaseMgd.dll",
                                        // opcionales, si existen:
                                        @"C3D\AeccPressurePipesMgd.dll", @"C3D\AeccRailMgd.dll",
                                        @"C3D\AeccDataShortcutMgd.dll", "AcWindows.dll", "AdWindows.dll" })
            {
                var f = Path.Combine(acad, rel);
                if (File.Exists(f)) files.Add(f); else report.Add("no encontrada (se omite): " + f);
            }
            files.Add(typeof(ScriptRunner).Assembly.Location); // helpers del propio add-in

            var refs = new List<MetadataReference>();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var f in files)
            {
                var name = Path.GetFileNameWithoutExtension(f);
                if (!seen.Add(name)) continue;
                if (!IsManaged(f)) { report.Add("nativa (se omite): " + f); continue; }
                try { refs.Add(MetadataReference.CreateFromFile(f)); }
                catch (System.Exception ex) { report.Add($"error ({ex.Message}): {f}"); }
            }
            return refs;
        }

        /// <summary>true si la DLL tiene metadatos .NET (las nativas se saltan).</summary>
        static bool IsManaged(string path)
        {
            try
            {
                using var fs = File.OpenRead(path);
                using var pe = new System.Reflection.PortableExecutable.PEReader(fs);
                return pe.HasMetadata;
            }
            catch { return false; }
        }

        // "using X.Y;", "using static X.Y;" o "using Alias = X.Y;" (no confunde con "using var x = ...;")
        static readonly System.Text.RegularExpressions.Regex UsingDirective = new System.Text.RegularExpressions.Regex(
            @"^using\s+((static\s+)?[\w.]+|\w+\s*=\s*[\w.<>,\s]+)\s*;$");

        static (string usings, string body) SplitUsings(string code)
        {
            var lines = code.Replace("\r\n", "\n").Split('\n');
            var u = new StringBuilder(); int i = 0;
            for (; i < lines.Length; i++)
            {
                var t = lines[i].Trim();
                if (t.Length == 0 || t.StartsWith("//")) { u.AppendLine(); continue; }
                if (UsingDirective.IsMatch(t)) { u.AppendLine(lines[i]); continue; }
                break;
            }
            // Conservamos la numeración: las líneas movidas siguen contando.
            return (u.ToString(), string.Join("\n", lines.Skip(i)));
        }

        public static string Wrap(string userCode, out int bodyStartLine)
        {
            var (usings, body) = SplitUsings(userCode);
            int usingLines = usings.Split('\n').Length - 1;
            bodyStartLine = usingLines + 1;
            return DefaultUsings + "#line 1 \"script.cs\"\n" + usings + "#line default\n" +
@"namespace Civil3DAgentScript {
public static class Script {
  public static object Run(Document doc, Database db, Editor ed, CivilDocument civ, Transaction tr) {
#line " + bodyStartLine + @" ""script.cs""
" + body + @"
#line default
#pragma warning disable CS0162
    return null;
#pragma warning restore CS0162
  }
}}";
        }

        public static JsonObject Run(string code, bool modify, string label)
        {
            var sw = Stopwatch.StartNew();
            string mode = modify ? "modify" : "query";
            string stamp = DateTime.Now.ToString("yyyyMMdd-HHmmss-fff");
            string runBase = Path.Combine(Paths.RunsDir, $"{stamp}_{mode}");
            var res = new JsonObject { ["mode"] = mode };
            string consoleText = "";
            try
            {
                File.WriteAllText(runBase + ".cs", (label != null ? "// " + label + "\n" : "") + code);

                var doc = AcApp.DocumentManager.MdiActiveDocument;
                if (doc == null) return Finish(BridgeServer.Err("No hay ningún documento activo."), runBase, sw);
                if (!string.IsNullOrEmpty(Convert.ToString(AcApp.GetSystemVariable("CMDNAMES"))))
                    return Finish(BridgeServer.Err("Hay un comando en curso en Civil 3D (" + AcApp.GetSystemVariable("CMDNAMES") +
                                                   "). Termínalo o pulsa Esc y vuelve a intentarlo.", "busy"), runBase, sw);

                // 1) Compilar
                string src = Wrap(code, out _);
                var tree = CSharpSyntaxTree.ParseText(src, new CSharpParseOptions(LanguageVersion.Latest));
                var comp = CSharpCompilation.Create("C3DScript_" + Guid.NewGuid().ToString("N"), new[] { tree }, References,
                    new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary, optimizationLevel: OptimizationLevel.Debug,
                                                 allowUnsafe: false, platform: Platform.X64));
                using var pe = new MemoryStream();
                var emit = comp.Emit(pe);
                var diags = new JsonArray();
                foreach (var d in emit.Diagnostics.Where(d => d.Severity >= DiagnosticSeverity.Warning))
                {
                    var span = d.Location.GetMappedLineSpan();
                    bool inScript = span.Path == "script.cs";
                    diags.Add(new JsonObject
                    {
                        ["severity"] = d.Severity.ToString().ToLowerInvariant(),
                        ["id"] = d.Id,
                        ["line"] = inScript ? span.StartLinePosition.Line + 1 : (int?)null,
                        ["column"] = inScript ? span.StartLinePosition.Character + 1 : (int?)null,
                        ["message"] = d.GetMessage(System.Globalization.CultureInfo.GetCultureInfo("es-ES"))
                    });
                }
                res["diagnostics"] = diags;
                if (!emit.Success)
                {
                    res["ok"] = false; res["code"] = "compile_error";
                    res["error"] = "Error de compilación (las líneas se cuentan desde la primera línea del script).";
                    return Finish(res, runBase, sw);
                }

                // 2) Cargar en un contexto descartable
                var alc = new AssemblyLoadContext("C3DScript", isCollectible: true);
                object ret = null;
                var oldOut = Console.Out; var oldErr = Console.Error;
                var console = new StringWriter();
                try
                {
                    pe.Position = 0;
                    var asm = alc.LoadFromStream(pe);
                    var run = asm.GetType("Civil3DAgentScript.Script").GetMethod("Run");

                    // 3) Ejecutar: documento bloqueado + transacción
                    Console.SetOut(console); Console.SetError(console);
                    var db = doc.Database; var ed = doc.Editor;
                    CivilDocument civ = null;
                    try { civ = CivilApplication.ActiveDocument; } catch { /* AutoCAD sin Civil */ }
                    using (doc.LockDocument())
                    using (var tr = db.TransactionManager.StartTransaction())
                    {
                        try
                        {
                            ret = run.Invoke(null, new object[] { doc, db, ed, civ, tr });
                            // Serializar ANTES de cerrar la transacción: los objetos abiertos dejan de ser válidos después.
                            res["result"] = ToJson(ret);
                            if (modify) { tr.Commit(); res["committed"] = true; }
                            else { tr.Abort(); res["committed"] = false; }
                        }
                        catch
                        {
                            try { tr.Abort(); } catch { }
                            res["committed"] = false;
                            throw;
                        }
                    }
                    if (modify) { try { ed.Regen(); } catch { } }
                    res["ok"] = true;
                }
                catch (TargetInvocationException tie) when (tie.InnerException != null)
                {
                    res["ok"] = false; res["code"] = "runtime_error";
                    res["error"] = tie.InnerException.GetType().FullName + ": " + tie.InnerException.Message;
                    res["stack"] = ScriptStack(tie.InnerException);
                }
                finally
                {
                    Console.SetOut(oldOut); Console.SetError(oldErr);
                    consoleText = console.ToString();
                    ret = null;
                    alc.Unload();
                }
            }
            catch (System.Exception ex)
            {
                res["ok"] = false; if (res["code"] == null) res["code"] = "exception";
                res["error"] = ex.GetType().FullName + ": " + ex.Message;
            }
            res["console"] = Truncate(consoleText, 200_000);
            return Finish(res, runBase, sw);
        }

        static JsonObject Finish(JsonObject res, string runBase, Stopwatch sw)
        {
            res["elapsed_ms"] = sw.ElapsedMilliseconds;
            res["audit_file"] = runBase + ".json";
            try { File.WriteAllText(runBase + ".json", res.ToJsonString(new JsonSerializerOptions { WriteIndented = true })); } catch { }
            return res;
        }

        static string ScriptStack(System.Exception ex)
        {
            // Solo las líneas que apuntan al script, que son las útiles.
            var st = ex.StackTrace ?? "";
            var lines = st.Split('\n').Where(l => l.Contains("script.cs") || l.Contains("Civil3DAgentScript")).Select(l => l.Trim());
            var s = string.Join("\n", lines);
            return s.Length > 0 ? s : Truncate(st, 4000);
        }

        static string Truncate(string s, int max) => s == null || s.Length <= max ? s : s.Substring(0, max) + $"\n...[recortado, {s.Length - max} caracteres más]";

        static readonly JsonSerializerOptions _jsonOpts = new JsonSerializerOptions
        {
            ReferenceHandler = ReferenceHandler.IgnoreCycles,
            MaxDepth = 16,
            WriteIndented = false,
            NumberHandling = JsonNumberHandling.AllowNamedFloatingPointLiterals,
            Converters = { new JsonStringEnumConverter(), new AcadObjectConverterFactory() }
        };

        /// <summary>ObjectId, Handle y objetos de AutoCAD (DBObject, Database, Document...) se escriben como texto,
        /// para no recorrer grafos enormes ni tocar objetos ya cerrados.</summary>
        sealed class AcadObjectConverterFactory : JsonConverterFactory
        {
            public override bool CanConvert(Type t) =>
                t == typeof(ObjectId) || t == typeof(Handle) ||
                typeof(Autodesk.AutoCAD.Runtime.DisposableWrapper).IsAssignableFrom(t) ||
                typeof(Document).IsAssignableFrom(t);
            public override JsonConverter CreateConverter(Type t, JsonSerializerOptions o) =>
                (JsonConverter)Activator.CreateInstance(typeof(ToStringConverter<>).MakeGenericType(t));
        }

        sealed class ToStringConverter<T> : JsonConverter<T>
        {
            public override T Read(ref Utf8JsonReader r, Type t, JsonSerializerOptions o) => throw new NotSupportedException();
            public override void Write(Utf8JsonWriter w, T v, JsonSerializerOptions o)
            {
                switch (v)
                {
                    case null: w.WriteNullValue(); break;
                    case ObjectId id: w.WriteStringValue(id.IsNull ? "(null)" : $"{id.ObjectClass?.DxfName}:{id.Handle}"); break;
                    case Handle h: w.WriteStringValue(h.ToString()); break;
                    default:
                        string name = null;
                        try { name = v.GetType().GetProperty("Name")?.GetValue(v) as string; } catch { }
                        w.WriteStringValue(v.GetType().Name + (name != null ? " «" + name + "»" : "")); break;
                }
            }
        }

        /// <summary>Convierte el valor devuelto a JSON. Texto tal cual; objetos de AutoCAD como texto.</summary>
        public static JsonNode ToJson(object v)
        {
            if (v == null) return null;
            if (v is string s) return JsonValue.Create(s);
            if (v is JsonNode n) return n;
            if (v is ObjectId oid) return JsonValue.Create(oid.ToString());
            if (v is DBObject || v is Document || v is Database) return JsonValue.Create(v.GetType().FullName + " (no serializable; devuelve propiedades concretas)");
            try { return JsonNode.Parse(JsonSerializer.Serialize(v, v.GetType(), _jsonOpts)); }
            catch (System.Exception ex) { return JsonValue.Create(v.ToString() + "  [no serializable como JSON: " + ex.Message + "]"); }
        }
    }
}
