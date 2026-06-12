$base = 'https://gaurav-gandhi-2411.github.io/mindmeld-payloads'
$urls = @(
    "$base/play/",
    "$base/play/manifest.json",
    "$base/play/sqlite3.wasm",
    "$base/play/flutter_service_worker.js",
    "$base/play/icons/Icon-512.png",
    "$base/en/2026-06-12.json.gz"
)

foreach ($url in $urls) {
    try {
        $resp = Invoke-WebRequest -Uri $url -Method HEAD -UseBasicParsing -TimeoutSec 10
        $code = $resp.StatusCode
        $acao = $resp.Headers['Access-Control-Allow-Origin']
        if ($acao) {
            Write-Host "HTTP $code - $url  [ACAO: $acao]"
        } else {
            Write-Host "HTTP $code - $url"
        }
    } catch {
        $ex = $_.Exception
        if ($ex.Response -ne $null) {
            $code = [int]$ex.Response.StatusCode
            Write-Host "HTTP $code - $url"
        } else {
            Write-Host "ERROR - $url - $($ex.Message)"
        }
    }
}
