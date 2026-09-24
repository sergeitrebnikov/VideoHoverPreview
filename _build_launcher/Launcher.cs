// Лаунчер VideoHoverPreview: держит процесс в диспетчере задач и гасит
// python/ffmpeg при закрытии через Job Object (KILL_ON_JOB_CLOSE).
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;

internal static class Program
{
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    private const uint JobObjectExtendedLimitInformation = 9;

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(
        IntPtr hJob, uint JobObjectInfoClass, IntPtr lpJobObjectInfo, uint cbJobObjectInfoLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr hObject);

    [STAThread]
    private static int Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(
            Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        string tools = Path.Combine(root, "runtime", "python", "tools");
        string launchPy = Path.Combine(root, "launch.py");
        string host = Path.Combine(tools, "vhpreview-host.exe");
        string pyw = Path.Combine(tools, "pythonw.exe");
        string py = Path.Combine(tools, "python.exe");

        // Копия pythonw под своим именем — меньше путаницы с «Python» в диспетчере.
        if (File.Exists(pyw))
        {
            try
            {
                if (!File.Exists(host) || new FileInfo(host).Length != new FileInfo(pyw).Length)
                    File.Copy(pyw, host, true);
            }
            catch
            {
                host = pyw;
            }
        }
        else if (File.Exists(py))
        {
            host = py;
        }
        else
        {
            MessageBox.Show(
                "Не найден runtime\\python\\tools\\pythonw.exe.\r\n" +
                "Скопируйте папку программы целиком, вместе с runtime\\.",
                "Video Hover Preview",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning);
            return 1;
        }

        if (!File.Exists(launchPy))
        {
            MessageBox.Show(
                "Не найден launch.py рядом с VideoHoverPreview.exe.",
                "Video Hover Preview",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning);
            return 1;
        }

        string ffbin = Path.Combine(root, "runtime", "ffmpeg", "bin");
        var psi = new ProcessStartInfo
        {
            FileName = host,
            Arguments = "\"" + launchPy + "\"",
            WorkingDirectory = root,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        if (Directory.Exists(ffbin))
        {
            string path = Environment.GetEnvironmentVariable("PATH") ?? "";
            psi.EnvironmentVariables["PATH"] = ffbin + ";" + path;
        }

        Process child;
        try
        {
            child = Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "Не удалось запустить runtime:\r\n" + ex.Message,
                "Video Hover Preview",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 1;
        }
        if (child == null)
            return 1;

        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job != IntPtr.Zero)
        {
            var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            int length = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
            IntPtr ptr = Marshal.AllocHGlobal(length);
            try
            {
                Marshal.StructureToPtr(info, ptr, false);
                if (SetInformationJobObject(job, JobObjectExtendedLimitInformation, ptr, (uint)length))
                    AssignProcessToJobObject(job, child.Handle);
            }
            finally
            {
                Marshal.FreeHGlobal(ptr);
            }
        }

        try
        {
            child.WaitForExit();
            return child.ExitCode;
        }
        finally
        {
            if (job != IntPtr.Zero)
                CloseHandle(job);
            try { child.Dispose(); } catch { }
        }
    }
}
