$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

Write-Host "Starting emulator..."
Start-Process emulator -ArgumentList '-avd','mindmeld_avd','-no-window','-no-audio','-no-boot-anim','-gpu','swiftshader_indirect'

Write-Host "Polling for boot_completed..."
$maxWait = 120
$elapsed = 0
while ($elapsed -lt $maxWait) {
    Start-Sleep -Seconds 5
    $elapsed += 5
    try {
        $result = & adb shell getprop sys.boot_completed 2>&1
        $result = $result.Trim()
        Write-Host "  [${elapsed}s] sys.boot_completed = '$result'"
        if ($result -eq '1') {
            Write-Host "Emulator booted successfully after ${elapsed}s"
            break
        }
    } catch {
        Write-Host "  [${elapsed}s] adb not ready yet..."
    }
}
if ($result -ne '1') {
    Write-Host "ERROR: Emulator did not boot within ${maxWait}s"
    exit 1
}
