param(
    [Parameter(Mandatory = $true)][string]$ExpectedArtifactSha256,
    [Parameter(Mandatory = $true)][switch]$RightsReviewed
)
$ErrorActionPreference = 'Stop'
if (-not $RightsReviewed) {
    throw 'Artifact packaging blocked: review dataset provenance and derived-model rights, then pass -RightsReviewed.'
}
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$artifact = Join-Path $repoRoot 'ml-training\models\url-char-tfidf-v0.1.0-research.joblib'
if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) { throw "Expected research artifact not found: $artifact" }
$actual = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ExpectedArtifactSha256 -notmatch '^[0-9a-fA-F]{64}$' -or $actual -ne $ExpectedArtifactSha256.ToLowerInvariant()) {
    throw "Artifact SHA-256 does not match the reviewed digest. Actual: $actual"
}
$context = Join-Path ([IO.Path]::GetTempPath()) ("anarisk-url-staging-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $context | Out-Null
try {
    foreach ($name in @('Dockerfile.staging', 'requirements.txt', 'requirements-url-staging.txt', 'alembic.ini')) {
        Copy-Item -LiteralPath (Join-Path $repoRoot "backend\$name") -Destination $context
    }
    foreach ($name in @('alembic', 'app')) { Copy-Item -LiteralPath (Join-Path $repoRoot "backend\$name") -Destination $context -Recurse }
    New-Item -ItemType Directory -Path (Join-Path $context 'docker'), (Join-Path $context 'scripts\staging'), (Join-Path $context 'staging-artifact') -Force | Out-Null
    Copy-Item (Join-Path $repoRoot 'backend\docker\entrypoint.sh') (Join-Path $context 'docker')
    Copy-Item (Join-Path $repoRoot 'backend\docker\staging-entrypoint.sh') (Join-Path $context 'docker')
    Copy-Item (Join-Path $repoRoot 'backend\scripts\staging\validate_url_model.py') (Join-Path $context 'scripts\staging')
    Copy-Item -LiteralPath $artifact -Destination (Join-Path $context 'staging-artifact\url-char-tfidf-v0.1.0-research.joblib')
    Write-Output "Staging build context prepared: $context"
    Write-Output "Artifact SHA-256: $actual"
    Write-Output 'Build locally with: docker build -f Dockerfile.staging -t anarisk-url-shadow:staging .'
} catch {
    Remove-Item -LiteralPath $context -Recurse -Force -ErrorAction SilentlyContinue
    throw
}
