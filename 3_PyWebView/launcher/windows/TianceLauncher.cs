using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

internal static class TianceLauncher
{
    private const string AppUserModelId = "LikeMirage.Tiance";
    private const string ChineseShortcutName = "天策.lnk";
    private const string EnglishShortcutName = "Tiance.lnk";
    private static readonly PROPERTYKEY AppUserModelIdPropertyKey = new PROPERTYKEY(
        new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"),
        5
    );

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            string projectRoot = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(
                Path.DirectorySeparatorChar,
                Path.AltDirectorySeparatorChar
            );
            string runtimeRoot = ResolveRuntimeRoot(projectRoot);
            string pythonwPath = Path.Combine(runtimeRoot, "python", "py313", "pythonw.exe");
            string pythonPath = Path.Combine(runtimeRoot, "python", "py313", "python.exe");
            string shellRunPath = Path.Combine(projectRoot, "3_PyWebView", "run.py");
            string shellRoot = Path.Combine(projectRoot, "3_PyWebView");

            if (!File.Exists(pythonwPath) && File.Exists(pythonPath))
            {
                pythonwPath = pythonPath;
            }

            if (!File.Exists(pythonwPath))
            {
                ShowError("Embedded Python was not found:\n" + pythonwPath);
                return 1;
            }

            if (!File.Exists(shellRunPath))
            {
                ShowError("Desktop shell entry was not found:\n" + shellRunPath);
                return 1;
            }

            TryEnsureDesktopShortcut(projectRoot);
            StartDesktopShell(pythonwPath, shellRunPath, shellRoot, args);
            return 0;
        }
        catch (Exception ex)
        {
            ShowError("Failed to start Tiance.\n\n" + ex.Message);
            return 1;
        }
    }

    private static string ResolveRuntimeRoot(string projectRoot)
    {
        string runtimeRoot = Path.Combine(projectRoot, "runtime");
        string legacyRuntimeRoot = Path.Combine(projectRoot, "Data", "runtime");
        if (HasEmbeddedPython(runtimeRoot))
        {
            PreserveUnexpectedLegacyRuntime(projectRoot, legacyRuntimeRoot);
            return runtimeRoot;
        }

        if (!HasEmbeddedPython(legacyRuntimeRoot))
        {
            return runtimeRoot;
        }

        try
        {
            Directory.Move(legacyRuntimeRoot, runtimeRoot);
            return runtimeRoot;
        }
        catch
        {
            // A failed migration must not make an otherwise usable installation unstartable.
            return legacyRuntimeRoot;
        }
    }

    private static bool HasEmbeddedPython(string runtimeRoot)
    {
        return File.Exists(Path.Combine(runtimeRoot, "python", "py313", "python.exe"));
    }

    private static void PreserveUnexpectedLegacyRuntime(string projectRoot, string legacyRuntimeRoot)
    {
        if (!Directory.Exists(legacyRuntimeRoot))
        {
            return;
        }
        try
        {
            string backupRoot = Path.Combine(projectRoot, ".tiance-runtime-backup");
            Directory.CreateDirectory(backupRoot);
            string backupPath = Path.Combine(backupRoot, DateTime.UtcNow.ToString("yyyyMMddHHmmssfff"));
            Directory.Move(legacyRuntimeRoot, backupPath);
        }
        catch
        {
            // The valid root runtime remains authoritative; preserving legacy files is best-effort.
        }
    }

    private static void StartDesktopShell(string pythonPath, string shellRunPath, string shellRoot, string[] args)
    {
        ProcessStartInfo startInfo = new ProcessStartInfo
        {
            FileName = pythonPath,
            WorkingDirectory = shellRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        startInfo.Arguments = QuoteArgument(shellRunPath);
        foreach (string arg in args)
        {
            startInfo.Arguments += " " + QuoteArgument(arg);
        }

        startInfo.EnvironmentVariables.Remove("PYTHONHOME");
        startInfo.EnvironmentVariables.Remove("PYTHONPATH");
        startInfo.EnvironmentVariables.Remove("VIRTUAL_ENV");
        startInfo.EnvironmentVariables.Remove("CONDA_PREFIX");
        startInfo.EnvironmentVariables.Remove("CONDA_DEFAULT_ENV");
        startInfo.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
        startInfo.EnvironmentVariables["TIANCE_SHELL_USE_EMBEDDED_PYTHON"] = "true";
        startInfo.EnvironmentVariables["TIANCE_API_USE_EMBEDDED_PYTHON"] = "true";
        startInfo.EnvironmentVariables["TIANCE_APP_USER_MODEL_ID"] = AppUserModelId;

        Process.Start(startInfo);
    }

    private static void TryEnsureDesktopShortcut(string projectRoot)
    {
        try
        {
            string launcherPath = Process.GetCurrentProcess().MainModule.FileName;
            string desktopPath = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
            if (string.IsNullOrWhiteSpace(desktopPath) || string.IsNullOrWhiteSpace(launcherPath))
            {
                return;
            }

            string chineseShortcut = Path.Combine(desktopPath, ChineseShortcutName);
            string englishShortcut = Path.Combine(desktopPath, EnglishShortcutName);
            bool existingShortcutUpdated = false;
            if (ShortcutTargets(chineseShortcut, launcherPath))
            {
                ApplyShortcutAppUserModelId(chineseShortcut);
                existingShortcutUpdated = true;
            }
            if (ShortcutTargets(englishShortcut, launcherPath))
            {
                ApplyShortcutAppUserModelId(englishShortcut);
                existingShortcutUpdated = true;
            }
            if (existingShortcutUpdated)
            {
                return;
            }

            string preferredShortcut = Path.Combine(
                desktopPath,
                IsChineseUiLanguage() ? ChineseShortcutName : EnglishShortcutName
            );
            CreateOrUpdateShortcut(preferredShortcut, launcherPath, projectRoot);
        }
        catch
        {
            // Shortcut creation must never block application startup.
        }
    }

    private static bool IsChineseUiLanguage()
    {
        string language = CultureInfo.CurrentUICulture.Name;
        if (string.IsNullOrWhiteSpace(language))
        {
            return false;
        }

        string normalized = language.Trim().ToLowerInvariant();
        return normalized == "zh" || normalized.StartsWith("zh-", StringComparison.Ordinal);
    }

    private static bool ShortcutTargets(string shortcutPath, string launcherPath)
    {
        if (!File.Exists(shortcutPath))
        {
            return false;
        }

        string targetPath = ReadShortcutTarget(shortcutPath);
        return PathsEqual(targetPath, launcherPath);
    }

    private static string ReadShortcutTarget(string shortcutPath)
    {
        IShellLinkW link = (IShellLinkW)new CShellLink();
        ((IPersistFile)link).Load(shortcutPath, 0);
        StringBuilder target = new StringBuilder(1024);
        WIN32_FIND_DATAW data;
        link.GetPath(target, target.Capacity, out data, 0);
        return target.ToString();
    }

    private static void CreateOrUpdateShortcut(string shortcutPath, string launcherPath, string projectRoot)
    {
        IShellLinkW link = (IShellLinkW)new CShellLink();
        link.SetPath(launcherPath);
        link.SetWorkingDirectory(projectRoot);
        link.SetDescription("Tiance");
        link.SetIconLocation(launcherPath, 0);
        SetShortcutAppUserModelId(link);
        ((IPersistFile)link).Save(shortcutPath, true);
    }

    private static void ApplyShortcutAppUserModelId(string shortcutPath)
    {
        IShellLinkW link = (IShellLinkW)new CShellLink();
        IPersistFile persistFile = (IPersistFile)link;
        persistFile.Load(shortcutPath, 2);
        SetShortcutAppUserModelId(link);
        persistFile.Save(shortcutPath, true);
    }

    private static void SetShortcutAppUserModelId(IShellLinkW link)
    {
        IPropertyStore propertyStore = (IPropertyStore)link;
        PROPERTYKEY propertyKey = AppUserModelIdPropertyKey;
        PROPVARIANT propertyValue = PROPVARIANT.FromString(AppUserModelId);
        try
        {
            propertyStore.SetValue(ref propertyKey, ref propertyValue);
            propertyStore.Commit();
        }
        finally
        {
            PropVariantClear(ref propertyValue);
        }
    }

    private static bool PathsEqual(string left, string right)
    {
        if (string.IsNullOrWhiteSpace(left) || string.IsNullOrWhiteSpace(right))
        {
            return false;
        }

        return string.Equals(
            Path.GetFullPath(left).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar),
            Path.GetFullPath(right).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar),
            StringComparison.OrdinalIgnoreCase
        );
    }

    private static string QuoteArgument(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return "\"\"";
        }

        StringBuilder result = new StringBuilder();
        result.Append('"');
        int backslashCount = 0;
        foreach (char character in value)
        {
            if (character == '\\')
            {
                backslashCount += 1;
                continue;
            }

            if (character == '"')
            {
                result.Append('\\', backslashCount * 2 + 1);
                result.Append('"');
                backslashCount = 0;
                continue;
            }

            result.Append('\\', backslashCount);
            result.Append(character);
            backslashCount = 0;
        }

        result.Append('\\', backslashCount * 2);
        result.Append('"');
        return result.ToString();
    }

    private static void ShowError(string message)
    {
        MessageBoxW(IntPtr.Zero, message, "Tiance", 0x00000010);
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBoxW(IntPtr hwnd, string text, string caption, uint type);

    [DllImport("ole32.dll")]
    private static extern int PropVariantClear(ref PROPVARIANT pvar);

    [ComImport]
    [Guid("00021401-0000-0000-C000-000000000046")]
    private class CShellLink
    {
    }

    [ComImport]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [Guid("000214F9-0000-0000-C000-000000000046")]
    private interface IShellLinkW
    {
        void GetPath(
            [Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszFile,
            int cchMaxPath,
            out WIN32_FIND_DATAW pfd,
            uint fFlags
        );

        void GetIDList(out IntPtr ppidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszName, int cchMaxName);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszDir, int cchMaxPath);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszArgs, int cchMaxPath);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string pszArgs);
        void GetHotkey(out short pwHotkey);
        void SetHotkey(short wHotkey);
        void GetShowCmd(out int piShowCmd);
        void SetShowCmd(int iShowCmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszIconPath, int cchIconPath, out int piIcon);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string pszIconPath, int iIcon);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pszPathRel, uint dwReserved);
        void Resolve(IntPtr hwnd, uint fFlags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
    }

    [ComImport]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [Guid("0000010b-0000-0000-C000-000000000046")]
    private interface IPersistFile
    {
        void GetClassID(out Guid pClassID);
        void IsDirty();
        void Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, uint dwMode);
        void Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, bool fRemember);
        void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
        void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string ppszFileName);
    }

    [ComImport]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    private interface IPropertyStore
    {
        void GetCount(out uint propertyCount);
        void GetAt(uint propertyIndex, out PROPERTYKEY propertyKey);
        void GetValue(ref PROPERTYKEY propertyKey, out PROPVARIANT propertyValue);
        void SetValue(ref PROPERTYKEY propertyKey, ref PROPVARIANT propertyValue);
        void Commit();
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    private struct PROPERTYKEY
    {
        public Guid formatId;
        public uint propertyId;

        public PROPERTYKEY(Guid formatId, uint propertyId)
        {
            this.formatId = formatId;
            this.propertyId = propertyId;
        }
    }

    [StructLayout(LayoutKind.Explicit, Size = 24)]
    private struct PROPVARIANT
    {
        [FieldOffset(0)]
        public ushort valueType;

        [FieldOffset(8)]
        public IntPtr pointerValue;

        public static PROPVARIANT FromString(string value)
        {
            return new PROPVARIANT
            {
                valueType = 31,
                pointerValue = Marshal.StringToCoTaskMemUni(value),
            };
        }
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct WIN32_FIND_DATAW
    {
        public uint dwFileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME ftCreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME ftLastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME ftLastWriteTime;
        public uint nFileSizeHigh;
        public uint nFileSizeLow;
        public uint dwReserved0;
        public uint dwReserved1;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
        public string cFileName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 14)]
        public string cAlternateFileName;
    }
}
