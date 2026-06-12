$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

# Test if emulator can reach external URLs
Write-Host "Testing gstatic CDN reachability from emulator..."
$result = & adb shell "curl -s -o /dev/null -w '%{http_code}' https://www.gstatic.com/flutter-canvaskit/77e2e94772b6eb43759e34ed1ad7da4674e19cab/canvaskit.js --max-time 15" 2>&1
Write-Host "gstatic HTTP status: $result"

Write-Host "`nTesting github.io reachability..."
$result2 = & adb shell "curl -s -o /dev/null -w '%{http_code}' https://gaurav-gandhi-2411.github.io/mindmeld-payloads/play/ --max-time 10" 2>&1
Write-Host "github.io HTTP status: $result2"
