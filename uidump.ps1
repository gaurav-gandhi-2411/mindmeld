$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

& adb shell uiautomator dump /sdcard/uidump.xml
& adb pull /sdcard/uidump.xml C:\Users\gaura\ml-projects\mindmeld\uidump.xml
Write-Host 'UI dump pulled'
