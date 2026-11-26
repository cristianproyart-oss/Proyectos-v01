// Despachador al hilo principal de AutoCAD.
// La API de AutoCAD/Civil 3D solo es segura en el hilo de la aplicación. El servidor TCP
// recibe en un hilo de fondo y usa este despachador (un Control oculto de WinForms creado
// en Initialize, que corre en el hilo principal) para ejecutar cada petición allí.
using System;
using System.Threading;
using System.Windows.Forms;

namespace Civil3DAgent
{
    internal static class MainThread
    {
        static Control _ctl;
        static int _mainThreadId;

        public static void Init()
        {
            _mainThreadId = Environment.CurrentManagedThreadId;
            _ctl = new Control();
            _ = _ctl.Handle; // fuerza la creación del HWND en este hilo
        }

        public static T Invoke<T>(Func<T> f, TimeSpan timeout)
        {
            if (Environment.CurrentManagedThreadId == _mainThreadId) return f();
            T result = default;
            System.Exception error = null;
            var done = new ManualResetEventSlim(false);
            int state = 0; // 0 = pendiente, 1 = en ejecución, 2 = cancelada por tiempo
            _ctl.BeginInvoke((Action)(() =>
            {
                if (Interlocked.CompareExchange(ref state, 1, 0) != 0) { done.Set(); return; }
                try { result = f(); }
                catch (System.Exception ex) { error = ex; }
                finally { done.Set(); }
            }));
            if (!done.Wait(timeout))
            {
                if (Interlocked.CompareExchange(ref state, 2, 0) == 0)
                    throw new TimeoutException(
                        "Civil 3D no atendió la petición a tiempo (¿hay un cuadro de diálogo abierto o un comando esperando entrada?). " +
                        "La petición se canceló y NO se ejecutó.");
                // Ya empezó a ejecutarse: hay que esperar a que termine (no se puede abortar a medias).
                done.Wait();
            }
            if (error != null) throw new AggregateException(error.Message, error);
            return result;
        }
    }
}
