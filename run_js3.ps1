$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

& adb forward tcp:9222 localabstract:chrome_devtools_remote 2>&1 | Out-Null

$tabs = Invoke-RestMethod -Uri 'http://localhost:9222/json' -Method GET
$wsUrl = $tabs[0].webSocketDebuggerUrl
Write-Host "Tab URL: $($tabs[0].url)"
Write-Host "Tab title: $($tabs[0].title)"

Add-Type -AssemblyName System.Net.WebSockets
$cts = New-Object System.Threading.CancellationTokenSource
$ws = New-Object System.Net.WebSockets.ClientWebSocket
$uri = [System.Uri]$wsUrl
$ws.ConnectAsync($uri, $cts.Token).Wait()

function SendJS($ws, $id, $jsCode, $cts) {
    $escaped = $jsCode -replace '"', '\"' -replace "'", "\'"
    $msg = "{`"id`":$id,`"method`":`"Runtime.evaluate`",`"params`":{`"expression`":`"$escaped`",`"returnByValue`":true}}"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($msg)
    $segment = New-Object System.ArraySegment[byte] -ArgumentList @(,$bytes)
    $ws.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cts.Token).Wait()
    $buffer = New-Object byte[] 131072
    $seg2 = New-Object System.ArraySegment[byte] -ArgumentList @(,$buffer)
    $result = $ws.ReceiveAsync($seg2, $cts.Token).Result
    return [System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
}

# Check WebGL support
$r1 = SendJS $ws 1 "(function(){var c=document.createElement('canvas');return JSON.stringify({webgl:c.getContext('webgl')!=null,webgl2:c.getContext('webgl2')!=null});})()" $cts
Write-Host "WebGL check: $r1"

# Check canvas count and flutter state
$r2 = SendJS $ws 2 "(function(){return JSON.stringify({canvases:document.querySelectorAll('canvas').length,flt:document.querySelectorAll('flt-glass-pane').length,ck:typeof window.flutterCanvasKit,buildConfig:JSON.stringify(_flutter.buildConfig)});})()" $cts
Write-Host "Flutter state: $r2"

# Check console errors
$r3 = SendJS $ws 3 "(function(){return JSON.stringify({crossOriginIsolated:window.crossOriginIsolated,location:location.href});})()" $cts
Write-Host "Context: $r3"

$ws.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, 'done', $cts.Token).Wait()
