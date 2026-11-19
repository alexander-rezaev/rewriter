$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Ofline = Join-Path $Root "ofline"

New-Item -ItemType Directory -Force -Path $Ofline | Out-Null

Write-Host "Building rewriter:laptop..."
# Attestations wrap the image in a nested index. Older Docker then fails
# on `docker load` with an invalid image / unknown media type.
$env:BUILDX_NO_DEFAULT_ATTESTATIONS = "1"
docker compose -f (Join-Path $Root "docker-compose.yml") build
if ($LASTEXITCODE -ne 0) {
    throw "docker compose build failed"
}

Write-Host "Tagging rewriter:offline..."
docker tag rewriter:laptop rewriter:offline
if ($LASTEXITCODE -ne 0) {
    throw "docker tag failed"
}

$tar = Join-Path $Ofline "rewriter-images.tar"
$gz = Join-Path $Ofline "rewriter-images.tar.gz"
if (Test-Path $tar) { Remove-Item -Force $tar }
if (Test-Path $gz) { Remove-Item -Force $gz }

Write-Host "Saving $gz ..."
docker save rewriter:offline -o $tar
if ($LASTEXITCODE -ne 0) {
    throw "docker save failed"
}

# gzip the docker-save tar itself. `tar -czf` would wrap it in a second tar,
# and `gzip -dc | docker load` would fail with missing manifest.json.
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}
& $Python -c "import gzip, shutil, sys; src, dst = sys.argv[1], sys.argv[2]; f_in = open(src, 'rb'); f_out = gzip.open(dst, 'wb', compresslevel=6); shutil.copyfileobj(f_in, f_out, 1024 * 1024); f_in.close(); f_out.close()" $tar $gz
if ($LASTEXITCODE -ne 0) {
    throw "gzip failed"
}
Remove-Item -Force $tar
Write-Host "Wrote $gz"
