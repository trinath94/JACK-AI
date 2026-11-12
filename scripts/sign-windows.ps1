<#
.SYNOPSIS
  Authenticode-sign JACK AI installers with a PFX supplied via environment variables.

.DESCRIPTION
  WINDOWS_CERTIFICATE           base64-encoded .pfx
  WINDOWS_CERTIFICATE_PASSWORD  its password
  Uses signtool from the Windows SDK with SHA-256 and an RFC 3161 timestamp, then verifies.
  Fails the build if verification fails. Never run with a self-signed certificate for
  public releases.

  STATUS: written for Milestone 18 (decision D-2). Not yet exercised — no certificate is
  configured for this repository.
#>
param(
  [Parameter(Mandatory)] [string[]] $Files,
  [string] $TimestampUrl = "http://timestamp.digicert.com"
)
$ErrorActionPreference = "Stop"

$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" |
  Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) { throw "signtool.exe not found" }

$pfx = Join-Path $env:RUNNER_TEMP "jack-signing.pfx"
try {
  [IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:WINDOWS_CERTIFICATE))
  foreach ($f in $Files) {
    & $signtool.FullName sign /fd SHA256 /td SHA256 /tr $TimestampUrl `
      /f $pfx /p $env:WINDOWS_CERTIFICATE_PASSWORD $f
    if ($LASTEXITCODE -ne 0) { throw "signing failed: $f" }
    & $signtool.FullName verify /pa /v $f
    if ($LASTEXITCODE -ne 0) { throw "signature verification failed: $f" }
  }
}
finally {
  Remove-Item -Force -ErrorAction SilentlyContinue $pfx
}
