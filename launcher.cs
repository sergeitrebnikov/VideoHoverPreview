using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

static class Program
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int MessageBox(IntPtr hWnd, string text, string caption, uint type);

    [STAThread]
    static void Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/');
        string pyw = Path.Combine(root, "runtime", "python", "tools", "pythonw.exe");
        string script = Path.Combine(root, "launch.py");
        if (!File.Exists(pyw) || !File.Exists(script))
        {
            MessageBox(
                IntPtr.Zero,
                "Не найден portable runtime.\nСкопируйте папку программы целиком, вместе с runtime\\.",
                "Video Hover Preview",
                0x30);
            return;
        }

        var psi = new ProcessStartInfo
        {
            FileName = pyw,
            Arguments = "\"" + script + "\"",
            WorkingDirectory = root,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        string ffbin = Path.Combine(root, "runtime", "ffmpeg", "bin");
        if (Directory.Exists(ffbin))
        {
            string path = Environment.GetEnvironmentVariable("PATH") ?? "";
            psi.EnvironmentVariables["PATH"] = ffbin + ";" + path;
        }
        Process.Start(psi);
    }
}
