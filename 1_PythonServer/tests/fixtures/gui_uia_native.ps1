# Creates only isolated test controls; no user application is operated.
param([string]$StatePath)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Windows.Forms @'
using System;
using System.Windows.Forms;
using System.Runtime.InteropServices;
public class TestPopup : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get { var p=base.CreateParams; p.ExStyle |= 0x08000080; return p; } }
}
public static class TestNative {
    [DllImport("user32.dll")] public static extern bool SetWindowDisplayAffinity(IntPtr hwnd,uint affinity);
}
'@
$form=[Windows.Forms.Form]::new()
$form.Text='Tiance isolated UIA test'; $form.StartPosition='Manual'
$form.Location=[Drawing.Point]::new(80,120); $form.Size=[Drawing.Size]::new(760,500)
$form.BackColor=[Drawing.Color]::White
$edit=[Windows.Forms.TextBox]::new(); $edit.Name='test_input'; $edit.AccessibleName='Test input'
$edit.Location=[Drawing.Point]::new(20,30); $edit.Width=220; $edit.Text='initial'
$button=[Windows.Forms.Button]::new(); $button.Name='test_button'; $button.Text='Invoke test'
$button.Location=[Drawing.Point]::new(20,75); $button.Width=150
$button.Add_Click({$edit.Text='invoked'})
$check=[Windows.Forms.CheckBox]::new(); $check.Name='test_check'; $check.Text='Toggle test'
$check.Location=[Drawing.Point]::new(20,120); $check.Width=150
$list=[Windows.Forms.ListBox]::new(); $list.Name='test_list'; $list.Location=[Drawing.Point]::new(20,165)
[void]$list.Items.Add('First item'); [void]$list.Items.Add('Second item')
$tree=[Windows.Forms.TreeView]::new(); $tree.Name='test_tree'; $tree.Location=[Drawing.Point]::new(270,30)
$tree.Size=[Drawing.Size]::new(180,160)
$parent=$tree.Nodes.Add('Parent node'); [void]$parent.Nodes.Add('Child node')
$form.Controls.AddRange(@($edit,$button,$check,$list,$tree))
$popup=[TestPopup]::new(); $popup.Text=''; $popup.FormBorderStyle='None'; $popup.StartPosition='Manual'
$popup.Location=[Drawing.Point]::new(500,460); $popup.Size=[Drawing.Size]::new(120,80)
$popup.BackColor=[Drawing.Color]::FromArgb(30,80,220); $popup.Opacity=0.95
$overlay=[TestPopup]::new(); $overlay.Text=''; $overlay.FormBorderStyle='None'; $overlay.StartPosition='Manual'
$overlay.Location=[Drawing.Point]::new(680,460); $overlay.Size=[Drawing.Size]::new(80,80)
$overlay.BackColor=[Drawing.Color]::Red; $overlay.Opacity=0.99
$form.Add_Shown({
    $popup.Show($form); $overlay.Show($form)
    $excluded=[TestNative]::SetWindowDisplayAffinity($overlay.Handle,0x11)
    $form.Activate()
    @{hwnd=$form.Handle.ToInt64(); popup=$popup.Handle.ToInt64(); overlay=$overlay.Handle.ToInt64();
      excluded=$excluded; process_id=$PID} | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8
})
try { [Windows.Forms.Application]::Run($form) }
finally { $overlay.Dispose(); $popup.Dispose(); $form.Dispose() }
