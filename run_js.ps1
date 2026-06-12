$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

# Forward Chrome DevTools
& adb forward tcp:9222 localabstract:chrome_devtools_remote 2>&1 | Out-Null

# Get the WebSocket URL for the tab
$tabs = Invoke-RestMethod -Uri 'http://localhost:9222/json' -Method GET
$wsUrl = $tabs[0].webSocketDebuggerUrl
Write-Host "WS URL: $wsUrl"

# Use DevTools via WebSocket to run JS
# We'll use Invoke-WebRequest with a simple JS eval approach via the /json/version endpoint
$version = Invoke-RestMethod -Uri 'http://localhost:9222/json/version' -Method GET
Write-Host "Browser: $($version.Browser)"
Write-Host "Protocol: $($version.'Protocol-Version')"

# Run JS via CDP using PowerShell WebSockets (requires .NET WebSockets)
Add-Type -AssemblyName System.Net.WebSockets.Client

$cts = New-Object System.Threading.CancellationTokenSource
$ws = New-Object System.Net.WebSockets.ClientWebSocket
$uri = [System.Uri]$wsUrl

try {
    $ws.ConnectAsync($uri, $cts.Token).Wait()
    Write-Host "Connected to DevTools WebSocket"

    # Send Runtime.evaluate command
    $msg = '{"id":1,"method":"Runtime.evaluate","params":{"expression":"JSON.stringify({title:document.title,canvases:document.querySelectorAll(\"canvas\").length,flutter:typeof _flutter,flutterLoader:typeof _flutter!==\"undefined\"?JSON.stringify(Object.keys(_flutter)):\"\",body:document.body.innerHTML.substring(0,500)})", "returnByValue":true}}'
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($msg)
    $segment = New-Object System.ArraySegment[byte] -ArgumentList @(,$bytes)
    $ws.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cts.Token).Wait()

    # Read response
    $buffer = New-Object byte[] 65536
    $seg2 = New-Object System.ArraySegment[byte] -ArgumentList @(,$buffer)
    $result = $ws.ReceiveAsync($seg2, $cts.Token).Result
    $response = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
    Write-Host "Response: $response"

    $ws.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, 'done', $cts.Token).Wait()
} catch {
    Write-Host "WS error: $_"
}
