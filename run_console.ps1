$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

& adb forward tcp:9222 localabstract:chrome_devtools_remote 2>&1 | Out-Null

$tabs = Invoke-RestMethod -Uri 'http://localhost:9222/json' -Method GET
$wsUrl = $tabs[0].webSocketDebuggerUrl

Add-Type -AssemblyName System.Net.WebSockets
$cts = New-Object System.Threading.CancellationTokenSource
$ws = New-Object System.Net.WebSockets.ClientWebSocket
$uri = [System.Uri]$wsUrl
$ws.ConnectAsync($uri, $cts.Token).Wait()

# Enable Console logging to capture messages
$enablePayload = '{"id":100,"method":"Runtime.enable"}'
$enableConsole = '{"id":101,"method":"Log.enable"}'

foreach ($msg in @($enablePayload, $enableConsole)) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($msg)
    $segment = New-Object System.ArraySegment[byte] -ArgumentList @(,$bytes)
    $ws.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cts.Token).Wait()
    Start-Sleep -Milliseconds 200
}

# Reload the page to capture console from start
$reloadMsg = '{"id":102,"method":"Page.reload","params":{"ignoreCache":true}}'
$bytes = [System.Text.Encoding]::UTF8.GetBytes($reloadMsg)
$segment = New-Object System.ArraySegment[byte] -ArgumentList @(,$bytes)
$ws.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cts.Token).Wait()
Write-Host "Reloaded page. Capturing events for 60s..."

# Collect messages
$messages = @()
$deadline = [DateTime]::Now.AddSeconds(60)
while ([DateTime]::Now -lt $deadline) {
    $buffer = New-Object byte[] 262144
    $seg2 = New-Object System.ArraySegment[byte] -ArgumentList @(,$buffer)

    $cancelToken = New-Object System.Threading.CancellationTokenSource
    $cancelToken.CancelAfter(2000)

    try {
        $result = $ws.ReceiveAsync($seg2, $cancelToken.Token).Result
        $msg = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
        if ($msg -match 'error|Error|exception|Exception|fail|Fail|canvas|Canvas|webgl|WebGL|flutter|Flutter|CanvasKit') {
            Write-Host "EVT: $($msg.Substring(0, [Math]::Min(500, $msg.Length)))"
            $messages += $msg
        }
    } catch {
        # timeout - just continue
    }
}

Write-Host "`n=== SUMMARY: Captured $($messages.Count) relevant events ==="
$ws.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, 'done', $cts.Token).Wait()
