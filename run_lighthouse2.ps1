$env:JAVA_HOME = 'C:\Users\gaura\sdks\jdk17'
$env:ANDROID_HOME = 'C:\Users\gaura\sdks\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = 'C:\Users\gaura\sdks\flutter\bin;' + $env:JAVA_HOME + '\bin;' + $env:ANDROID_HOME + '\platform-tools;' + $env:ANDROID_HOME + '\emulator;' + $env:PATH

$lhOut = 'C:\Users\gaura\ml-projects\mindmeld\lh2.json'
$url = 'https://gaurav-gandhi-2411.github.io/mindmeld-payloads/play/'

Write-Host "Running Lighthouse on $url ..."
# Use longer timeout and headless=old which handles WebGL/canvas better
npx lighthouse@latest $url `
    --output=json `
    "--output-path=$lhOut" `
    --only-categories=performance,best-practices,seo `
    '--chrome-flags=--headless=new --no-sandbox --disable-setuid-sandbox' `
    --max-wait-for-load=45000 `
    --quiet 2>&1

if (Test-Path $lhOut) {
    $size = (Get-Item $lhOut).Length
    Write-Host "Output file: $size bytes"
    if ($size -gt 1000) {
        $lh = Get-Content $lhOut | ConvertFrom-Json
        Write-Host "URL: $($lh.finalUrl)"
        Write-Host "LH version: $($lh.lighthouseVersion)"
        if ($lh.runtimeError) { Write-Host "Runtime error: $($lh.runtimeError.message)" }
        if ($lh.runWarnings) { $lh.runWarnings | ForEach-Object { Write-Host "Warning: $_" } }
        $perf = $lh.categories.performance.score
        $bp = $lh.categories.'best-practices'.score
        $seo = $lh.categories.seo.score
        Write-Host "Performance: $([Math]::Round($perf * 100))"
        Write-Host "Best Practices: $([Math]::Round($bp * 100))"
        Write-Host "SEO: $([Math]::Round($seo * 100))"
        # Individual audits
        $fcp = $lh.audits.'first-contentful-paint'
        $lcp = $lh.audits.'largest-contentful-paint'
        $tbt = $lh.audits.'total-blocking-time'
        if ($fcp.displayValue) { Write-Host "FCP: $($fcp.displayValue) (score=$($fcp.score))" }
        if ($lcp.displayValue) { Write-Host "LCP: $($lcp.displayValue) (score=$($lcp.score))" }
        if ($tbt.displayValue) { Write-Host "TBT: $($tbt.displayValue) (score=$($tbt.score))" }
        # Check manifest audit
        $manifest = $lh.audits.'installable-manifest'
        if ($manifest) { Write-Host "Installable manifest: score=$($manifest.score) - $($manifest.displayValue)" }
        $sw = $lh.audits.'service-worker'
        if ($sw) { Write-Host "Service worker: score=$($sw.score) - $($sw.displayValue)" }
    }
} else {
    Write-Host "No output file"
}
