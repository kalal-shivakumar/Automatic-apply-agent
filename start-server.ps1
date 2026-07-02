# Naukri AI Job Agent - Start Script
# Provisions Azure infrastructure, installs dependencies, and launches servers.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }

function Write-Step($msg) { Write-Host "`n[STEP] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host " [ERR] $msg" -ForegroundColor Red }

function Refresh-Path {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Install-WithWinget($id, $name) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Warn "winget is not available. Cannot auto-install $name."
        return $false
    }

    Write-Warn "Attempting to install $name via winget..."
    winget install --id $id --exact --accept-package-agreements --accept-source-agreements --silent 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "winget install failed for $name (id: $id)."
        return $false
    }

    Refresh-Path
    Write-Ok "$name installation completed via winget."
    return $true
}

function Find-Python39Plus {
    foreach ($candidate in @('python', 'python3', 'py',
                              'C:\Program Files\Python313\python.exe',
                              'C:\Program Files\Python312\python.exe',
                              'C:\Program Files\Python311\python.exe',
                              'C:\Program Files\Python310\python.exe',
                              'C:\Program Files\Python39\python.exe')) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }

        $source = $cmd.Source
        if (-not $source) { continue }

        $ver = (& $source --version 2>&1) | Select-Object -First 1
        if ("$ver" -match 'Python (\d+)\.(\d+)') {
            $major = [int]$matches[1]
            $minor = [int]$matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 9)) {
                return [pscustomobject]@{
                    Path    = $source
                    Version = "$ver"
                }
            }
        }
    }

    return $null
}

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

# Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Warn "Git is not installed."
    $gitInstalled = Install-WithWinget "Git.Git" "Git"
    if (-not $gitInstalled -or -not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Fail "Git is not installed."
        Write-Host "  Install from: https://git-scm.com/download/win" -ForegroundColor Yellow
        $prereqFailed = $true
    } else {
        $gitVer = (git --version 2>&1) | Select-Object -First 1
        Write-Ok "Git            : $gitVer"
    }
} else {
    $gitVer = (git --version 2>&1) | Select-Object -First 1
    Write-Ok "Git            : $gitVer"
}

# Azure CLI
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Warn "Azure CLI (az) is not installed."
    $azInstalled = Install-WithWinget "Microsoft.AzureCLI" "Azure CLI"
    if (-not $azInstalled -or -not (Get-Command az -ErrorAction SilentlyContinue)) {
        Write-Fail "Azure CLI (az) is not installed."
        Write-Host "  Install from: https://aka.ms/installazurecliwindows" -ForegroundColor Yellow
        $prereqFailed = $true
    } else {
        $azVerRaw = (az --version 2>&1) | Where-Object { $_ -match '^azure-cli' } | Select-Object -First 1
        $azVer = "$azVerRaw" -replace 'azure-cli\s*',''
        Write-Ok "Azure CLI      : $azVer"
    }
} else {
    $azVerRaw = (az --version 2>&1) | Where-Object { $_ -match '^azure-cli' } | Select-Object -First 1
    $azVer = "$azVerRaw" -replace 'azure-cli\s*',''
    Write-Ok "Azure CLI      : $azVer"
}

# Terraform
if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
    Write-Warn "Terraform is not installed."
    $tfInstalled = Install-WithWinget "Hashicorp.Terraform" "Terraform"
    if (-not $tfInstalled -or -not (Get-Command terraform -ErrorAction SilentlyContinue)) {
        Write-Fail "Terraform is not installed."
        Write-Host "  Install from: https://developer.hashicorp.com/terraform/install" -ForegroundColor Yellow
        $prereqFailed = $true
    } else {
        $tfVerLine = (terraform --version 2>&1) | Select-Object -First 1
        $tfVer = "$tfVerLine" -replace 'Terraform v',''
        Write-Ok "Terraform      : $tfVer"
    }
} else {
    $tfVerLine = (terraform --version 2>&1) | Select-Object -First 1
    $tfVer = "$tfVerLine" -replace 'Terraform v',''
    Write-Ok "Terraform      : $tfVer"
}

# Python (>=3.9)
$pythonInfo = Find-Python39Plus
if (-not $pythonInfo) {
    Write-Warn "Python 3.9+ is not installed or not in PATH."
    $pyInstalled = Install-WithWinget "Python.Python.3.9" "Python 3.9"
    if (-not $pyInstalled) {
        $pyInstalled = Install-WithWinget "Python.Python.3" "Python 3"
    }

    $pythonInfo = Find-Python39Plus
    if (-not $pyInstalled -or -not $pythonInfo) {
        Write-Fail "Python 3.9+ is not installed or not in PATH."
        Write-Host "  Install from: https://www.python.org/downloads/" -ForegroundColor Yellow
        $prereqFailed = $true
    } else {
        Write-Ok "Python         : $($pythonInfo.Version)  ($($pythonInfo.Path))"
    }
} else {
    Write-Ok "Python         : $($pythonInfo.Version)  ($($pythonInfo.Path))"
}

# Node.js
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Warn "Node.js is not installed."
    $nodeInstalled = Install-WithWinget "OpenJS.NodeJS.LTS" "Node.js LTS"
    if (-not $nodeInstalled -or -not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Fail "Node.js is not installed."
        Write-Host "  Install from: https://nodejs.org/en/download" -ForegroundColor Yellow
        $prereqFailed = $true
    } else {
        $nodeVer = (node --version 2>&1) | Select-Object -First 1
        Write-Ok "Node.js        : $nodeVer"
    }
} else {
    $nodeVer = (node --version 2>&1) | Select-Object -First 1
    Write-Ok "Node.js        : $nodeVer"
}

# npm
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Warn "npm is not installed (should come with Node.js)."
    $npmInstalled = Install-WithWinget "OpenJS.NodeJS.LTS" "Node.js LTS"
    if (-not $npmInstalled -or -not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Fail "npm is not installed (should come with Node.js)."
        Write-Host "  Install from: https://nodejs.org/en/download" -ForegroundColor Yellow
        $prereqFailed = $true
    } else {
        $npmVer = (npm --version 2>&1) | Select-Object -First 1
        Write-Ok "npm            : $npmVer"
    }
} else {
    $npmVer = (npm --version 2>&1) | Select-Object -First 1
    Write-Ok "npm            : $npmVer"
}

$ErrorActionPreference = $savedPref

if ($prereqFailed) {
    Write-Host ""
    Write-Fail "One or more prerequisites are missing. Install/fix them and re-run this script."
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
# STEP 3 cont. - Clear stale system env vars + Write .env + export to session
# ----------------------------------------------------------
Write-Step "Writing .env and exporting environment variables..."

# First, clear any stale system environment variables from previous sessions
# These can override .env values if not cleared
$staleVars = @('AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_KEY', 'AZURE_OPENAI_DEPLOYMENT',
               'AZURE_OPENAI_API_VERSION', 'AZURE_OPENAI_ACCOUNT', 'AZURE_OPENAI_MODEL',
               'AZURE_RESOURCE_GROUP')
foreach ($var in $staleVars) {
    $oldVal = [System.Environment]::GetEnvironmentVariable($var, 'User')
    if ($oldVal) {
        [System.Environment]::SetEnvironmentVariable($var, '', 'User')
        Write-Warn "Cleared stale $var from User environment"
    }
}

# Write .env file with proper formatting (each var on own line) and NO UTF-8 BOM
$envLines = @()
foreach ($kv in $merged.GetEnumerator()) {
    $envLines += "$($kv.Key)=$($kv.Value)"
}
$envContent = $envLines -join "`n"
$utf8NoBOM = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($envFile, $envContent, $utf8NoBOM)

Write-Ok ".env written to: $envFile"

# Export into current Process environment (not User, to avoid persistence)
# These will be inherited by spawned Python process
foreach ($kv in $merged.GetEnumerator()) {
    Set-Item -Path "env:$($kv.Key)" -Value $kv.Value
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

# Validate required runtime modules are importable
Write-Warn "Validating required Python modules..."
$depsCheckScript = @"
import importlib
import sys

required = [
    ("openai", "openai"),
    ("dotenv", "python-dotenv"),
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("websockets", "websockets"),
    ("aiofiles", "aiofiles"),
    ("playwright", "playwright"),
    ("pypdf", "pypdf"),
]

missing = []
for mod_name, pkg_name in required:
    try:
        importlib.import_module(mod_name)
    except Exception:
        missing.append(pkg_name)

if missing:
    print("MISSING=" + ",".join(missing))
    sys.exit(2)

print("ALL_REQUIRED_MODULES_OK")
"@

$depsCheckFile = Join-Path $root "_check_deps.py"
[System.IO.File]::WriteAllText($depsCheckFile, $depsCheckScript, [System.Text.UTF8Encoding]::new($false))
$depsOutput = & $venvPython $depsCheckFile 2>&1
$depsExit = $LASTEXITCODE
Remove-Item $depsCheckFile -ErrorAction SilentlyContinue

if ($depsExit -ne 0) {
    Write-Warn "Some modules are missing after requirements install. Attempting recovery install..."
    if ("$depsOutput" -match "MISSING=(.*)") {
        $missingPkgs = $matches[1].Split(',') | Where-Object { $_ -and $_.Trim() -ne "" }
        if ($missingPkgs.Count -gt 0) {
            & $venvPython -m pip install $missingPkgs
            if ($LASTEXITCODE -ne 0) {
                Write-Fail "Failed to install missing modules: $($missingPkgs -join ', ')"
                exit 1
            }
            Write-Ok "Recovered missing modules: $($missingPkgs -join ', ')"
        } else {
            Write-Fail "Dependency validation failed, but missing package list could not be parsed."
            Write-Host "  $depsOutput"
            exit 1
        }
    } else {
        Write-Fail "Dependency validation failed."
        Write-Host "  $depsOutput"
        exit 1
    }
} else {
    Write-Ok "All required Python modules are available (including pypdf)."
}

# Install Playwright browser (Chromium) if not already installed
Write-Warn "Ensuring Playwright Chromium is installed..."
& $venvPython -m playwright install chromium 2>&1 | Out-Null
Write-Ok "Playwright Chromium ready."

# ----------------------------------------------------------
# STEP 5 - Validate and apply code fixes (config.py, ai_answerer.py)
# ----------------------------------------------------------
Write-Step "Validating Python code fixes..."

$configPy = Join-Path $root "config.py"
$aiAnswererPy = Join-Path $root "ai_answerer.py"

# Fix 1: Ensure config.py has load_dotenv(override=True)
if (Test-Path $configPy) {
    $configContent = Get-Content $configPy -Raw
    if ($configContent -match 'load_dotenv\(\)') {
        Write-Warn "config.py has load_dotenv() without override=True - fixing..."
        $configContent = $configContent -replace 'load_dotenv\(\)', 'load_dotenv(override=True)'
        [System.IO.File]::WriteAllText($configPy, $configContent, [System.Text.UTF8Encoding]::new($false))
        Write-Ok "config.py patched: load_dotenv(override=True)"
    } elseif ($configContent -match 'load_dotenv\(override=True\)') {
        Write-Ok "config.py already has load_dotenv(override=True)"
    }
}

# Fix 2: Ensure ai_answerer.py has SSL verification bypass (httpx client)
if (Test-Path $aiAnswererPy) {
    $aiContent = Get-Content $aiAnswererPy -Raw
    if (-not ($aiContent -match '_get_http_client')) {
        Write-Warn "ai_answerer.py missing SSL bypass - fixing..."
        
        # Add the _get_http_client static method after __init__
        $insertCode = @"

    @staticmethod
    def _get_http_client():
        """Create HTTP client with SSL verification disabled for corporate proxy environments"""
        import httpx
        return httpx.Client(verify=False)
"@
        
        # Find the end of __init__ and insert after it
        $aiContent = $aiContent -replace '(self\.search_criteria = _load_search_criteria\(\))', "`$1`n$insertCode"
        
        # Also update __init__ to use the http_client parameter
        $aiContent = $aiContent -replace 'AzureOpenAI\(\s*azure_endpoint=', "AzureOpenAI(`n            http_client=self._get_http_client(),  # SSL verification disabled for corporate proxy`n            azure_endpoint="
        
        [System.IO.File]::WriteAllText($aiAnswererPy, $aiContent, [System.Text.UTF8Encoding]::new($false))
        Write-Ok "ai_answerer.py patched: added _get_http_client() method"
    } else {
        Write-Ok "ai_answerer.py already has SSL bypass configured"
    }
}

# ----------------------------------------------------------
# STEP 5a - Test AI endpoint connectivity
# ----------------------------------------------------------
Write-Step "Testing Azure OpenAI endpoint connectivity..."

$testScript = @"
import sys
try:
    from config import Config
    from ai_answerer import QuestionAnswerer
    print('✓ Config and QuestionAnswerer imported successfully')
    
    # Initialize client (this tests SSL bypass works)
    qa = QuestionAnswerer()
    print(f'✓ Azure OpenAI client initialized')
    print(f'  Endpoint: {Config.AZURE_OPENAI_ENDPOINT}')
    print(f'  Deployment: {qa.deployment}')
    print(f'  API Version: {Config.AZURE_OPENAI_API_VERSION}')
    
except Exception as e:
    print(f'✗ Error: {str(e)}', file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
"@

$testFile = Join-Path $root "_test_ai_init.py"
$utf8NoBOM = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($testFile, $testScript, $utf8NoBOM)

$testOutput = & $venvPython $testFile 2>&1
$testExit = $LASTEXITCODE
Remove-Item $testFile -ErrorAction SilentlyContinue

if ($testExit -eq 0) {
    Write-Ok "Azure OpenAI endpoint verified and accessible"
    Write-Host "  $($testOutput | Select-Object -Last 3 | ForEach-Object { "  $_" })"
} else {
    Write-Fail "Azure OpenAI endpoint test failed:"
    Write-Host "  $($testOutput | ForEach-Object { "  $_" })"
    Write-Host ""
    Write-Host "  Troubleshooting:" -ForegroundColor Yellow
    Write-Host "  1. Check .env file: $envFile" -ForegroundColor Yellow
    Write-Host "  2. Verify AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY are set" -ForegroundColor Yellow
    Write-Host "  3. Check Azure resource exists: az cognitiveservices account list -g $tfRgName" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ----------------------------------------------------------
# STEP 6 - Frontend static assets (no Vite/esbuild needed)
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
# STEP 7 - Launch backend server (API + frontend on port 8000)
# ----------------------------------------------------------
Write-Step "Starting backend server..."

$pidFile = Join-Path $root ".server.pid"

# Try to kill any existing server on port 8000
try {
    $existingProcess = netstat -ano 2>$null | Select-String ":8000" | ForEach-Object {
        if ($_ -match '\s+(\d+)\s*$') {
            [int]$matches[1]
        }
    }
    if ($existingProcess) {
        Write-Warn "Killing existing process on port 8000 (PID: $existingProcess)..."
        Stop-Process -Id $existingProcess -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
} catch {
    # netstat might not be available, that's ok
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  All setup complete! Starting server...   " -ForegroundColor Green
Write-Host "  ✓ Azure OpenAI configured                " -ForegroundColor Green
Write-Host "  ✓ Python environment ready               " -ForegroundColor Green
Write-Host "  ✓ Frontend assets verified               " -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  📋 Open: http://localhost:8000              " -ForegroundColor White
Write-Host ""
Write-Host "  Press Ctrl+C to stop the server." -ForegroundColor Gray
Write-Host ""

Start-Sleep -Seconds 1
Start-Process "http://localhost:8000"

try {
    Set-Location $root
    & $venvPython server.py
} finally {
    Write-Host "`n[*] Server stopped." -ForegroundColor Green
}

