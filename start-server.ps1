# Naukri AI Job Agent - Start Script
# Provisions Azure infrastructure, installs dependencies, and launches servers.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }

function Write-Step($msg) { Write-Host "`n[STEP] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host " [ERR] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   Naukri AI Job Agent - Setup & Launch     " -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# ----------------------------------------------------------
# STEP 0 - Prerequisites check
# ----------------------------------------------------------
Write-Step "Checking prerequisites..."

$prereqFailed = $false

# Temporarily allow non-terminating errors while probing external tools
$savedPref = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"

# Azure CLI
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Fail "Azure CLI (az) is not installed."
    Write-Host "  Install from: https://aka.ms/installazurecliwindows" -ForegroundColor Yellow
    $prereqFailed = $true
} else {
    $azVerRaw = (az --version 2>&1) | Where-Object { $_ -match '^azure-cli' } | Select-Object -First 1
    $azVer = "$azVerRaw" -replace 'azure-cli\s*',''
    Write-Ok "Azure CLI      : $azVer"
}

# Terraform
if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
    Write-Fail "Terraform is not installed."
    Write-Host "  Install from: https://developer.hashicorp.com/terraform/install" -ForegroundColor Yellow
    $prereqFailed = $true
} else {
    $tfVerLine = (terraform --version 2>&1) | Select-Object -First 1
    $tfVer = "$tfVerLine" -replace 'Terraform v',''
    Write-Ok "Terraform      : $tfVer"
}

# Python (>=3.9)
$pythonExe = $null
foreach ($candidate in @('python', 'python3', 'C:\Program Files\Python313\python.exe',
                          'C:\Program Files\Python312\python.exe',
                          'C:\Program Files\Python311\python.exe',
                          'C:\Program Files\Python310\python.exe',
                          'C:\Program Files\Python39\python.exe')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) {
        $ver = (& $cmd.Source --version 2>&1) | Select-Object -First 1
        if ("$ver" -match 'Python (\d+)\.(\d+)') {
            $major = [int]$matches[1]; $minor = [int]$matches[2]
            if ($major -ge 3 -and $minor -ge 9) {
                $pythonExe = $cmd.Source
                Write-Ok "Python         : $ver  ($pythonExe)"
                break
            }
        }
    }
}
if (-not $pythonExe) {
    Write-Fail "Python 3.9+ is not installed or not in PATH."
    Write-Host "  Install from: https://www.python.org/downloads/" -ForegroundColor Yellow
    $prereqFailed = $true
}

# Node.js
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Fail "Node.js is not installed."
    Write-Host "  Install from: https://nodejs.org/en/download" -ForegroundColor Yellow
    $prereqFailed = $true
} else {
    $nodeVer = (node --version 2>&1) | Select-Object -First 1
    Write-Ok "Node.js        : $nodeVer"
}

# npm
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Fail "npm is not installed (should come with Node.js)."
    $prereqFailed = $true
} else {
    $npmVer = (npm --version 2>&1) | Select-Object -First 1
    Write-Ok "npm            : $npmVer"
}

$ErrorActionPreference = $savedPref

if ($prereqFailed) {
    Write-Host ""
    Write-Fail "One or more prerequisites are missing. Install them and re-run this script."
    exit 1
}

# ----------------------------------------------------------
# STEP 1 - Validate Azure login
# ----------------------------------------------------------
Write-Step "Validating Azure login..."

$azCheck = az account show 2>&1 | Where-Object { $_ -notmatch '^WARNING' }
if ($LASTEXITCODE -ne 0) {
    Write-Fail "You are not logged in to Azure."
    Write-Host ""
    Write-Host "  Please run the following command and then re-run this script:" -ForegroundColor Yellow
    Write-Host "      az login" -ForegroundColor White
    Write-Host ""
    exit 1
}

$accountJson  = $azCheck | ConvertFrom-Json
$subscription = $accountJson.name
$tenantId     = $accountJson.tenantId
Write-Ok "Logged in - Subscription: $subscription  |  Tenant: $tenantId"

# ----------------------------------------------------------
# STEP 2 - Provision Azure resources with Terraform
# ----------------------------------------------------------
Write-Step "Provisioning Azure resources with Terraform..."

$tfDir = Join-Path $root "terraform"
if (-not (Test-Path $tfDir)) {
    Write-Fail "Terraform directory not found at: $tfDir"
    exit 1
}

# Copy example tfvars if no tfvars file exists yet
$tfvars        = Join-Path $tfDir "terraform.tfvars"
$tfvarsExample = Join-Path $tfDir "terraform.tfvars.example"
if (-not (Test-Path $tfvars) -and (Test-Path $tfvarsExample)) {
    Copy-Item $tfvarsExample $tfvars
    Write-Warn "terraform.tfvars not found - copied from terraform.tfvars.example. Edit it before re-running if needed."
}

Push-Location $tfDir

Write-Warn "Running terraform init..."
terraform init -upgrade
if ($LASTEXITCODE -ne 0) { Write-Fail "terraform init failed."; Pop-Location; exit 1 }

Write-Warn "Running terraform apply..."
terraform apply --auto-approve
if ($LASTEXITCODE -ne 0) { Write-Fail "terraform apply failed."; Pop-Location; exit 1 }

# Read resource identifiers from Terraform outputs (names only - used for az CLI queries)
$tfOutputJson = terraform output -json | ConvertFrom-Json
$tfRgName     = $tfOutputJson.resource_group_name.value

Pop-Location

Write-Ok "Terraform apply complete. Discovering Azure AI configuration dynamically..."

# ----------------------------------------------------------
# STEP 3 - Dynamically discover Azure AI config via az CLI
# ----------------------------------------------------------
Write-Step "Discovering Azure OpenAI configuration from Azure..."

# Find all OpenAI Cognitive Services accounts in the resource group
$cogAccounts = az cognitiveservices account list `
    --resource-group $tfRgName `
    --query "[?kind=='OpenAI']" `
    --output json 2>&1 | ConvertFrom-Json

if (-not $cogAccounts -or $cogAccounts.Count -eq 0) {
    Write-Fail "No Azure OpenAI account found in resource group '$tfRgName'."
    exit 1
}

# Use the first OpenAI account found
$cogAccount      = $cogAccounts[0]
$openaiAccountName = $cogAccount.name
$openaiEndpoint    = $cogAccount.properties.endpoint
Write-Ok "Found OpenAI account  : $openaiAccountName"
Write-Ok "Endpoint              : $openaiEndpoint"

# Get the primary key dynamically from az CLI
$keysJson   = az cognitiveservices account keys list `
    --name $openaiAccountName `
    --resource-group $tfRgName `
    --output json 2>&1 | ConvertFrom-Json
$openaiKey  = $keysJson.key1
if (-not $openaiKey) {
    Write-Fail "Could not retrieve API key for account '$openaiAccountName'."
    exit 1
}
Write-Ok "Primary key           : ****** (retrieved dynamically)"

# Discover all deployments and pick the first active one
$deploymentsJson = az cognitiveservices account deployment list `
    --name $openaiAccountName `
    --resource-group $tfRgName `
    --output json 2>&1 | ConvertFrom-Json

if (-not $deploymentsJson -or $deploymentsJson.Count -eq 0) {
    Write-Fail "No deployments found in account '$openaiAccountName'."
    exit 1
}

# Prefer a deployment whose provisioning state is Succeeded
$activeDeployment = $deploymentsJson | Where-Object { $_.properties.provisioningState -eq "Succeeded" } | Select-Object -First 1
if (-not $activeDeployment) { $activeDeployment = $deploymentsJson[0] }

$openaiDeployment  = $activeDeployment.name
$openaiModelName   = $activeDeployment.properties.model.name
$openaiModelVer    = $activeDeployment.properties.model.version
Write-Ok "Active deployment     : $openaiDeployment  (model: $openaiModelName $openaiModelVer)"

# Use a known-good API version for Azure OpenAI - prefer newer ones
$openaiApiVersion = "2025-01-01-preview"
# Override with anything already set in .env (user may pin a specific version)
$envFile = Join-Path $root ".env"
$existingEnv = @{}
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match "^\s*([^#=\s][^=]*?)\s*=\s*(.*)\s*$") {
            $existingEnv[$matches[1]] = $matches[2]
        }
    }
    if ($existingEnv.ContainsKey("AZURE_OPENAI_API_VERSION") -and $existingEnv["AZURE_OPENAI_API_VERSION"] -ne "") {
        $openaiApiVersion = $existingEnv["AZURE_OPENAI_API_VERSION"]
    }
}
Write-Ok "API version           : $openaiApiVersion"

# Build the merged env - Azure AI vars always come from live Azure discovery
$merged = [ordered]@{
    # Azure OpenAI - always refreshed from live Azure resources
    AZURE_OPENAI_ENDPOINT    = $openaiEndpoint
    AZURE_OPENAI_KEY         = $openaiKey
    AZURE_OPENAI_DEPLOYMENT  = $openaiDeployment
    AZURE_OPENAI_API_VERSION = $openaiApiVersion
    AZURE_OPENAI_ACCOUNT     = $openaiAccountName
    AZURE_OPENAI_MODEL       = $openaiModelName
    AZURE_RESOURCE_GROUP     = $tfRgName

    # Job search preferences - keep existing or set defaults
    JOB_KEYWORDS       = if ($existingEnv.ContainsKey("JOB_KEYWORDS"))       { $existingEnv["JOB_KEYWORDS"] }       else { "Python Developer" }
    JOB_LOCATION       = if ($existingEnv.ContainsKey("JOB_LOCATION"))       { $existingEnv["JOB_LOCATION"] }       else { "Bangalore" }
    EXPERIENCE_YEARS   = if ($existingEnv.ContainsKey("EXPERIENCE_YEARS"))   { $existingEnv["EXPERIENCE_YEARS"] }   else { "3" }
    MAX_APPLICATIONS   = if ($existingEnv.ContainsKey("MAX_APPLICATIONS"))   { $existingEnv["MAX_APPLICATIONS"] }   else { "50" }

    # Profile - keep existing values (user must edit .env to personalise)
    YOUR_NAME            = if ($existingEnv.ContainsKey("YOUR_NAME"))            { $existingEnv["YOUR_NAME"] }            else { "" }
    YOUR_EMAIL           = if ($existingEnv.ContainsKey("YOUR_EMAIL"))           { $existingEnv["YOUR_EMAIL"] }           else { "" }
    YOUR_PHONE           = if ($existingEnv.ContainsKey("YOUR_PHONE"))           { $existingEnv["YOUR_PHONE"] }           else { "" }
    YOUR_EXPERIENCE      = if ($existingEnv.ContainsKey("YOUR_EXPERIENCE"))      { $existingEnv["YOUR_EXPERIENCE"] }      else { "" }
    YOUR_SKILLS          = if ($existingEnv.ContainsKey("YOUR_SKILLS"))          { $existingEnv["YOUR_SKILLS"] }          else { "" }
    YOUR_EDUCATION       = if ($existingEnv.ContainsKey("YOUR_EDUCATION"))       { $existingEnv["YOUR_EDUCATION"] }       else { "" }
    YOUR_CURRENT_COMPANY = if ($existingEnv.ContainsKey("YOUR_CURRENT_COMPANY")) { $existingEnv["YOUR_CURRENT_COMPANY"] } else { "" }
    YOUR_CURRENT_ROLE    = if ($existingEnv.ContainsKey("YOUR_CURRENT_ROLE"))    { $existingEnv["YOUR_CURRENT_ROLE"] }    else { "" }
    YOUR_NOTICE_PERIOD   = if ($existingEnv.ContainsKey("YOUR_NOTICE_PERIOD"))   { $existingEnv["YOUR_NOTICE_PERIOD"] }   else { "" }
    YOUR_EXPECTED_CTC    = if ($existingEnv.ContainsKey("YOUR_EXPECTED_CTC"))    { $existingEnv["YOUR_EXPECTED_CTC"] }    else { "" }
    YOUR_CURRENT_CTC     = if ($existingEnv.ContainsKey("YOUR_CURRENT_CTC"))     { $existingEnv["YOUR_CURRENT_CTC"] }     else { "" }
}

# ----------------------------------------------------------
# STEP 3 cont. - Write .env and export to session
# ----------------------------------------------------------
Write-Step "Writing .env and exporting environment variables..."
foreach ($kv in $merged.GetEnumerator()) {
    $envLines += "$($kv.Key)=$($kv.Value)"
}
$envLines | Set-Content $envFile -Encoding UTF8

Write-Ok ".env written to: $envFile"

# Also export into current session so the spawned python process inherits them
foreach ($kv in $merged.GetEnumerator()) {
    [System.Environment]::SetEnvironmentVariable($kv.Key, $kv.Value, "Process")
}
Write-Ok "Environment variables exported to current session."

# Warn if profile fields are still empty
$emptyProfile = @("YOUR_NAME","YOUR_EMAIL","YOUR_PHONE") | Where-Object { -not $merged[$_] }
if ($emptyProfile) {
    Write-Warn "Profile fields are empty: $($emptyProfile -join ', '). Edit .env to personalise AI answers."
}

# ----------------------------------------------------------
# STEP 4 - Python virtual environment + pip install
# ----------------------------------------------------------
Write-Step "Setting up Python virtual environment..."

$venvDir      = Join-Path $root ".venv"
$venvActivate = Join-Path $venvDir "Scripts\Activate.ps1"
$venvPython   = Join-Path $venvDir "Scripts\python.exe"

# Clear any stale PYTHONHOME / PYTHONPATH that would break venv creation
$env:PYTHONHOME = ""
$env:PYTHONPATH = ""

if (-not (Test-Path $venvPython)) {
    Write-Warn ".venv not found - creating..."
    & $pythonExe -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { Write-Fail "Failed to create Python venv."; exit 1 }
    Write-Ok "Virtual environment created."
} else {
    Write-Ok "Virtual environment already exists."
}

# Activate
& $venvActivate

Write-Warn "Installing Python dependencies from requirements.txt..."
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r (Join-Path $root "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { Write-Fail "pip install failed."; exit 1 }
Write-Ok "Python dependencies installed."

# Install Playwright browser (Chromium) if not already installed
Write-Warn "Ensuring Playwright Chromium is installed..."
& $venvPython -m playwright install chromium 2>&1 | Out-Null
Write-Ok "Playwright Chromium ready."

# ----------------------------------------------------------
# STEP 5 - Frontend static assets (no Vite/esbuild needed)
# ----------------------------------------------------------
Write-Step "Checking frontend static assets..."

$webappDir  = Join-Path $root "webapp"
$staticDir  = Join-Path $webappDir "static"
$reactJs    = Join-Path $staticDir "react.js"
$reactDomJs = Join-Path $staticDir "react-dom.js"
$babelJs    = Join-Path $staticDir "babel.js"
$nodeModules = Join-Path $webappDir "node_modules"

if (-not (Test-Path (Join-Path $webappDir "package.json"))) {
    Write-Fail "webapp/package.json not found."
    exit 1
}

New-Item -ItemType Directory -Path $staticDir -Force | Out-Null

# Run npm install only if React UMD files are not yet in static/
if (-not (Test-Path $reactJs) -or -not (Test-Path $reactDomJs)) {
    Write-Warn "React UMD files missing - running npm install (no binaries)..."
    $savedPref = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
    taskkill /f /im esbuild.exe 2>&1 | Out-Null
    Get-Process -Name node -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    $ErrorActionPreference = $savedPref
    Start-Sleep -Seconds 1

    if (Test-Path $nodeModules) {
        $tmpDir = Join-Path $webappDir "_nm_del_$(Get-Date -Format 'HHmmss')"
        Rename-Item $nodeModules $tmpDir -ErrorAction SilentlyContinue
        cmd /c "rd /s /q `"$tmpDir`"" 2>&1 | Out-Null
    }

    $savedPref = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    Push-Location $webappDir
    npm install --omit=optional --ignore-scripts
    $npmExit = $LASTEXITCODE
    Pop-Location
    $ErrorActionPreference = $savedPref
    if ($npmExit -ne 0) { Write-Fail "npm install failed."; exit 1 }

    Copy-Item (Join-Path $nodeModules "react\umd\react.development.js")         $reactJs    -Force
    Copy-Item (Join-Path $nodeModules "react-dom\umd\react-dom.development.js") $reactDomJs -Force
    Write-Ok "React UMD files copied to static/."
} else {
    Write-Ok "React UMD files already present in static/."
}

# Download Babel standalone if missing
if (-not (Test-Path $babelJs) -or (Get-Item $babelJs -ErrorAction SilentlyContinue).Length -lt 100000) {
    Write-Warn "Downloading Babel standalone for in-browser JSX (2MB JS file)..."
    $savedPref = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
    curl.exe -sL --max-time 120 "https://unpkg.com/@babel/standalone/babel.min.js" -o $babelJs 2>&1 | Out-Null
    $ErrorActionPreference = $savedPref
    if ((Test-Path $babelJs) -and (Get-Item $babelJs).Length -gt 100000) {
        Write-Ok "Babel standalone ready ($([math]::Round((Get-Item $babelJs).Length/1MB,1))MB)."
    } else {
        Write-Fail "Could not download Babel standalone. Check proxy/network settings."
        exit 1
    }
} else {
    Write-Ok "Babel standalone already present in static/."
}

Write-Ok "Frontend served directly by FastAPI on http://localhost:8000"

# ----------------------------------------------------------
# STEP 6 - Launch backend server (API + frontend on port 8000)
# ----------------------------------------------------------
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  All setup complete! Starting server...   " -ForegroundColor Green
Write-Host "  Open: http://localhost:8000              " -ForegroundColor White
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop the server." -ForegroundColor Gray
Write-Host ""

Start-Sleep -Seconds 1
Start-Process "http://localhost:8000"

try {
    Set-Location $root
    & $venvPython server.py
} finally {
    Write-Host "`n[*] Server stopped." -ForegroundColor Green
}
