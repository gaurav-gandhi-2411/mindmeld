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

# Check canvaskit status
$jsExpr = 'JSON.stringify({canvases:document.querySelectorAll("canvas").length, flutterCanvasKit: typeof window.flutterCanvasKit, flutterCanvasKitLoaded: typeof window.flutterCanvasKitLoaded, fltElements: document.querySelectorAll("flt-glass-pane,flt-scene-host,flt-scene").length, errors: window.__flutterErrors || "none"})'
$msg = "{`"id`":2,`"method`":`"Runtime.evaluate`",`"params`":{`"expression`":`"$jsExpr`",`"returnByValue`":true}}"
$bytes = [System.Text.Encoding]::UTF8.GetBytes($msg)
$segment = New-Object System.ArraySegment[byte] -ArgumentList @(,$bytes)
$ws.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cts.Token).Wait()

$buffer = New-Object byte[] 65536
$seg2 = New-Object System.ArraySegment[byte] -ArgumentList @(,$buffer)
$result = $ws.ReceiveAsync($seg2, $cts.Token).Result
$response = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
Write-Host "CanvasKit status: $response"

$ws.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, 'done', $cts.Token).Wait()
