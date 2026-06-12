$content = Get-Content 'C:\Users\gaura\ml-projects\mindmeld\uidump.xml' -Raw
$content = $content -replace '><node', "`n<node"
$lines = $content -split "`n"
foreach ($line in $lines) {
    if ($line -match 'content-desc="[^"]{2,}"') {
        $desc = ''
        $bounds = ''
        $clickable = ''
        if ($line -match 'content-desc="([^"]*)"') { $desc = $Matches[1] }
        if ($line -match 'bounds="([^"]*)"') { $bounds = $Matches[1] }
        if ($line -match 'clickable="([^"]*)"') { $clickable = $Matches[1] }
        Write-Host "[$bounds] clickable=$clickable '$desc'"
    }
}
