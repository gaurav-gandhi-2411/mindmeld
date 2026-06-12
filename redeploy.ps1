$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

$src = 'C:\Users\gaura\ml-projects\mindmeld\app\build\web'
$stagingDir = 'C:\Users\gaura\ml-projects\mindmeld\web-dist'
$playDir = 'C:\Users\gaura\ml-projects\mindmeld-payloads\play'

# Refresh staging
if (Test-Path $stagingDir) { Remove-Item $stagingDir -Recurse -Force }
New-Item -ItemType Directory -Path $stagingDir | Out-Null
Copy-Item -Path "$src\*" -Destination $stagingDir -Recurse -Force
Write-Host "Updated staging dir"

# Refresh play/ dir in payloads repo
Get-ChildItem $playDir | Remove-Item -Recurse -Force
Copy-Item -Path "$src\*" -Destination $playDir -Recurse -Force
Write-Host "Updated play/ dir"

$count = (Get-ChildItem $playDir -Recurse).Count
Write-Host "play/ now contains $count files/dirs"
