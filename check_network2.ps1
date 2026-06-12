$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

# Test network with wget or ping
Write-Host "Testing network from emulator..."
$result = & adb shell "wget -q -O - https://www.gstatic.com/ 2>&1 | head -5" 2>&1
Write-Host "wget result: $result"

# Try am tool to check chrome accessibility
Write-Host "`nChecking installed Chrome version..."
$chromeVer = & adb shell "dumpsys package com.android.chrome | grep versionName" 2>&1
Write-Host "Chrome version: $chromeVer"

# Check if Chrome debugging is available
Write-Host "`nForward Chrome debug port..."
& adb forward tcp:9222 localabstract:chrome_devtools_remote 2>&1
