$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
try {
    $window = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][long]$request.hwnd)
    if ($null -eq $window) { throw 'UIA_WINDOW_UNAVAILABLE' }
    $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    $queue = [Collections.Generic.Queue[System.Windows.Automation.AutomationElement]]::new()
    $queue.Enqueue($window)
    $records = [Collections.Generic.List[object]]::new()
    $requestedIds = @($request.runtime_ids)
    while ($queue.Count -gt 0) {
        $element = $queue.Dequeue()
        $rid = $element.GetRuntimeId() -join ','
        $wanted = $requestedIds.Count -eq 0 -or $rid -in $requestedIds
        if ($wanted) {
            $current = $element.Current
            $patterns = @($element.GetSupportedPatterns() | ForEach-Object { $_.ProgrammaticName -replace 'PatternIdentifiers.Pattern','' })
            $rect = $current.BoundingRectangle
            $record = [ordered]@{
                runtime_id = $rid; process_id = $current.ProcessId; hwnd = [long]$request.hwnd
                name = $current.Name; automation_id = $current.AutomationId
                control_type = $current.ControlType.ProgrammaticName; class_name = $current.ClassName
                enabled = $current.IsEnabled; offscreen = $current.IsOffscreen
                focused = $current.HasKeyboardFocus; password = $current.IsPassword
                rect = @{ left=$rect.Left; top=$rect.Top; width=$rect.Width; height=$rect.Height }
                patterns = $patterns
            }
            $pattern = $null
            if (-not $current.IsPassword -and $element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$pattern)) {
                $record['value'] = $pattern.Current.Value
                $record['readonly'] = $pattern.Current.IsReadOnly
            }
            $pattern = $null
            if ($element.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$pattern)) {
                $record['selected'] = $pattern.Current.IsSelected
            }
            if ($request.operation -eq 'set_value' -and $rid -eq $request.runtime_ids[0]) {
                if (-not $current.IsEnabled -or $current.IsOffscreen -or $current.IsPassword) { throw 'UIA_ELEMENT_UNAVAILABLE' }
                if ($current.Name -ne $request.expected_name -or $current.ProcessId -ne $request.expected_process_id) { throw 'UIA_ELEMENT_CHANGED' }
                $pattern = $null
                if (-not $element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$pattern) -or $pattern.Current.IsReadOnly) { throw 'UIA_VALUE_UNSUPPORTED' }
                $pattern.SetValue([string]$request.value)
                $record['value'] = $pattern.Current.Value
                $record['performed'] = $true
            }
            $records.Add($record)
        }
        if ($requestedIds.Count -gt 0 -and $records.Count -eq $requestedIds.Count) { break }
        $child = $walker.GetFirstChild($element)
        while ($null -ne $child) {
            $queue.Enqueue($child)
            $child = $walker.GetNextSibling($child)
        }
    }
    @{ok=$true; elements=@($records.ToArray())} | ConvertTo-Json -Depth 12 -Compress
} catch {
    # No input text, password value or request content is echoed on error.
    @{ok=$false; error='UIA_READ_OR_ACTION_FAILED'; detail=$_.Exception.GetType().Name} | ConvertTo-Json -Compress
}
