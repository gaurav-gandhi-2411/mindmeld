$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

& adb emu kill 2>&1
Start-Sleep -Seconds 3
Get-Process | Where-Object { $_.ProcessName -match 'qemu|emulator' } | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "Emulator killed"
