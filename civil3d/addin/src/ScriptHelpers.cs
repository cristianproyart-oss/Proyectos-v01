// Utilidades disponibles dentro de los scripts (se importan con "using static", así que T(...) y Props(...) se usan directamente).
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace Civil3DAgent
{
    public static class ScriptHelpers
    {
        /// <summary>Evalúa f y, si lanza excepción, devuelve "!Tipo: mensaje" en vez de abortar el script.</summary>
        public static object T<TR>(Func<TR> f)
        {
            try { return f(); }
            catch (Exception ex) { return "!" + ex.GetType().Name + ": " + ex.Message; }
        }

        /// <summary>Valor de una propiedad por reflexión (null si no existe). Útil cuando no estás seguro de la API.</summary>
        public static object Get(object o, string prop) => o?.GetType().GetProperty(prop)?.GetValue(o);

        /// <summary>Elementos de cualquier colección no genérica como lista.</summary>
        public static List<object> Items(object coll) =>
            coll is System.Collections.IEnumerable e && !(coll is string) ? e.Cast<object>().ToList() : new List<object>();

        /// <summary>Lee por reflexión las propiedades públicas simples (números, texto, enums, bool) de un objeto.
        /// Útil para explorar objetos de la API sin conocer sus propiedades.</summary>
        public static Dictionary<string, object> Props(object o, params string[] only)
        {
            var d = new Dictionary<string, object>();
            if (o == null) return d;
            foreach (var p in o.GetType().GetProperties(BindingFlags.Public | BindingFlags.Instance))
            {
                if (p.GetIndexParameters().Length > 0) continue;
                if (only.Length > 0 && !only.Contains(p.Name)) continue;
                var t = Nullable.GetUnderlyingType(p.PropertyType) ?? p.PropertyType;
                if (!(t.IsPrimitive || t.IsEnum || t == typeof(string) || t == typeof(decimal) || t == typeof(DateTime))) continue;
                try { var v = p.GetValue(o); d[p.Name] = t.IsEnum ? v?.ToString() : v; }
                catch (Exception ex) { d[p.Name] = "!" + (ex.InnerException ?? ex).Message; }
            }
            return d;
        }
    }
}
