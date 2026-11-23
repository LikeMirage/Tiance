using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;

internal static class SetupWindow
{
    internal const string ProgressText = "首次启动，正在安装必要的运行环境。";

    private static Form Window()
    {
        return new Form {
            Text = "天策", Font = SystemFonts.MessageBoxFont, AutoScaleMode = AutoScaleMode.Font,
            StartPosition = FormStartPosition.CenterScreen, FormBorderStyle = FormBorderStyle.FixedDialog,
            MaximizeBox = false, MinimizeBox = false, ShowIcon = false,
            AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink
        };
    }

    private static FlowLayoutPanel Column(Form form)
    {
        var column = new FlowLayoutPanel {
            FlowDirection = FlowDirection.TopDown, WrapContents = false,
            AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Padding = new Padding(18)
        };
        form.Controls.Add(column);
        return column;
    }

    internal static Form CreateProgress()
    {
        var form = Window();
        form.ControlBox = false;
        var column = Column(form);
        column.Controls.Add(new Label { Text = ProgressText, AutoSize = true });
        column.Controls.Add(new ProgressBar {
            Width = 300, Height = 6, Style = ProgressBarStyle.Marquee, Margin = new Padding(3, 12, 3, 3)
        });
        return form;
    }

    internal static IDisposable ShowProgress()
    {
        var form = CreateProgress();
        form.Show();
        form.Update();
        return form;
    }

    internal static Form CreateFailure(string detail, bool fixedRuntime)
    {
        var form = Window();
        var column = Column(form);
        string url = fixedRuntime ? WebViewCheck.FixedDownload : WebViewCheck.OfflineDownload;
        string instruction = fixedRuntime
            ? "请更新指定目录中的 Microsoft Edge WebView2 Fixed Version Runtime，或将天策改为使用系统运行时。"
            : "请下载并安装 Microsoft Edge WebView2 Runtime（Evergreen x64 离线安装包）。";
        column.Controls.Add(new Label {
            Text = instruction + "\n所需版本：" + WebViewCheck.Minimum + " 或更高版本。安装完成后，请重新运行天策。",
            AutoSize = true, MaximumSize = new Size(480, 0)
        });
        column.Controls.Add(new TextBox {
            Text = detail, Width = 480, Height = 48, Multiline = true, ReadOnly = true,
            BorderStyle = BorderStyle.None, BackColor = form.BackColor, ScrollBars = ScrollBars.Vertical,
            AccessibleName = "失败原因", Margin = new Padding(3, 12, 3, 6)
        });
        var address = new TextBox { Text = url, Width = 480, ReadOnly = true, AccessibleName = "微软下载地址" };
        column.Controls.Add(address);
        var buttons = new FlowLayoutPanel { AutoSize = true, Margin = new Padding(0, 8, 0, 0) };
        var copy = new Button { Text = "复制下载地址", AutoSize = true };
        copy.Click += delegate
        {
            try { Clipboard.SetText(url); copy.Text = "已复制"; }
            catch (ExternalException) { address.Focus(); address.SelectAll(); }
        };
        var close = new Button { Text = "关闭", DialogResult = DialogResult.OK, AutoSize = true };
        buttons.Controls.Add(copy);
        buttons.Controls.Add(close);
        column.Controls.Add(buttons);
        form.AcceptButton = copy;
        form.CancelButton = close;
        return form;
    }

    internal static void ShowFailure(string detail, bool fixedRuntime)
    {
        using (var form = CreateFailure(detail, fixedRuntime)) form.ShowDialog();
    }
}
