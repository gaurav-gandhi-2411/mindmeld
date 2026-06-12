$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

Write-Host "Starting emulator..."
Start-Process emulator -ArgumentList '-avd','mindmeld_avd','-no-window','-no-audio','-no-boot-anim','-gpu','swiftshader_indirect'

Write-Host "Polling for boot..."
$maxWait = 120
$elapsed = 0
$booted = $false
while ($elapsed -lt $maxWait) {
    Start-Sleep -Seconds 5
    $elapsed += 5
    try {
        $result = (& adb shell getprop sys.boot_completed 2>&1).Trim()
        Write-Host "  [${elapsed}s] boot_completed=$result"
        if ($result -eq '1') { $booted = $true; break }
    } catch { }
}
if (-not $booted) { Write-Host "ERROR: Did not boot"; exit 1 }

Start-Sleep -Seconds 5
Write-Host "Opening URL in Chrome..."
& adb shell am start -a android.intent.action.VIEW -d 'https://gaurav-gandhi-2411.github.io/mindmeld-payloads/play/' com.android.chrome
Write-Host "Chrome opened. Waiting 90s for wasm load..."
