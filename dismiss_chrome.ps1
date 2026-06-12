$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

# Try using uiautomator to find and click "Use without an account"
Write-Host "Trying uiautomator click..."
& adb shell 'uiautomator runtest /data/local/tmp/libs/cts-uiautomator.apk:com.android.cts.uiautomator.UiAutomatorTest' 2>&1

# Alternative: use input keyevent to tab/press
# First let's try a swipe to scroll to the element and click
Write-Host "Trying swipe up then tap..."
& adb shell input swipe 354 1200 354 400 300
Start-Sleep -Seconds 1
& adb shell input tap 354 1358
Start-Sleep -Seconds 2

# Take screencap to see state
& adb shell screencap -p /sdcard/shot.png
& adb pull /sdcard/shot.png C:\Users\gaura\ml-projects\mindmeld\shot_dismiss.png
Write-Host "Done"
