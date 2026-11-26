// Servidor TCP local (solo 127.0.0.1) con token por sesión.
// Protocolo: una línea JSON por petición y una línea JSON por respuesta (UTF-8).
//   petición:  {"token":"...","op":"ping|query|modify|lookup|capture|refs", ...}
//   respuesta: {"ok":true|false, ...}
using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;

namespace Civil3DAgent
{
    public class BridgeServer
    {
        public const int PortMin = 8791, PortMax = 8799;
        const int MaxRequestBytes = 16 * 1024 * 1024;

        TcpListener _listener;
        CancellationTokenSource _cts;
        public int Port { get; private set; }
        public string Token { get; } = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
        public int RequestCount;
        // Una sola ejecución a la vez: el hilo principal es uno solo.
        readonly SemaphoreSlim _gate = new SemaphoreSlim(1, 1);

        public void Start()
        {
            for (int p = PortMin; p <= PortMax; p++)
            {
                try
                {
                    var l = new TcpListener(IPAddress.Loopback, p);
                    l.ExclusiveAddressUse = true;
                    l.Start();
                    _listener = l; Port = p; break;
                }
                catch (SocketException) { /* puerto ocupado: probar el siguiente */ }
            }
            if (_listener == null) throw new InvalidOperationException($"No hay puertos libres entre {PortMin} y {PortMax}.");
            _cts = new CancellationTokenSource();
            Task.Run(() => AcceptLoop(_cts.Token));
        }

        public void Stop()
        {
            try { _cts?.Cancel(); _listener?.Stop(); } catch { }
        }

        async Task AcceptLoop(CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                TcpClient c;
                try { c = await _listener.AcceptTcpClientAsync(ct); }
                catch { if (ct.IsCancellationRequested) return; continue; }
                _ = Task.Run(() => Handle(c, ct));
            }
        }

        async Task Handle(TcpClient client, CancellationToken ct)
        {
            using (client)
            {
                try
                {
                    // Defensa extra: solo conexiones desde loopback.
                    if (client.Client.RemoteEndPoint is IPEndPoint ep && !IPAddress.IsLoopback(ep.Address)) return;
                    client.ReceiveTimeout = 30000;
                    var stream = client.GetStream();
                    var line = await ReadLine(stream, ct);
                    if (line == null) return;
                    var resp = await Process(line);
                    var bytes = Encoding.UTF8.GetBytes(resp.ToJsonString() + "\n");
                    await stream.WriteAsync(bytes, ct);
                    await stream.FlushAsync(ct);
                }
                catch (System.Exception ex) { Paths.Log("Error de conexión: " + ex.Message); }
            }
        }

        static async Task<string> ReadLine(NetworkStream s, CancellationToken ct)
        {
            var ms = new MemoryStream();
            var buf = new byte[65536];
            while (true)
            {
                int n = await s.ReadAsync(buf, ct);
                if (n <= 0) break;
                int nl = Array.IndexOf(buf, (byte)'\n', 0, n);
                if (nl >= 0) { ms.Write(buf, 0, nl); break; }
                ms.Write(buf, 0, n);
                if (ms.Length > MaxRequestBytes) throw new InvalidDataException("Petición demasiado grande.");
            }
            return ms.Length == 0 ? null : Encoding.UTF8.GetString(ms.ToArray());
        }

        bool TokenOk(string t)
        {
            if (string.IsNullOrEmpty(t)) return false;
            var a = Encoding.UTF8.GetBytes(t); var b = Encoding.UTF8.GetBytes(Token);
            return a.Length == b.Length && CryptographicOperations.FixedTimeEquals(a, b);
        }

        async Task<JsonObject> Process(string line)
        {
            JsonObject req;
            try { req = JsonNode.Parse(line)?.AsObject(); }
            catch (System.Exception ex) { return Err("JSON inválido: " + ex.Message); }
            if (req == null) return Err("Petición vacía.");
            if (!TokenOk((string)req["token"])) { Paths.Log("Petición rechazada: token inválido."); return Err("Token inválido o ausente.", "unauthorized"); }

            string op = (string)req["op"] ?? "";
            Interlocked.Increment(ref RequestCount);
            if (op == "ping") return new JsonObject { ["ok"] = true, ["pong"] = true, ["pid"] = Environment.ProcessId, ["port"] = Port };

            int timeoutSec = (int?)req["timeout_sec"] ?? 120;
            if (!await _gate.WaitAsync(TimeSpan.FromSeconds(timeoutSec)))
                return Err("El puente está ocupado con otra petición.", "busy");
            try
            {
                return MainThread.Invoke(() => Dispatch(op, req), TimeSpan.FromSeconds(timeoutSec));
            }
            catch (System.Exception ex)
            {
                var inner = ex is AggregateException ae && ae.InnerException != null ? ae.InnerException : ex;
                return Err(inner.GetType().Name + ": " + inner.Message, ex is TimeoutException ? "timeout" : "exception");
            }
            finally { _gate.Release(); }
        }

        // Corre en el hilo principal de AutoCAD.
        static JsonObject Dispatch(string op, JsonObject req)
        {
            switch (op)
            {
                case "query": return ScriptRunner.Run((string)req["code"] ?? "", modify: false, (string)req["label"]);
                case "modify": return ScriptRunner.Run((string)req["code"] ?? "", modify: true, (string)req["label"]);
                case "lookup": return ApiLookup.Search((string)req["query"] ?? "", (int?)req["max"] ?? 60, (bool?)req["members"] ?? true);
                case "capture": return ViewCapture.Capture((int?)req["width"] ?? 1600, (int?)req["height"] ?? 1000, (string)req["method"] ?? "auto");
                case "refs":
                    {
                        // Diagnóstico: qué DLL se usan como referencias para compilar scripts.
                        var list = ScriptRunner.BuildReferences(out var report);
                        var arr = new JsonArray(); foreach (var r in list) arr.Add(r.Display);
                        var rep = new JsonArray(); foreach (var r in report) rep.Add(r);
                        return new JsonObject { ["ok"] = true, ["references"] = arr, ["skipped"] = rep };
                    }
                default: return Err("Operación desconocida: " + op);
            }
        }

        internal static JsonObject Err(string msg, string code = "error") =>
            new JsonObject { ["ok"] = false, ["error"] = msg, ["code"] = code };
    }
}
