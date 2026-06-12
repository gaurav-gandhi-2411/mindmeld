$content = Get-Content 'C:\Users\gaura\ml-projects\mindmeld\uidump.xml' -Raw
$content = $content -replace '><node', "`n<node"
$lines = $content -split "`n"
foreach ($line in $lines) {
    if ($line -match 'clickable="true"|text="[^"]{3,}"') {
        $text = ''
        $bounds = ''
        if ($line -match 'text="([^"]*)"') { $text = $Matches[1] }
        if ($line -match 'bounds="([^"]*)"') { $bounds = $Matches[1] }
        Write-Host "[$bounds] '$text'"
    }
}
