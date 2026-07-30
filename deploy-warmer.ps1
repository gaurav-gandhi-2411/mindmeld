#Requires -Version 5.1
<#
.SYNOPSIS
    Canonical build + deploy pipeline for Warmer (playwarmer.vercel.app).

.DESCRIPTION
    Formalizes the manual command sequence documented in README.md's "Web / PWA"
    section into a single reusable script (referenced by spec.md's launch-1 wave
    and docs/runbook.md). Fails fast and loud at every gate -- a deploy that fails
    a guard script or the post-deploy smoke check leaves production UNCHANGED
    (Vercel only promotes a deployment to production once `vercel deploy --prod`
    completes; a script failure before that point means nothing was deployed).

    Mirrors README.md exactly -- if you change one, change the other.

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

function Invoke-NativeCommand {
    <#
    .SYNOPSIS
        Runs an external executable robustly against this script's global
        $ErrorActionPreference = 'Stop'.

    .DESCRIPTION
        Real incident (confirmed TWICE, with two unrelated tools): any
        native command's routine STDERR output -- not just genuine errors --
        gets treated as a script-terminating NativeCommandError the instant
        $ErrorActionPreference = 'Stop' is in effect. First seen with the
        vercel CLI (writes ordinary progress text like "Retrieving
        project..." to STDERR -- the deploy step failed on every run, even
        fully successful ones). Then seen AGAIN with a completely different
        tool once the vercel call was fixed: `uv run ...`'s own benign
        "warning: No `requires-python` value found" line crashed the very
        next step the same way. Two independent tools hitting the identical
        failure mode confirms this is a property of this script's global EAP
        setting, not something specific to vercel -- so every native-command
        call site in this script needs the same treatment, not just vercel's.

        Fix: capture combined stdout+stderr with $ErrorActionPreference
        temporarily set to 'Continue' -- scoped to ONLY this function's call
        (saved and restored via try/finally, never touching the caller's or
        the script's global value) -- then decide success/failure from
        $LASTEXITCODE, which is what actually reflects whether the command
        failed. Real PowerShell-level errors elsewhere in the script
        (cmdlet failures, thrown exceptions) are unaffected and still stop
        it immediately, since $ErrorActionPreference reverts the instant
        this function returns.

    .OUTPUTS
        The command's combined stdout+stderr lines (string array) -- callers
        that need to parse output (e.g. the deploy step's JSON "url" field)
        get it back; callers that just need success/failure can discard it.
    #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$Description = $FilePath
    )
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $FilePath @ArgumentList 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousEap
    }
    $output | ForEach-Object { Write-Host $_ }
    if ($exitCode -ne 0) {
        throw "$Description failed (exit code $exitCode) -- see output above."
    }
    return $output
}

function Invoke-VercelCommand {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [string]$Description = "vercel $($Arguments -join ' ')"
    )
    return Invoke-NativeCommand -FilePath 'npx' -ArgumentList (@('vercel') + $Arguments) -Description $Description
}

Invoke-Step "flutter build web (--wasm, ANALYTICS_ENABLED=true)" {
    Push-Location (Join-Path $repoRoot 'app')
    try {
        Invoke-NativeCommand -FilePath 'flutter' -Description "flutter build web" -ArgumentList @(
            'build', 'web', '--release', '--no-web-resources-cdn', '--wasm',
            '--dart-define=ANALYTICS_ENABLED=true'
        ) | Out-Null
    } finally {
        Pop-Location
    }
}

Invoke-Step "Guard: web plugin registrant check" {
    Push-Location $repoRoot
    try {
        Invoke-NativeCommand -FilePath 'uv' -Description "web plugin registrant check" -ArgumentList @(
            'run', 'python', 'scripts/check_web_plugin_registrant.py', '--project-dir', 'app'
        ) | Out-Null
    } finally {
        Pop-Location
    }
}

Invoke-Step "Guard: Firebase Auth authorized-domains check" {
    Push-Location $repoRoot
    try {
        Invoke-NativeCommand -FilePath 'uv' -Description "Firebase Auth authorized-domains check" -ArgumentList @(
            'run', 'python', 'scripts/check_authorized_domains.py',
            '--project-id', 'mindmeld-c4bba', '--domain', 'playwarmer.vercel.app'
        ) | Out-Null
    } finally {
        Pop-Location
    }
}

Invoke-Step "Generate caching service worker + copy vercel.json/FCM sw" {
    Push-Location $repoRoot
    try {
        Invoke-NativeCommand -FilePath 'uv' -Description "make_web_sw.py" -ArgumentList @(
            'run', 'python', 'scripts/make_web_sw.py', '--build-dir', 'app/build/web'
        ) | Out-Null
    } finally {
        Pop-Location
    }
}

Invoke-Step "Guard: web-dist/ must already be linked to the real playwarmer project" {
    # web-dist/.vercel/ is gitignored (staging dir only) so this link never
    # survives a fresh clone or a deleted web-dist/ directory. A real incident
    # (documented in PLAN.md, recurred once already during this wave): running
    # `vercel deploy --prod` from an UNLINKED directory does NOT error -- it
    # silently auto-creates and deploys to a brand-new stray project named
    # after the directory, leaving the real "playwarmer" project completely
    # untouched while every guard/smoke-check downstream still reports success
    # (they check the static playwarmer.vercel.app domain, which just keeps
    # serving the previous, unrelated deployment). Fail loudly here instead of
    # letting `vercel deploy` silently improvise -- one-time fix if this trips:
    # `cd web-dist && npx vercel link --yes --project=playwarmer`.
    $projectFile = Join-Path $repoRoot 'web-dist/.vercel/project.json'
    if (-not (Test-Path $projectFile)) {
        throw "web-dist/.vercel/project.json missing -- web-dist/ is not linked to any Vercel " +
            "project. Run: cd web-dist && npx vercel link --yes --project=playwarmer"
    }
    $linked = Get-Content $projectFile | ConvertFrom-Json
    if ($linked.projectName -ne 'playwarmer') {
        throw "web-dist/ is linked to '$($linked.projectName)', not 'playwarmer' -- " +
            "deploying now would silently update the WRONG project. Fix: " +
            "rm -rf web-dist/.vercel && cd web-dist && npx vercel link --yes --project=playwarmer"
    }
    Write-Host "  OK: web-dist/ linked to playwarmer ($($linked.projectId))"
}

Invoke-Step "Stage build into web-dist/" {
    $webDist = Join-Path $repoRoot 'web-dist'
    if (Test-Path $webDist) {
        # Exclude .vercel/ -- a bare `*` + -Force wipes hidden dirs too (verified
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

Invoke-Step "Guard: local wasm boot check (before ANY Vercel upload or promotion)" {
    # Real incident (2026-07-30, docs/known-limitations.md entry 23): a deploy
    # built successfully, byte-verified successfully, and PROMOTED to
    # production before anything checked that the app actually boots -- it
    # didn't (a silent eager-init hang), and production served a blank white
    # screen until the POST-deploy smoke check caught it, several minutes
    # after real users could have hit it. This step closes that gap: serve
    # the exact freshly-staged web-dist/ locally and require a clean boot
    # BEFORE web-dist/ is ever uploaded to Vercel, let alone promoted.
    #
    # Reuses smoke_check.js's own boot-detection (flt-glass-pane + sized
    # canvas, zero pageerror/requestfailed) against a local URL instead of
    # production -- one implementation, not a second copy of the same
    # Puppeteer logic. smoke_check.js already accepts an arbitrary target URL
    # as argv[1]; no changes to that script were needed.
    $localPort = 8322
    $webDist = Join-Path $repoRoot 'web-dist'
    $localUrl = "http://localhost:$localPort/"
    $serverOutLog = Join-Path $repoRoot 'web-dist-local-server.out.log'
    $serverErrLog = Join-Path $repoRoot 'web-dist-local-server.err.log'
    $serverProcess = $null
    try {
        $serverProcess = Start-Process -FilePath 'uv' `
            -ArgumentList @('run', 'python', '-m', 'http.server', $localPort, '--directory', $webDist) `
            -WorkingDirectory $repoRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $serverOutLog `
            -RedirectStandardError $serverErrLog `
            -PassThru

        $ready = $false
        for ($i = 0; $i -lt 30; $i++) {
            try {
                $resp = Invoke-WebRequest -Uri $localUrl -UseBasicParsing -TimeoutSec 2
                if ($resp.StatusCode -eq 200) { $ready = $true; break }
            } catch {
                Start-Sleep -Seconds 1
            }
        }
        if (-not $ready) {
            throw "Local server on port $localPort never became ready -- see $serverOutLog / $serverErrLog"
        }

        Invoke-NativeCommand -FilePath 'node' -Description "local pre-promotion boot check" -ArgumentList @(
            'firebase-tests/smoke_check.js', $localUrl
        ) | Out-Null
        Write-Host "  OK: freshly-built web-dist/ boots cleanly (local, pre-upload)"
    } finally {
        if ($serverProcess -and -not $serverProcess.HasExited) {
            # `Stop-Process` on $serverProcess.Id only kills the `uv` launcher
            # -- `uv run python -m http.server` spawns python as a CHILD
            # process on Windows (no exec-replace), which Stop-Process does
            # not cascade to, orphaning a live server still bound to the
            # port on every single deploy run (found while testing this gate
            # -- 4 leaked listeners on port 8322 after 4 deploy runs).
            # taskkill /T kills the whole process tree, not just the parent.
            & taskkill /PID $serverProcess.Id /T /F 2>&1 | Out-Null
        }
        Remove-Item $serverOutLog, $serverErrLog -ErrorAction SilentlyContinue
        # Unconditional, at the very end of finally, regardless of which
        # cleanup path ran above: taskkill's exit code (e.g. 128 if the
        # process already exited on its own before we got here) must NOT
        # leak out as this scriptblock's $LASTEXITCODE -- Invoke-Step checks
        # it AFTER this finally block runs and would otherwise fail an
        # already-successful boot check on pure cleanup noise (found while
        # testing this gate: the boot check printed PASS, then the step
        # still threw "exit 128" from taskkill's own code bleeding through).
        $global:LASTEXITCODE = 0
    }
}

$global:deploymentUrl = $null
Invoke-Step "Deploy to Vercel production" {
    Push-Location (Join-Path $repoRoot 'web-dist')
    try {
        # See Invoke-VercelCommand's docstring: vercel's own progress text on
        # STDERR must not be treated as a script-terminating error.
        $deployLines = Invoke-VercelCommand -Arguments @('deploy', '--prod', '--yes') `
            -Description "Vercel production deploy"
        # The JSON block is pretty-printed across multiple lines, so grab it by
        # matching the "url" key directly rather than trying to isolate/parse
        # a single JSON line (a prior version of this script tried the latter
        # and always failed to find it -- caught by this step's own throw,
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
    Invoke-VercelCommand -Arguments @('alias', 'set', $global:deploymentUrl, 'playwarmer.vercel.app') `
        -Description "Aliasing playwarmer.vercel.app to this deployment" | Out-Null
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
        try {
            Invoke-VercelCommand -Arguments @('cache', 'purge', '--yes') -Description "CDN cache purge" | Out-Null
        } finally { Pop-Location }
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
            Invoke-NativeCommand -FilePath 'node' -Description "post-deploy smoke check" -ArgumentList @(
                'firebase-tests/smoke_check.js', 'https://playwarmer.vercel.app/'
            ) | Out-Null
        } finally {
            Pop-Location
        }
    }
}

Write-Host "==> Deploy complete." -ForegroundColor Green
