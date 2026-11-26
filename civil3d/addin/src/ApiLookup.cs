// Búsqueda por reflexión en las DLL de AutoCAD y Civil 3D cargadas en el proceso,
// para consultar tipos, miembros y firmas reales en vez de suponerlos.
// Consultas aceptadas:
//   "Alignment"                       -> tipos cuyo nombre contiene el texto
//   "Alignment.GetProfileIds"         -> miembros de ese tipo que contienen el texto
//   "Autodesk.Civil.DatabaseServices.Subassembly" -> tipo exacto con todos sus miembros
//   ".ImportSACSubassembly"           -> busca ese miembro en todos los tipos
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.DatabaseServices;

namespace Civil3DAgent
{
    public static class ApiLookup
    {
        static readonly string[] Prefixes = { "acdbmgd", "acmgd", "accoremgd", "aecc", "aec", "acwindows", "adwindows" };

        static IEnumerable<Assembly> TargetAssemblies()
        {
            string acad = Path.GetDirectoryName(typeof(Database).Assembly.Location) ?? "";
            // Asegura que las DLL principales de Civil estén cargadas aunque no se hayan usado aún.
            foreach (var rel in new[] { @"C3D\AeccDbMgd.dll", @"ACA\AecBaseMgd.dll", @"C3D\AeccPressurePipesMgd.dll" })
            {
                var f = Path.Combine(acad, rel);
                if (File.Exists(f)) { try { Assembly.LoadFrom(f); } catch { } }
            }
            return AppDomain.CurrentDomain.GetAssemblies().Where(a =>
            {
                if (a.IsDynamic) return false;
                var n = (a.GetName().Name ?? "").ToLowerInvariant();
                return Prefixes.Any(p => n.StartsWith(p));
            });
        }

        static IEnumerable<Type> SafeTypes(Assembly a)
        {
            try { return a.GetExportedTypes(); }
            catch (ReflectionTypeLoadException e) { return e.Types.Where(t => t != null && t.IsPublic); }
            catch { return Enumerable.Empty<Type>(); }
        }

        public static JsonObject Search(string query, int max, bool includeMembers)
        {
            query = (query ?? "").Trim();
            if (query.Length == 0) return BridgeServer.Err("Indica un texto a buscar.");
            var types = TargetAssemblies().SelectMany(SafeTypes).ToList();
            var outTypes = new JsonArray();
            int count = 0;

            string typePart = query, memberPart = null;
            var exact = types.FirstOrDefault(t => t.FullName == query);
            if (exact == null)
            {
                int dot = query.LastIndexOf('.');
                if (dot >= 0) { typePart = query.Substring(0, dot); memberPart = query.Substring(dot + 1); }
            }

            IEnumerable<Type> candidates;
            if (exact != null) candidates = new[] { exact };
            else if (typePart.Length == 0) candidates = types; // ".Miembro": buscar en todos
            else
            {
                var byExact = types.Where(t => t.Name.Equals(typePart, StringComparison.OrdinalIgnoreCase) || t.FullName == typePart).ToList();
                candidates = byExact.Count > 0 && memberPart != null ? byExact
                    : types.Where(t => (t.FullName ?? t.Name).IndexOf(typePart, StringComparison.OrdinalIgnoreCase) >= 0)
                           .OrderBy(t => t.Name.Length);
            }

            foreach (var t in candidates)
            {
                if (count >= max) break;
                var jt = new JsonObject
                {
                    ["type"] = t.FullName,
                    ["kind"] = t.IsEnum ? "enum" : t.IsInterface ? "interface" : t.IsValueType ? "struct" : "class",
                    ["assembly"] = t.Assembly.GetName().Name,
                    ["base"] = t.BaseType?.FullName
                };
                var members = new JsonArray();
                bool wantMembers = includeMembers && (exact != null || memberPart != null || candidates is IList<Type> l && l.Count == 1);
                if (t.IsEnum)
                {
                    if (includeMembers) foreach (var n in Enum.GetNames(t)) members.Add(n);
                }
                else if (wantMembers)
                {
                    foreach (var m in t.GetMembers(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static | BindingFlags.FlattenHierarchy)
                                       .Where(m => !(m is MethodInfo mi && mi.IsSpecialName))
                                       .Where(m => memberPart == null || m.Name.IndexOf(memberPart, StringComparison.OrdinalIgnoreCase) >= 0)
                                       .OrderBy(m => m.MemberType.ToString()).ThenBy(m => m.Name))
                    {
                        var sig = Signature(m);
                        if (sig != null) members.Add(sig);
                    }
                    if (memberPart != null && members.Count == 0) continue;
                }
                if (members.Count > 0) jt["members"] = members;
                outTypes.Add(jt); count++;
            }
            return new JsonObject
            {
                ["ok"] = true,
                ["query"] = query,
                ["count"] = count,
                ["truncated"] = count >= max,
                ["types"] = outTypes,
                ["hint"] = count == 0 ? "Sin resultados. Prueba con parte del nombre (p. ej. 'Subassembly'), o '.Miembro' para buscar un miembro en todos los tipos." : null
            };
        }

        static string Signature(MemberInfo m)
        {
            try
            {
                switch (m)
                {
                    case PropertyInfo p:
                        var acc = (p.CanRead ? "get; " : "") + (p.CanWrite && p.SetMethod?.IsPublic == true ? "set; " : "");
                        var idx = p.GetIndexParameters();
                        var ip = idx.Length > 0 ? "[" + string.Join(", ", idx.Select(Param)) + "]" : "";
                        return $"{(IsStatic(p.GetMethod) ? "static " : "")}property {TypeName(p.PropertyType)} {p.Name}{ip} {{ {acc}}}";
                    case MethodInfo mi:
                        var g = mi.IsGenericMethod ? "<" + string.Join(", ", mi.GetGenericArguments().Select(TypeName)) + ">" : "";
                        return $"{(mi.IsStatic ? "static " : "")}method {TypeName(mi.ReturnType)} {mi.Name}{g}({string.Join(", ", mi.GetParameters().Select(Param))})";
                    case ConstructorInfo c:
                        return $"ctor {c.DeclaringType?.Name}({string.Join(", ", c.GetParameters().Select(Param))})";
                    case FieldInfo f:
                        return $"{(f.IsStatic ? "static " : "")}field {TypeName(f.FieldType)} {f.Name}";
                    case EventInfo e:
                        return $"event {TypeName(e.EventHandlerType)} {e.Name}";
                    default: return null;
                }
            }
            catch (System.Exception ex) { return m.Name + " [error de reflexión: " + ex.Message + "]"; }
        }

        static bool IsStatic(MethodInfo m) => m != null && m.IsStatic;

        static string Param(ParameterInfo p)
        {
            var t = p.ParameterType; string mod = "";
            if (t.IsByRef) { t = t.GetElementType(); mod = p.IsOut ? "out " : "ref "; }
            var def = p.HasDefaultValue ? " = " + (p.DefaultValue ?? "null") : "";
            return mod + TypeName(t) + " " + p.Name + def;
        }

        public static string TypeName(Type t)
        {
            if (t == null) return "?";
            if (t == typeof(void)) return "void";
            if (t.IsArray) return TypeName(t.GetElementType()) + "[]";
            if (t.IsGenericType)
            {
                var n = t.Name; int q = n.IndexOf('`'); if (q > 0) n = n.Substring(0, q);
                return n + "<" + string.Join(", ", t.GetGenericArguments().Select(TypeName)) + ">";
            }
            return t.Namespace == "System" ? t.Name : (t.FullName ?? t.Name);
        }
    }
}
