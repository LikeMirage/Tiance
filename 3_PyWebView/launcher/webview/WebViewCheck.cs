using System;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;

internal static class WebViewCheck
{
    // Runtime paired with the desktop shell's WebView2 SDK 1.0.3856.49.
    internal static readonly Version Minimum = new Version(146, 0, 3856, 49);
    internal const string FixedDownload = "https://developer.microsoft.com/microsoft-edge/webview2/#download-section";
    internal const string OfflineDownload = "https://go.microsoft.com/fwlink/p/?LinkId=2124701";

    [STAThread]
    private static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        if (args.Length == 2 && args[0] == "--configuration-error")
        {
            SetupWindow.ShowFailure(args[1], true);
            return 1;
        }
        if (args.Length != 3) return 2;

        string sdk = Path.GetFullPath(args[0]);
        string browser = String.IsNullOrEmpty(args[1]) ? null : args[1];
        AppDomain.CurrentDomain.AssemblyResolve += delegate(object sender, ResolveEventArgs request)
        {
            if (new AssemblyName(request.Name).Name != "Microsoft.Web.WebView2.Core") return null;
            return Assembly.LoadFrom(Path.Combine(sdk, "Microsoft.Web.WebView2.Core.dll"));
        };

        // WebView2 async initialization requires an STA with a live message pump.
        int result = 1;
        using (var context = new ApplicationContext())
        {
            SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
            EventHandler start = null;
            start = async delegate
            {
                Application.Idle -= start;
                try
                {
                    await CheckAndRepair(sdk, browser, args[2]);
                    result = 0;
                }
                catch (Exception ex)
                {
                    SetupWindow.ShowFailure(ex.GetBaseException().Message, browser != null);
                }
                finally { context.ExitThread(); }
            };
            Application.Idle += start;
            Application.Run(context);
        }
        return result;
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static async Task CheckAndRepair(string sdk, string browser, string profile)
    {
        CoreWebView2Environment.SetLoaderDllFolderPath(Path.Combine(sdk, "runtimes", "win-x64", "native"));
        await EnsureCompatible(() => Probe(browser, profile), browser,
            () => Task.Run((Action)EvergreenInstaller.Install), SetupWindow.ShowProgress);
    }

    internal static async Task EnsureCompatible(Func<Task<bool>> probe, string browser,
        Func<Task> install, Func<IDisposable> showProgress)
    {
        if (await probe()) return;
        if (browser != null)
            throw new InvalidOperationException("指定的 WebView2 运行时缺失或版本过低：" + browser);
        using (showProgress())
        {
            Exception installError = null;
            try { await install(); }
            catch (Exception ex) { installError = ex; }
            // Another installer can finish while ours reports 'already installed'.
            if (await probe()) return;
            if (installError != null) throw installError;
            throw new InvalidOperationException("安装程序已退出，仍未检测到兼容的 WebView2 运行时。");
        }
    }

    internal static bool Compatible(string value)
    {
        Version version;
        return Version.TryParse(value, out version) && version >= Minimum;
    }

    private static async Task<bool> Probe(string browser, string profile)
    {
        try
        {
            if (!Compatible(CoreWebView2Environment.GetAvailableBrowserVersionString(browser))) return false;
            var pending = CoreWebView2Environment.CreateAsync(browser, profile, null);
            if (await Task.WhenAny(pending, Task.Delay(TimeSpan.FromSeconds(30))) != pending)
                throw new TimeoutException("初始化 WebView2 超时。请检查运行时及用户数据目录：" + profile);
            var environment = await pending;
            return Compatible(environment.BrowserVersionString);
        }
        catch (WebView2RuntimeNotFoundException) { return false; }
        catch (Exception ex)
        {
            // Only missing runtime files call for installation. Permissions, SDK
            // load errors and a locked data directory need the actual diagnostic.
            if (ex is System.Runtime.InteropServices.COMException &&
                (ex.HResult == unchecked((int)0x80070002) || ex.HResult == unchecked((int)0x80070003)))
                return false;
            throw;
        }
    }
}
