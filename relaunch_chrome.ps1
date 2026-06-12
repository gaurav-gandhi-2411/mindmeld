$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

# Force-stop Chrome first
& adb shell am force-stop com.android.chrome
Start-Sleep -Seconds 2

# Relaunch with the URL
& adb shell am start -a android.intent.action.VIEW -d 'https://gaurav-gandhi-2411.github.io/mindmeld-payloads/play/' com.android.chrome
Start-Sleep -Seconds 8
Write-Host "Chrome relaunched"
