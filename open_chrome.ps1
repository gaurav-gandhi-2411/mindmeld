$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

$url = 'https://gaurav-gandhi-2411.github.io/mindmeld-payloads/play/'

Write-Host "Opening Chrome with URL: $url"
& adb shell am start -a android.intent.action.VIEW -d $url com.android.chrome
Write-Host "Chrome started. Waiting 5s for initial load..."
Start-Sleep -Seconds 5
