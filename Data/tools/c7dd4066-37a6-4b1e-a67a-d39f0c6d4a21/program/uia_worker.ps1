$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName UIAutomationClientsideProviders
# Register through a named managed method: the .NET provider loader walks the
# caller's stack and cannot inspect PowerShell's anonymous dynamic call frames.
Add-Type -ReferencedAssemblies @('UIAutomationClient','UIAutomationClientsideProviders','UIAutomationTypes') @'
using System;
using System.Runtime.InteropServices;
public static class UiaNative {
    [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
    public static void InitializeProviders() {
        System.Windows.Automation.ClientSettings.RegisterClientSideProviders(
            UIAutomationClientsideProviders.UIAutomationClientSideProviders.ClientSideProviderDescriptionTable);
    }
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr hwnd, uint cmd);
}
'@
[UiaNative]::InitializeProviders()

function Describe($element) {
    $current = $element.Current
    $rect = $current.BoundingRectangle
    $record = [ordered]@{
        runtime_id = $element.GetRuntimeId() -join ','
        process_id = $current.ProcessId
        name = $current.Name; automation_id = $current.AutomationId
        control_type = $current.ControlType.ProgrammaticName; class_name = $current.ClassName
        enabled = $current.IsEnabled; offscreen = $current.IsOffscreen
        focused = $current.HasKeyboardFocus; focusable = $current.IsKeyboardFocusable
        password = $current.IsPassword
        rect = $null
        patterns = @($element.GetSupportedPatterns() | ForEach-Object { $_.ProgrammaticName -replace 'PatternIdentifiers.Pattern','' })
    }
    if (-not $rect.IsEmpty) { $record.rect = @{left=$rect.Left; top=$rect.Top; width=$rect.Width; height=$rect.Height} }
    $pattern = $null
    if (-not $current.IsPassword -and $element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$pattern)) {
        $record.value = $pattern.Current.Value; $record.readonly = $pattern.Current.IsReadOnly
    }
    $pattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$pattern)) { $record.selected = $pattern.Current.IsSelected }
    $pattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern,[ref]$pattern)) { $record.toggle_state = [string]$pattern.Current.ToggleState }
    $pattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern,[ref]$pattern)) { $record.expand_state = [string]$pattern.Current.ExpandCollapseState }
    return $record
}

function Find-Controls($window, $runtimeId) {
    $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    $queue = [Collections.Generic.Queue[System.Windows.Automation.AutomationElement]]::new()
    $queue.Enqueue($window)
    $records = [Collections.Generic.List[object]]::new()
    while ($queue.Count -gt 0) {
        $element = $queue.Dequeue()
        if ($runtimeId) {
            if (($element.GetRuntimeId() -join ',') -eq $runtimeId) { return $element }
        } else { $records.Add((Describe $element)) }
        $child = $walker.GetFirstChild($element)
        while ($null -ne $child) { $queue.Enqueue($child); $child = $walker.GetNextSibling($child) }
    }
    if ($runtimeId) { return $null }
    return ,($records.ToArray())
}

while ($null -ne ($line = [Console]::ReadLine())) {
    $request = $null; $started = $false
    $code = 'UIA_UNAVAILABLE'; $message = 'UIA控件读取失败，请重新观察。'
    try {
        $request = $line | ConvertFrom-Json
        $window = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][long]$request.hwnd)
        if ($null -eq $window -or $window.Current.ProcessId -ne $request.process_id) {
            $code = 'WINDOW_IDENTITY_CHANGED'; $message = '目标窗口已关闭或身份变化。'; throw $code
        }
        if ($request.operation -eq 'inspect') {
            $response = @{ok=$true; elements=(Find-Controls $window $null)}
        } else {
            $element = Find-Controls $window $request.expected.runtime_id
            $code = 'UIA_ELEMENT_STALE'; $message = '控件已消失或身份变化，请重新inspect。'
            if ($null -eq $element) { throw $code }
            $live = Describe $element
            foreach ($key in @('runtime_id','process_id','name','automation_id','control_type','class_name')) {
                if ($live[$key] -cne $request.expected.$key) { throw $code }
            }
            if ($request.operation -eq 'read') {
                $response = @{ok=$true; element=$live}
            } else {
                $code = 'UIA_ELEMENT_UNAVAILABLE'; $message = '控件不可用、不在可见区域或为密码输入框，本次未执行。'
                if (-not $live.enabled -or $live.offscreen -or $live.password) { throw $code }
                $foreground = [UiaNative]::GetForegroundWindow().ToInt64()
                $owner = [long]$request.hwnd
                $seen = [Collections.Generic.HashSet[long]]::new()
                while ($owner -ne 0 -and $owner -ne $foreground -and $seen.Add($owner)) {
                    $owner = [UiaNative]::GetWindow([IntPtr]$owner,4).ToInt64()
                }
                $code = 'TARGET_NOT_FOREGROUND'; $message = '控件窗口及其所属窗口已失去前台，本次未执行。'
                if ($owner -eq 0 -or $owner -ne $foreground) { throw $code }
                $code = 'UIA_ACTION_UNSUPPORTED'; $message = '该控件不支持请求的UIA操作；未改用鼠标或键盘。'
                $pattern = $null
                $patternId = switch ($request.operation) {
                    'invoke' { [System.Windows.Automation.InvokePattern]::Pattern }
                    'set_value' { [System.Windows.Automation.ValuePattern]::Pattern }
                    'select' { [System.Windows.Automation.SelectionItemPattern]::Pattern }
                    'toggle' { [System.Windows.Automation.TogglePattern]::Pattern }
                    'expand' { [System.Windows.Automation.ExpandCollapsePattern]::Pattern }
                    'collapse' { [System.Windows.Automation.ExpandCollapsePattern]::Pattern }
                    'focus' { $null }
                    default { throw $code }
                }
                if ($request.operation -eq 'focus') {
                    if (-not $live.focusable) { throw $code }
                } elseif (-not $element.TryGetCurrentPattern($patternId,[ref]$pattern)) { throw $code }
                if ($request.operation -eq 'set_value' -and $pattern.Current.IsReadOnly) { throw $code }
                $code = 'UIA_ACTION_UNCONFIRMED'; $message = 'UIA动作未能确认完成，可能已经生效；请重新观察，不要直接重试。'
                $started = $true
                switch ($request.operation) {
                    'invoke' { $pattern.Invoke() }
                    'set_value' { $pattern.SetValue([string]$request.value) }
                    'select' { $pattern.Select() }
                    'toggle' { $pattern.Toggle() }
                    'expand' { $pattern.Expand() }
                    'collapse' { $pattern.Collapse() }
                    'focus' { $element.SetFocus() }
                }
                $response = @{ok=$true; execution_status='completed'}
            }
        }
    } catch {
        $response = @{ok=$false; code=$code; message=$message; execution_status=$(if ($started) {'unknown'} else {'not_started'})}
    }
    $response.request_id = $request.request_id
    [Console]::WriteLine(($response | ConvertTo-Json -Depth 16 -Compress))
    [Console]::Out.Flush()
}
