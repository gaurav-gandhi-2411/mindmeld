$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

$lhOut = 'C:\Users\gaura\ml-projects\mindmeld\lh.json'
$url = 'https://gaurav-gandhi-2411.github.io/mindmeld-payloads/play/'

Write-Host "Running Lighthouse on $url ..."
npx --yes lighthouse@latest $url `
    --output=json `
    "--output-path=$lhOut" `
    --only-categories=performance,best-practices,seo `
    '--chrome-flags=--headless=new' `
    --quiet 2>&1

if (Test-Path $lhOut) {
    $lh = Get-Content $lhOut | ConvertFrom-Json
    $perf = [Math]::Round($lh.categories.performance.score * 100)
    $bp = [Math]::Round($lh.categories.'best-practices'.score * 100)
    $seo = [Math]::Round($lh.categories.seo.score * 100)
    Write-Host "Lighthouse scores:"
    Write-Host "  Performance: $perf"
    Write-Host "  Best Practices: $bp"
    Write-Host "  SEO: $seo"
} else {
    Write-Host "ERROR: Lighthouse output file not found"
}
