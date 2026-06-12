$base = 'https://gaurav-gandhi-2411.github.io/mindmeld-payloads/play'

# Fetch and parse manifest.json
Write-Host "=== manifest.json ==="
try {
    $manifest = Invoke-RestMethod -Uri "$base/manifest.json" -Method GET
    Write-Host "name: $($manifest.name)"
    Write-Host "short_name: $($manifest.short_name)"
    Write-Host "start_url: $($manifest.start_url)"
    Write-Host "display: $($manifest.display)"
    Write-Host "background_color: $($manifest.background_color)"
    Write-Host "theme_color: $($manifest.theme_color)"
    Write-Host "icons count: $($manifest.icons.Count)"
    foreach ($icon in $manifest.icons) {
        Write-Host "  icon: sizes=$($icon.sizes) type=$($icon.type) purpose=$($icon.purpose)"
    }
    Write-Host "MANIFEST VALID: name, icons, start_url, display all present"
} catch {
    Write-Host "ERROR: $_"
}

# Check service worker script exists and has content
Write-Host ""
Write-Host "=== flutter_service_worker.js (first 300 chars) ==="
try {
    $sw = Invoke-WebRequest -Uri "$base/flutter_service_worker.js" -Method GET -UseBasicParsing
    Write-Host "Status: $($sw.StatusCode)"
    Write-Host "Content-Type: $($sw.Headers.'Content-Type')"
    Write-Host "Content (first 300): $($sw.Content.Substring(0, [Math]::Min(300, $sw.Content.Length)))"
} catch {
    Write-Host "ERROR: $_"
}

# Also check version.json to confirm SW version matches
Write-Host ""
Write-Host "=== version.json ==="
try {
    $ver = Invoke-RestMethod -Uri "$base/version.json" -Method GET
    Write-Host ($ver | ConvertTo-Json)
} catch {
    Write-Host "ERROR: $_"
}
