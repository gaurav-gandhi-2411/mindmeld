$chromePath = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$lhOut = 'C:\Users\gaura\ml-projects\mindmeld\lh3.json'
$url = 'https://gaurav-gandhi-2411.github.io/mindmeld-payloads/play/'

Write-Host "Running Lighthouse on $url with system Chrome..."
npx lighthouse@latest $url `
    --output=json `
    "--output-path=$lhOut" `
    --only-categories=performance,best-practices,seo `
    "--chrome-path=$chromePath" `
    '--chrome-flags=--headless=new --no-sandbox' `
    --max-wait-for-load=60000 `
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
        Write-Host "Performance: $(if($perf){[Math]::Round($perf * 100)}else{'N/A'})"
        Write-Host "Best Practices: $(if($bp){[Math]::Round($bp * 100)}else{'N/A'})"
        Write-Host "SEO: $(if($seo){[Math]::Round($seo * 100)}else{'N/A'})"
        $fcp = $lh.audits.'first-contentful-paint'
        $lcp = $lh.audits.'largest-contentful-paint'
        if ($fcp.displayValue) { Write-Host "FCP: $($fcp.displayValue) (score=$($fcp.score))" }
        if ($lcp.displayValue) { Write-Host "LCP: $($lcp.displayValue) (score=$($lcp.score))" }
        # Check manifest and SW installability
        $manifest = $lh.audits.'installable-manifest'
        if ($manifest) { Write-Host "Installable manifest: $($manifest.score) - $($manifest.explanation)" }
    }
}
