<#
.SYNOPSIS
    Canonical Warmer (playwarmer.vercel.app) production deploy, wrapped with a dirty-tree
    guard and a provenance log (reports/deploys.log).

.DESCRIPTION
    Wraps the exact deploy flow documented in README.md's "Web / PWA" section, in the same
    order, with no steps added, removed, or reordered:
      1. flutter build web --release --no-web-resources-cdn        (app/)
      2. scripts/check_web_plugin_registrant.py --project-dir app  (guard)
      3. scripts/check_authorized_domains.py --project-id mindmeld-c4bba
         --domain playwarmer.vercel.app                            (guard)
      4. scripts/make_web_sw.py --build-dir app\build\web, then copy into web-dist/
      5. npx vercel deploy --prod --yes                            (from web-dist/)
      6. firebase-tests/smoke_check.js                             (required post-deploy
         gate — per README/PLAN.md: "wired into the README's canonical deploy flow right
         after vercel deploy --prod --yes; documented as a required gate, not optional")

    Then, new in this script (not part of the manual flow): records
    "<ISO8601 UTC> sha=<full SHA> url=<deployment URL> target=production" to
    reports/deploys.log and commits+pushes that one file, so every production deploy has a
    provenance trail (added after the 2026-07-12 incident where the Vercel project was
    deleted and nobody could say when the last known-good deploy was).

    Payload publishing (`uv run publish` in generator/) is a separate, unrelated pipeline
    per README ("Publish payloads (unchanged...)") and is intentionally NOT run by this
    script — see the last block of README's Web/PWA section for that step.

.NOTES
    Refuses to run against a dirty working tree (staged, unstaged, or untracked changes) so
    the recorded commit SHA is unambiguous: it deploys and logs exactly what's at HEAD.

    Not run in CI; intended for interactive/manual invocation from a Windows dev machine
    with `flutter`, `uv`, `node`, and `vercel` (via `npx`) already set up, same as the
    manual README flow this wraps.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function Invoke-DeployStep {
    <#
    .SYNOPSIS
        Runs a native-command script block and throws if it exits non-zero.
    .DESCRIPTION
        PowerShell does not treat a non-zero exit code from a native executable as a
        terminating error by default, so $ErrorActionPreference = 'Stop' alone would not
        stop the script on a failed `flutter build`, guard script, etc. This wraps the call
        and checks $LASTEXITCODE explicitly.
    .PARAMETER Name
        Human-readable step name used in the thrown error message.
    .PARAMETER ScriptBlock
        The command to run.
    #>
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$ScriptBlock
    )
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $ScriptBlock
    if ($LASTEXITCODE -ne 0) {
        throw "Deploy step failed: $Name (exit code $LASTEXITCODE)"
    }
}

function Get-RepoRoot {
    <#
    .SYNOPSIS
        Returns the absolute path to the git repository root, Windows-style.
    .DESCRIPTION
        Lets this script be invoked from any working directory while every relative path in
        the wrapped flow (cd app, cd web-dist, scripts\..., etc.) still resolves correctly.
    #>
    $root = (& git rev-parse --show-toplevel 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($root)) {
        throw 'Not inside a git repository (git rev-parse --show-toplevel failed).'
    }
    return ($root -replace '/', '\')
}

try {
    $repoRoot = Get-RepoRoot
    Push-Location $repoRoot
    try {
        # --- 1. Refuse to run with a dirty working tree ---
        $status = & git status --porcelain
        if ($LASTEXITCODE -ne 0) {
            throw "git status failed (exit code $LASTEXITCODE)."
        }
        if (-not [string]::IsNullOrWhiteSpace(($status -join "`n"))) {
            Write-Host ($status -join "`n")
            throw 'Working tree is dirty (staged, unstaged, or untracked changes listed ' +
                'above). Commit or stash before deploying -- the provenance log records ' +
                "HEAD's SHA and must be unambiguous about what was actually deployed."
        }

        $deploySha = (& git rev-parse HEAD).Trim()
        $deployBranch = (& git rev-parse --abbrev-ref HEAD).Trim()
        Write-Host "Deploying HEAD $deploySha (branch $deployBranch)"

        # --- 2. flutter build web --release (README "Web / PWA", step 1) ---
        Push-Location (Join-Path $repoRoot 'app')
        try {
            Invoke-DeployStep -Name 'flutter build web --release' -ScriptBlock {
                flutter build web --release --no-web-resources-cdn
            }
        }
        finally {
            Pop-Location
        }

        # --- 3. Guard: Firebase web plugin registrant ---
        Invoke-DeployStep -Name 'check_web_plugin_registrant guard' -ScriptBlock {
            uv run python scripts\check_web_plugin_registrant.py --project-dir app
        }

        # --- 4. Guard: Firebase Auth authorized domains ---
        Invoke-DeployStep -Name 'check_authorized_domains guard' -ScriptBlock {
            uv run python scripts\check_authorized_domains.py `
                --project-id mindmeld-c4bba `
                --domain playwarmer.vercel.app
        }

        # --- 5. Generate/rotate the caching service worker, then stage into web-dist/ ---
        Invoke-DeployStep -Name 'make_web_sw.py' -ScriptBlock {
            uv run python scripts\make_web_sw.py --build-dir app\build\web
        }
        Copy-Item app\build\web\* web-dist\ -Recurse -Force

        # --- 6. vercel deploy --prod --yes, from web-dist/ (documented staging dir --
        #        deploying app\build\web\ directly is missing the tracked vercel.json/SW
        #        and has previously created a stray Vercel project silently, see PLAN.md
        #        Gotchas) ---
        Push-Location (Join-Path $repoRoot 'web-dist')
        $deployStdout = $null
        try {
            Write-Host '==> vercel deploy --prod --yes' -ForegroundColor Cyan
            # Deliberately NOT merging stderr (2>&1): vercel writes build/progress logs to
            # stderr and the production deployment URL to stdout as designed for scripting
            # (`URL=$(vercel deploy)`). Merging stderr here would also make PowerShell treat
            # every stderr line as a terminating error under $ErrorActionPreference = 'Stop',
            # aborting on benign progress output. Un-redirected stderr still prints to the
            # console for visibility.
            $deployStdout = & npx vercel deploy --prod --yes
            if ($LASTEXITCODE -ne 0) {
                throw "Deploy step failed: vercel deploy --prod --yes (exit code $LASTEXITCODE)"
            }
        }
        finally {
            Pop-Location
        }

        # vercel prints the production URL as (usually the only) stdout line; fall back to
        # the last https:// match in case a future CLI version adds extra stdout noise.
        # NOTE: must force array context with @(...) -- when vercel emits exactly one line
        # (its documented scripting-friendly behavior: URL only, all logs on stderr),
        # PowerShell unwraps a single-item pipeline result to a bare string, and `[-1]` on a
        # *string* indexes its last CHARACTER, not the last array element.
        $urlMatches = @(
            $deployStdout | Select-String -Pattern 'https://\S+' -AllMatches |
                ForEach-Object { $_.Matches.Value }
        )
        if ($urlMatches.Count -eq 0) {
            throw "Could not find a deployment URL in 'vercel deploy' stdout: $deployStdout"
        }
        $deployUrl = $urlMatches[-1]
        Write-Host "Deployment URL: $deployUrl"

        # --- 7. Post-deploy smoke check (required gate per README/PLAN.md -- a deploy is
        #        NOT done until this passes) ---
        Invoke-DeployStep -Name 'post-deploy smoke check' -ScriptBlock {
            node firebase-tests\smoke_check.js https://playwarmer.vercel.app/
        }

        # --- 8. Record provenance ---
        $timestamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        $logLine = "$timestamp  sha=$deploySha  url=$deployUrl  target=production"
        $reportsDir = Join-Path $repoRoot 'reports'
        # reports/ is not currently tracked in git (created ad hoc in a prior session for
        # Lighthouse baselines), so a fresh clone/worktree won't have it -- create it here
        # rather than let Add-Content fail on a missing parent directory AFTER a real deploy
        # already succeeded, which would be the worst possible place for this to error.
        if (-not (Test-Path -LiteralPath $reportsDir)) {
            New-Item -ItemType Directory -Path $reportsDir -Force | Out-Null
        }
        $logPath = Join-Path $reportsDir 'deploys.log'
        Add-Content -Path $logPath -Value $logLine
        Write-Host "Logged: $logLine"

        # --- 9. Commit + push the log line ---
        & git add $logPath
        if ($LASTEXITCODE -ne 0) { throw 'git add reports\deploys.log failed.' }
        $shortSha = $deploySha.Substring(0, 7)
        & git commit -m "chore(deploy): record production deploy $shortSha"
        if ($LASTEXITCODE -ne 0) { throw 'git commit failed.' }
        & git push origin $deployBranch
        if ($LASTEXITCODE -ne 0) { throw 'git push failed.' }

        Write-Host "Deploy complete: $deployUrl (sha $shortSha)" -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
}
catch {
    Write-Error "Deploy FAILED: $($_.Exception.Message)"
    exit 1
}
