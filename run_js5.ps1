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

function EvalJs {
    param($ws, $id, $expr, $cts)
    $payload = @{
        id = $id
        method = "Runtime.evaluate"
        params = @{
            expression = $expr
            returnByValue = $true
        }
    } | ConvertTo-Json -Depth 5 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
    $segment = New-Object System.ArraySegment[byte] -ArgumentList @(,$bytes)
    $ws.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cts.Token).Wait()
    $buffer = New-Object byte[] 262144
    $seg2 = New-Object System.ArraySegment[byte] -ArgumentList @(,$buffer)
    $result = $ws.ReceiveAsync($seg2, $cts.Token).Result
    return [System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
}

# Check flt-glass-pane innerHTML
$r1 = EvalJs $ws 1 "document.querySelector('flt-glass-pane').innerHTML.substring(0,300)" $cts
Write-Host "flt-glass innerHTML: $r1"

# Check full body DOM structure
$r2 = EvalJs $ws 2 "document.body.innerHTML.substring(0,800)" $cts
Write-Host "Body: $r2"

# Check if there's a pending promise on canvasKitLoaded
$r3 = EvalJs $ws 3 "typeof window.flutterCanvasKitLoaded + ' - ck keys=' + Object.keys(window.flutterCanvasKit||{}).slice(0,10).join(',')" $cts
Write-Host "CanvasKit: $r3"

$ws.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, 'done', $cts.Token).Wait()
