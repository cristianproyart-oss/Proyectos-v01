// Civil3DAgent - puente local entre Claude Code (MCP) y Civil 3D 2026.
// Punto de entrada del add-in: arranca el servidor TCP al cargar y lo detiene al cerrar.
using System;
using System.IO;
using System.Text.Json;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.Runtime;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;

[assembly: ExtensionApplication(typeof(Civil3DAgent.AgentApp))]
[assembly: CommandClass(typeof(Civil3DAgent.AgentCommands))]

namespace Civil3DAgent
{
    public static class Paths
    {
        public static readonly string Root = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Civil3DAgent");
        public static readonly string SessionFile = Path.Combine(Root, "session.json");
        public static readonly string RunsDir = Path.Combine(Root, "runs");
        public static readonly string LogFile = Path.Combine(Root, "agent.log");

        public static void Ensure()
        {
            Directory.CreateDirectory(Root);
            Directory.CreateDirectory(RunsDir);
        }

        public static void Log(string msg)
        {
            try { File.AppendAllText(LogFile, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff} [{Environment.ProcessId}] {msg}{Environment.NewLine}"); }
            catch { /* el log nunca debe tumbar Civil 3D */ }
        }
    }

    public class AgentApp : IExtensionApplication
    {
        internal static BridgeServer Server;

        public void Initialize()
        {
            try
            {
                Paths.Ensure();
                // El despachador se crea aquí porque Initialize corre en el hilo principal de AutoCAD.
                MainThread.Init();
                Server = new BridgeServer();
                Server.Start();
                WriteSession();
                Paths.Log($"Iniciado en 127.0.0.1:{Server.Port}");
                Say($"\nCivil3DAgent: puente MCP escuchando en 127.0.0.1:{Server.Port}\n");
            }
            catch (System.Exception ex)
            {
                Paths.Log("Error al iniciar: " + ex);
                Say("\nCivil3DAgent: no se pudo iniciar el puente: " + ex.Message + "\n");
            }
        }

        public void Terminate()
        {
            try
            {
                Server?.Stop();
                // Solo borra session.json si es el nuestro (puede haber otra instancia de Civil 3D).
                if (File.Exists(Paths.SessionFile))
                {
                    using var d = JsonDocument.Parse(File.ReadAllText(Paths.SessionFile));
                    if (d.RootElement.TryGetProperty("pid", out var p) && p.GetInt32() == Environment.ProcessId)
                        File.Delete(Paths.SessionFile);
                }
                var mine = Path.Combine(Paths.Root, $"session-{Environment.ProcessId}.json");
                if (File.Exists(mine)) File.Delete(mine);
            }
            catch { }
        }

        static void WriteSession()
        {
            var info = new
            {
                port = Server.Port,
                token = Server.Token,
                pid = Environment.ProcessId,
                started = DateTime.Now.ToString("o"),
                acadver = SafeSysVar("ACADVER"),
                product = SafeSysVar("PRODUCT"),
                addin_version = typeof(AgentApp).Assembly.GetName().Version?.ToString()
            };
            var json = JsonSerializer.Serialize(info, new JsonSerializerOptions { WriteIndented = true });
            // session.json = la última instancia abierta; session-<pid>.json = una por instancia.
            File.WriteAllText(Paths.SessionFile, json);
            File.WriteAllText(Path.Combine(Paths.Root, $"session-{Environment.ProcessId}.json"), json);
        }

        internal static string SafeSysVar(string name)
        {
            try { return Convert.ToString(AcApp.GetSystemVariable(name)); } catch { return null; }
        }

        internal static void Say(string msg)
        {
            try { AcApp.DocumentManager.MdiActiveDocument?.Editor.WriteMessage(msg); } catch { }
        }
    }

    public class AgentCommands
    {
        [CommandMethod("C3DAGENT_STATUS", CommandFlags.Session)]
        public void Status()
        {
            var ed = AcApp.DocumentManager.MdiActiveDocument?.Editor;
            if (ed == null) return;
            if (AgentApp.Server == null) { ed.WriteMessage("\nCivil3DAgent: el puente no está activo. Revisa " + Paths.LogFile + "\n"); return; }
            ed.WriteMessage($"\nCivil3DAgent activo en 127.0.0.1:{AgentApp.Server.Port}. Peticiones atendidas: {AgentApp.Server.RequestCount}." +
                            $"\nSesión: {Paths.SessionFile}\nAuditoría: {Paths.RunsDir}\n");
        }
    }
}
