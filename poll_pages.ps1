$url = 'https://gaurav-gandhi-2411.github.io/mindmeld-payloads/play/'
$maxAttempts = 16
$interval = 15
$live = $false
for ($i = 1; $i -le $maxAttempts; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri $url -Method GET -UseBasicParsing -TimeoutSec 10
        $code = $resp.StatusCode
        Write-Host "Attempt $i - HTTP $code - LIVE"
        $live = $true
        break
    } catch {
        $ex = $_.Exception
        if ($ex.Response -ne $null) {
            $code = [int]$ex.Response.StatusCode
        } else {
            $code = 'no-response'
        }
        Write-Host "Attempt $i - HTTP $code - waiting ${interval}s..."
        Start-Sleep -Seconds $interval
    }
}
if (-not $live) {
    Write-Host "TIMEOUT: site not live after $maxAttempts attempts"
    exit 1
}
Write-Host "Site is live at $url"
