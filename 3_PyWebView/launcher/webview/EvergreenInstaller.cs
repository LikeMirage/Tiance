using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Security.Principal;

internal static class EvergreenInstaller
{
    internal const string Bootstrapper = "https://go.microsoft.com/fwlink/p/?LinkId=2124703";

    internal static void Install()
    {
        // The elevated bootstrapper must not load side-by-side files from a user-writable directory.
        string stagingRoot = Path.GetTempPath();
        using (var identity = WindowsIdentity.GetCurrent())
            if (new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))
                stagingRoot = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        string directory = Path.Combine(stagingRoot, "Tiance-WebView2-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        string file = Path.Combine(directory, "MicrosoftEdgeWebview2Setup.exe");
        try
        {
            Download(file);
            // Prevent replacement or writes between Authenticode validation and execution.
            using (File.Open(file, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                VerifyPublisher(file);
                using (var process = Process.Start(new ProcessStartInfo(file, "/silent /install") {
                    UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden,
                    WorkingDirectory = directory
                }))
                {
                    if (!process.WaitForExit(10 * 60 * 1000))
                        throw new TimeoutException("微软 WebView2 安装程序未在十分钟内完成。");
                    if (process.ExitCode != 0)
                        throw new InvalidOperationException("微软安装程序返回 0x" + process.ExitCode.ToString("X8") + "。");
                }
            }
        }
        finally
        {
            // The updater may temporarily retain a file handle after returning.
            try { File.Delete(file); Directory.Delete(directory); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }

    internal static void Download(string file)
    {
        ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
        using (var client = new HttpClient())
        {
            client.MaxResponseContentBufferSize = 16 * 1024 * 1024;
            client.Timeout = TimeSpan.FromMinutes(2);
            using (var response = client.GetAsync(Bootstrapper).GetAwaiter().GetResult())
            {
                response.EnsureSuccessStatusCode();
                if (response.RequestMessage.RequestUri.Scheme != Uri.UriSchemeHttps)
                    throw new InvalidDataException("微软安装程序的下载地址必须使用 HTTPS。");
                using (var dest = new FileStream(file, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                    response.Content.CopyToAsync(dest).GetAwaiter().GetResult();
            }
        }
    }

    internal static void VerifyPublisher(string file)
    {
        string powershell = Path.Combine(Environment.SystemDirectory, @"WindowsPowerShell\v1.0\powershell.exe");
        // The path is passed as data, including paths containing quotes or non-ASCII characters.
        const string command = "$ErrorActionPreference='Stop'; $s=Microsoft.PowerShell.Security\\Get-AuthenticodeSignature -LiteralPath $env:TIANCE_SETUP_FILE; " +
            "if ($s.Status -ne 'Valid' -or $s.SignerCertificate.GetNameInfo('SimpleName',$false) -ne 'Microsoft Corporation') { exit 1 }; exit 0";
        var info = new ProcessStartInfo(powershell, "-NoLogo -NoProfile -NonInteractive -Command \"" + command + "\"") {
            UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden,
            WorkingDirectory = Environment.SystemDirectory
        };
        info.EnvironmentVariables["PSModulePath"] = Path.Combine(Path.GetDirectoryName(powershell), "Modules");
        info.EnvironmentVariables["TIANCE_SETUP_FILE"] = file;
        using (var process = Process.Start(info))
        {
            if (!process.WaitForExit(60000))
            {
                process.Kill();
                throw new TimeoutException("验证微软安装程序的数字签名超时。");
            }
            if (process.ExitCode != 0)
                throw new InvalidDataException("无法验证安装程序的微软数字签名。");
        }
    }
}
