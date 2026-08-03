using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Reflection;
using System.Threading;

[assembly: AssemblyTitle("Tiance Updater")]
[assembly: AssemblyProduct("Tiance")]
[assembly: AssemblyCompany("Tiance")]
[assembly: AssemblyVersion("0.3.9.0")]
[assembly: AssemblyFileVersion("0.3.9.0")]

internal static class TianceUpdater
{
    private static readonly string[] ReplacementPaths = new string[]
    {
        "Tiance.exe",
        "TianceUpdater.exe",
        "version.json",
        "LICENSE",
        "README.md",
        "1_PythonServer",
        "2_ReactWeb",
        "3_PyWebView",
        "assets",
        "docs",
        "runtime",
        // Legacy clients require the runtime payload under Data/runtime. Newer updaters
        // install that bridge payload into the root runtime directory instead.
        Path.Combine("Data", "runtime"),
    };

    [STAThread]
    private static int Main(string[] args)
    {
        string logPath = BuildLogPath();
        try
        {
            Dictionary<string, string> options = ParseOptions(args);
            string installRoot = RequireDirectory(options, "install-root");
            string stageRoot = RequireDirectory(options, "stage-root");
            int parentPid = ParsePositiveInt(options, "parent-pid");
            ValidateRoots(installRoot, stageRoot);
            Log(logPath, "Waiting for Tiance desktop shell to exit.");
            WaitForProcessExit(parentPid, TimeSpan.FromSeconds(45));
            InstallUpdate(installRoot, stageRoot, logPath);
            StartApplication(installRoot);
            Log(logPath, "Update completed.");
            return 0;
        }
        catch (Exception error)
        {
            Log(logPath, "Update failed: " + error);
            MessageBoxW(
                IntPtr.Zero,
                "天策更新失败，原程序文件已尽量恢复。\n\n" +
                "请重新启动天策；仍失败时查看更新日志：\n" + logPath,
                "Tiance Updater",
                0x00000010
            );
            return 1;
        }
    }

    private static void InstallUpdate(string installRoot, string stageRoot, string logPath)
    {
        string backupRoot = Path.Combine(
            installRoot,
            ".tiance-update-backup",
            DateTime.UtcNow.ToString("yyyyMMddHHmmss")
        );
        Directory.CreateDirectory(backupRoot);
        List<Replacement> replacements = new List<Replacement>();
        try
        {
            foreach (string relativePath in ReplacementPaths)
            {
                string source = Path.Combine(stageRoot, relativePath);
                if (!File.Exists(source) && !Directory.Exists(source))
                {
                    continue;
                }
                string destinationRelativePath = IsLegacyRuntimeBridge(relativePath)
                    ? "runtime"
                    : relativePath;
                string destination = Path.Combine(installRoot, destinationRelativePath);
                string backup = Path.Combine(backupRoot, destinationRelativePath);
                Replacement replacement = new Replacement(destination, backup);
                BackupExisting(destination, backup, replacement);
                replacements.Add(replacement);
                CopyEntry(source, destination);
                replacement.Installed = true;
                Log(logPath, "Replaced " + relativePath + " -> " + destinationRelativePath);
            }
        }
        catch
        {
            Rollback(replacements, logPath);
            throw;
        }
    }

    private static bool IsLegacyRuntimeBridge(string relativePath)
    {
        return string.Equals(
            relativePath,
            Path.Combine("Data", "runtime"),
            StringComparison.OrdinalIgnoreCase
        );
    }

    private static void BackupExisting(string destination, string backup, Replacement replacement)
    {
        if (File.Exists(destination))
        {
            Directory.CreateDirectory(Path.GetDirectoryName(backup));
            File.Move(destination, backup);
            replacement.HadOriginal = true;
        }
        else if (Directory.Exists(destination))
        {
            Directory.CreateDirectory(Path.GetDirectoryName(backup));
            Directory.Move(destination, backup);
            replacement.HadOriginal = true;
        }
    }

    private static void Rollback(List<Replacement> replacements, string logPath)
    {
        for (int index = replacements.Count - 1; index >= 0; index--)
        {
            Replacement replacement = replacements[index];
            try
            {
                DeleteEntry(replacement.Destination);
                if (replacement.HadOriginal)
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(replacement.Destination));
                    if (File.Exists(replacement.Backup))
                    {
                        File.Move(replacement.Backup, replacement.Destination);
                    }
                    else if (Directory.Exists(replacement.Backup))
                    {
                        Directory.Move(replacement.Backup, replacement.Destination);
                    }
                }
            }
            catch (Exception rollbackError)
            {
                Log(logPath, "Rollback failed for " + replacement.Destination + ": " + rollbackError);
            }
        }
    }

    private static void CopyEntry(string source, string destination)
    {
        if (File.Exists(source))
        {
            Directory.CreateDirectory(Path.GetDirectoryName(destination));
            File.Copy(source, destination, true);
            return;
        }
        CopyDirectory(source, destination);
    }

    private static void CopyDirectory(string source, string destination)
    {
        Directory.CreateDirectory(destination);
        foreach (string directory in Directory.GetDirectories(source, "*", SearchOption.AllDirectories))
        {
            string relative = directory.Substring(source.Length).TrimStart(Path.DirectorySeparatorChar);
            Directory.CreateDirectory(Path.Combine(destination, relative));
        }
        foreach (string file in Directory.GetFiles(source, "*", SearchOption.AllDirectories))
        {
            string relative = file.Substring(source.Length).TrimStart(Path.DirectorySeparatorChar);
            string target = Path.Combine(destination, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            File.Copy(file, target, true);
        }
    }

    private static void DeleteEntry(string path)
    {
        if (File.Exists(path))
        {
            File.SetAttributes(path, FileAttributes.Normal);
            File.Delete(path);
        }
        else if (Directory.Exists(path))
        {
            Directory.Delete(path, true);
        }
    }

    private static void ValidateRoots(string installRoot, string stageRoot)
    {
        if (Directory.Exists(Path.Combine(installRoot, ".git")))
        {
            throw new InvalidOperationException("Source checkouts cannot be replaced by the updater.");
        }
        if (!File.Exists(Path.Combine(stageRoot, ".tiance-update-ready")))
        {
            throw new InvalidOperationException("The staged update is not ready.");
        }
        string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string expectedRoot = Path.GetFullPath(Path.Combine(localAppData, "Tiance", "updates")) + Path.DirectorySeparatorChar;
        string normalizedStage = Path.GetFullPath(stageRoot).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!normalizedStage.StartsWith(expectedRoot, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("The staged update path is outside the Tiance update cache.");
        }
        if (!File.Exists(Path.Combine(stageRoot, "Tiance.exe")) ||
            !File.Exists(Path.Combine(stageRoot, "version.json")))
        {
            throw new InvalidOperationException("The staged update is incomplete.");
        }
    }

    private static void WaitForProcessExit(int pid, TimeSpan timeout)
    {
        try
        {
            Process process = Process.GetProcessById(pid);
            if (!process.WaitForExit((int)timeout.TotalMilliseconds))
            {
                throw new TimeoutException("Tiance did not close within the update timeout.");
            }
        }
        catch (ArgumentException)
        {
        }
    }

    private static void StartApplication(string installRoot)
    {
        string launcher = Path.Combine(installRoot, "Tiance.exe");
        Process.Start(new ProcessStartInfo
        {
            FileName = launcher,
            WorkingDirectory = installRoot,
            UseShellExecute = true,
        });
    }

    private static Dictionary<string, string> ParseOptions(string[] args)
    {
        Dictionary<string, string> options = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (int index = 0; index < args.Length; index += 2)
        {
            if (!args[index].StartsWith("--", StringComparison.Ordinal) || index + 1 >= args.Length)
            {
                throw new ArgumentException("Invalid updater arguments.");
            }
            options[args[index].Substring(2)] = args[index + 1];
        }
        return options;
    }

    private static string RequireDirectory(Dictionary<string, string> options, string key)
    {
        string value;
        if (!options.TryGetValue(key, out value))
        {
            throw new ArgumentException("Missing updater option: " + key);
        }
        string path = Path.GetFullPath(value);
        if (!Directory.Exists(path))
        {
            throw new DirectoryNotFoundException(path);
        }
        return path.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }

    private static int ParsePositiveInt(Dictionary<string, string> options, string key)
    {
        string value;
        int result;
        if (!options.TryGetValue(key, out value) || !int.TryParse(value, out result) || result <= 0)
        {
            throw new ArgumentException("Invalid updater option: " + key);
        }
        return result;
    }

    private static string BuildLogPath()
    {
        string directory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Tiance",
            "logs"
        );
        Directory.CreateDirectory(directory);
        return Path.Combine(directory, "updater.log");
    }

    private static void Log(string path, string message)
    {
        File.AppendAllText(path, DateTime.UtcNow.ToString("o") + " " + message + Environment.NewLine);
    }

    private sealed class Replacement
    {
        internal Replacement(string destination, string backup)
        {
            Destination = destination;
            Backup = backup;
        }

        internal string Destination { get; private set; }
        internal string Backup { get; private set; }
        internal bool HadOriginal { get; set; }
        internal bool Installed { get; set; }
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBoxW(IntPtr hwnd, string text, string caption, uint type);
}
