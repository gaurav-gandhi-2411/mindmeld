$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

# Check logcat for chrome/flutter errors
Write-Host "=== Recent Chrome/Flutter logcat ==="
& adb logcat -d -t 100 -s chromium 2>&1 | Select-Object -Last 40

Write-Host "`n=== Chrome logcat (last 30) ==="
& adb logcat -d -t 50 2>&1 | Where-Object { $_ -match 'chrome|flutter|canvaskit|webgl|ERROR|FATAL|crash' } | Select-Object -Last 30
