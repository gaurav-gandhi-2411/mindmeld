$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

# Forward Chrome DevTools
& adb forward tcp:9222 localabstract:chrome_devtools_remote 2>&1 | Out-Null

# Query Chrome tabs via DevTools protocol
try {
    $tabs = Invoke-RestMethod -Uri 'http://localhost:9222/json' -Method GET
    Write-Host "Open tabs in Chrome:"
    foreach ($tab in $tabs) {
        Write-Host "  URL: $($tab.url)"
        Write-Host "  Title: $($tab.title)"
        Write-Host "  Type: $($tab.type)"
        Write-Host "  WS Debugger: $($tab.webSocketDebuggerUrl)"
        Write-Host ""
    }
} catch {
    Write-Host "DevTools not accessible: $_"
}
