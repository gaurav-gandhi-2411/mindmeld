$content = Get-Content 'C:\Users\gaura\ml-projects\mindmeld\uidump.xml' -Raw
$content = $content -replace '><node', "`n<node"
$lines = $content -split "`n"
foreach ($line in $lines) {
    if ($line -match 'No thanks|Continue|No|thanks') {
        Write-Host $line
    }
}
