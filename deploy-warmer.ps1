#Requires -Version 5.1
<#
.SYNOPSIS
    Canonical build + deploy pipeline for Warmer (playwarmer.vercel.app).

.DESCRIPTION
    Formalizes the manual command sequence documented in README.md's "Web / PWA"
    section into a single reusable script (referenced by spec.md's launch-1 wave
    and docs/runbook.md). Fails fast and loud at every gate — a deploy that fails
    a guard script or the post-deploy smoke check leaves production UNCHANGED
    (Vercel only promotes a deployment to production once `vercel deploy --prod`
    completes; a script failure before that point means nothing was deployed).

    Mirrors README.md exactly — if you change one, change the other.

.PARAMETER SkipSmokeCheck
    Skip the post-deploy smoke check. Only use this for the rollback exercise's
    own verification steps, where the smoke check is run as an explicit separate
    step against a specific deployment URL instead.

.EXAMPLE
    ./deploy-warmer.ps1
#>
param(
    [switch]$SkipSmokeCheck
)

$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot

function Invoke-Step {
    param([string]$Description, [scriptblock]$Action)
    Write-Host "==> $Description" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        throw "Step failed (exit $LASTEXITCODE): $Description"
    }
}

Invoke-Step "flutter build web (--wasm, ANALYTICS_ENABLED=true)" {
    Push-Location (Join-Path $repoRoot 'app')
    try {
        flutter build web --release --no-web-resources-cdn --wasm --dart-define=ANALYTICS_ENABLED=true
    } finally {
        Pop-Location
    }
}

Invoke-Step "Guard: web plugin registrant check" {
    Push-Location $repoRoot
    try {
        uv run python scripts/check_web_plugin_registrant.py --project-dir app
    } finally {
        Pop-Location
    }
}

Invoke-Step "Guard: Firebase Auth authorized-domains check" {
    Push-Location $repoRoot
    try {
        uv run python scripts/check_authorized_domains.py --project-id mindmeld-c4bba --domain playwarmer.vercel.app
    } finally {
        Pop-Location
    }
}

Invoke-Step "Generate caching service worker + copy vercel.json/FCM sw" {
    Push-Location $repoRoot
    try {
        uv run python scripts/make_web_sw.py --build-dir app/build/web
    } finally {
        Pop-Location
    }
}

Invoke-Step "Guard: web-dist/ must already be linked to the real playwarmer project" {
    # web-dist/.vercel/ is gitignored (staging dir only) so this link never
    # survives a fresh clone or a deleted web-dist/ directory. A real incident
    # (documented in PLAN.md, recurred once already during this wave): running
    # `vercel deploy --prod` from an UNLINKED directory does NOT error — it
    # silently auto-creates and deploys to a brand-new stray project named
    # after the directory, leaving the real "playwarmer" project completely
    # untouched while every guard/smoke-check downstream still reports success
    # (they check the static playwarmer.vercel.app domain, which just keeps
    # serving the previous, unrelated deployment). Fail loudly here instead of
    # letting `vercel deploy` silently improvise — one-time fix if this trips:
    # `cd web-dist && npx vercel link --yes --project=playwarmer`.
    $projectFile = Join-Path $repoRoot 'web-dist/.vercel/project.json'
    if (-not (Test-Path $projectFile)) {
        throw "web-dist/.vercel/project.json missing — web-dist/ is not linked to any Vercel " +
            "project. Run: cd web-dist && npx vercel link --yes --project=playwarmer"
    }
    $linked = Get-Content $projectFile | ConvertFrom-Json
    if ($linked.projectName -ne 'playwarmer') {
        throw "web-dist/ is linked to '$($linked.projectName)', not 'playwarmer' — " +
            "deploying now would silently update the WRONG project. Fix: " +
            "rm -rf web-dist/.vercel && cd web-dist && npx vercel link --yes --project=playwarmer"
    }
    Write-Host "  OK: web-dist/ linked to playwarmer ($($linked.projectId))"
}

Invoke-Step "Stage build into web-dist/" {
    $webDist = Join-Path $repoRoot 'web-dist'
    if (Test-Path $webDist) {
        # Exclude .vercel/ — a bare `*` + -Force wipes hidden dirs too (verified
        # empirically), which would silently delete the project link the guard
        # step above just checked, forcing a re-link on every single deploy.
        Get-ChildItem -Path $webDist -Force |
            Where-Object { $_.Name -ne '.vercel' } |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        New-Item -ItemType Directory -Path $webDist | Out-Null
    }
    Copy-Item (Join-Path $repoRoot 'app/build/web/*') $webDist -Recurse -Force
}

$global:deploymentUrl = $null
Invoke-Step "Deploy to Vercel production" {
    Push-Location (Join-Path $repoRoot 'web-dist')
    try {
        $deployLines = npx vercel deploy --prod --yes 2>&1
        $deployLines | ForEach-Object { Write-Host $_ }
        # The JSON block is pretty-printed across multiple lines, so grab it by
        # matching the "url" key directly rather than trying to isolate/parse
        # a single JSON line (a prior version of this script tried the latter
        # and always failed to find it — caught by this step's own throw,
        # not silently, but fixing the root cause here).
        $urlLine = $deployLines | Where-Object { $_ -match '^\s*"url":\s*"(https://[^"]+)"' } | Select-Object -First 1
        if ($urlLine -and $urlLine -match '"url":\s*"(https://[^"]+)"') {
            $global:deploymentUrl = $matches[1]
        }
    } finally {
        Pop-Location
    }
}

Invoke-Step "Guard: explicitly re-point playwarmer.vercel.app at THIS deployment" {
    # Real incident, launch-1 wave: `vercel deploy --prod` stopped auto-updating
    # the short playwarmer.vercel.app alias partway through a session (instead
    # only aliasing to the longer auto-generated *-gaurav-gandhi-2411s-
    # projects.vercel.app form) -- silently, with no error, and every
    # downstream check (smoke check, Lighthouse, screenshots) kept passing
    # because they only proved SOME build boots, not THIS ONE specifically.
    # Root cause not fully determined; this step makes the canonical domain's
    # target explicit and verified on every deploy instead of trusting
    # `vercel deploy`'s own automatic aliasing.
    if (-not $global:deploymentUrl) {
        throw "Could not parse the deployment URL from 'vercel deploy' output -- " +
            "cannot verify playwarmer.vercel.app points at what was just deployed."
    }
    npx vercel alias set $global:deploymentUrl playwarmer.vercel.app
    if ($LASTEXITCODE -ne 0) {
        throw "vercel alias set failed (exit $LASTEXITCODE) -- playwarmer.vercel.app may not point at this deployment."
    }
}

Invoke-Step "Guard: verify playwarmer.vercel.app actually serves THIS build" {
    # Belt-and-suspenders on top of the alias step above: fetch the live
    # main.dart.wasm and compare its byte size to the one just built. A
    # mismatch means either the alias didn't take (see above) or an edge
    # cache is serving stale content despite Cache-Control -- purge and
    # re-check once before failing loudly (a purge was needed once already
    # this wave even after a correct alias update).
    $localSize = (Get-Item (Join-Path $repoRoot 'web-dist/main.dart.wasm')).Length
    Start-Sleep -Seconds 3
    $remoteSize = (Invoke-WebRequest -Uri 'https://playwarmer.vercel.app/main.dart.wasm' -UseBasicParsing).RawContentLength
    if ($remoteSize -ne $localSize) {
        Write-Host "  Mismatch (local $localSize vs live $remoteSize) -- purging CDN cache and re-checking once..." -ForegroundColor Yellow
        Push-Location (Join-Path $repoRoot 'web-dist')
        try { npx vercel cache purge --yes } finally { Pop-Location }
        Start-Sleep -Seconds 3
        $remoteSize = (Invoke-WebRequest -Uri 'https://playwarmer.vercel.app/main.dart.wasm' -UseBasicParsing).RawContentLength
    }
    if ($remoteSize -ne $localSize) {
        throw "playwarmer.vercel.app is STILL serving a different main.dart.wasm size " +
            "(local $localSize vs live $remoteSize) after an alias fix and a cache purge -- " +
            "do not trust this deploy; investigate before relying on any measurement against it."
    }
    Write-Host "  OK: live main.dart.wasm matches this build ($localSize bytes)"
}

if (-not $SkipSmokeCheck) {
    Invoke-Step "Post-deploy smoke check (required)" {
        Push-Location $repoRoot
        try {
            node firebase-tests/smoke_check.js https://playwarmer.vercel.app/
        } finally {
            Pop-Location
        }
    }
}

Write-Host "==> Deploy complete." -ForegroundColor Green
