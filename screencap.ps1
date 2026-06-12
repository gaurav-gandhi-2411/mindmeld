$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

$outPath = $args[0]
if (-not $outPath) { $outPath = 'C:\Users\gaura\ml-projects\mindmeld\shot.png' }

# Use adb shell screencap to /sdcard then pull
& adb shell screencap -p /sdcard/shot.png
& adb pull /sdcard/shot.png $outPath
Write-Host "Screencap saved to $outPath"
