$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))
$directory = "config/organizations-demo.json"
if (-not (Test-Path -LiteralPath $directory)) {
    python -m scripts.provision_organization init-demo $directory
    if ($LASTEXITCODE -ne 0) { throw "Organization demo provisioning failed" }
}
docker compose -f docker-compose.yml -f docker-compose.org-demo.yml up -d --build
if ($LASTEXITCODE -ne 0) { throw "Docker startup failed" }
$ready = $null
for ($attempt = 0; $attempt -lt 150; $attempt++) {
    try {
        $ready = Invoke-RestMethod http://127.0.0.1:8000/ready -TimeoutSec 3
        break
    } catch {
        Start-Sleep -Seconds 2
    }
}
if ($null -eq $ready) { throw "Gateway did not become ready; inspect docker compose logs gateway" }
$ready
