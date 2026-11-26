// Captura PNG de la vista actual.
//  - "preview": Document.CapturePreviewImage(ancho, alto) -> render de la vista activa (sin la interfaz).
//  - "screen":  copia de pantalla de la ventana del dibujo (lo que se ve, incluidas ventanas encima).
//  - "auto":    preview y, si falla, screen.
// Se llama por reflexión para que el add-in compile aunque cambie la firma entre versiones.
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;

namespace Civil3DAgent
{
    public static class ViewCapture
    {
        [StructLayout(LayoutKind.Sequential)] struct RECT { public int Left, Top, Right, Bottom; }
        [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
        [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);

        public static JsonObject Capture(int width, int height, string method)
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument;
            if (doc == null) return BridgeServer.Err("No hay documento activo.");
            width = Math.Clamp(width, 64, 8000); height = Math.Clamp(height, 64, 8000);
            Bitmap bmp = null; string used = null; string err = "";

            if (method == "auto" || method == "preview")
            {
                try
                {
                    var mi = doc.GetType().GetMethod("CapturePreviewImage", new[] { typeof(uint), typeof(uint) });
                    if (mi == null) throw new MissingMethodException("Document.CapturePreviewImage(uint,uint) no existe en esta versión.");
                    bmp = mi.Invoke(doc, new object[] { (uint)width, (uint)height }) as Bitmap;
                    if (bmp != null) used = "preview";
                }
                catch (System.Exception ex) { err += "preview: " + (ex.InnerException ?? ex).Message + "; "; }
            }
            if (bmp == null && (method == "auto" || method == "screen"))
            {
                try
                {
                    var winObj = doc.GetType().GetProperty("Window")?.GetValue(doc);
                    var hwnd = (IntPtr)(winObj?.GetType().GetProperty("Handle")?.GetValue(winObj) ?? IntPtr.Zero);
                    if (hwnd == IntPtr.Zero) hwnd = Autodesk.AutoCAD.ApplicationServices.Application.MainWindow.Handle;
                    GetWindowRect(hwnd, out var r);
                    int w = r.Right - r.Left, h = r.Bottom - r.Top;
                    if (w <= 0 || h <= 0) throw new InvalidOperationException("La ventana del dibujo no es visible (¿minimizada?).");
                    bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb);
                    using (var g = Graphics.FromImage(bmp))
                    {
                        var hdc = g.GetHdc();
                        bool ok = PrintWindow(hwnd, hdc, 2 /* PW_RENDERFULLCONTENT */);
                        g.ReleaseHdc(hdc);
                        if (!ok) g.CopyFromScreen(r.Left, r.Top, 0, 0, new Size(w, h));
                    }
                    used = "screen";
                }
                catch (System.Exception ex) { err += "screen: " + ex.Message; bmp?.Dispose(); bmp = null; }
            }
            if (bmp == null) return BridgeServer.Err("No se pudo capturar la vista. " + err);

            using (bmp)
            using (var ms = new MemoryStream())
            {
                bmp.Save(ms, ImageFormat.Png);
                var bytes = ms.ToArray();
                var file = Path.Combine(Paths.RunsDir, $"{DateTime.Now:yyyyMMdd-HHmmss-fff}_capture.png");
                try { File.WriteAllBytes(file, bytes); } catch { }
                return new JsonObject
                {
                    ["ok"] = true, ["method"] = used, ["width"] = bmp.Width, ["height"] = bmp.Height,
                    ["file"] = file, ["png_base64"] = Convert.ToBase64String(bytes),
                    ["document"] = doc.Name
                };
            }
        }
    }
}
