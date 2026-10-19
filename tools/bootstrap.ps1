# Finds (or silently installs) Python 3.12, then opens the VisionDB Craft setup wizard.
# Started by Setup.cmd. Needs no admin rights: Python is installed for the current user only.
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$SetupArgs)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'      # Invoke-WebRequest is painfully slow in Windows PowerShell with the bar on
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$PythonVersion = '3.12.10'                    # last 3.12 release that ships a Windows installer

function Write-Step([string]$Text) { Write-Host "  $Text" -ForegroundColor Cyan }
function Fail([string]$Text) { Write-Host ""; Write-Host "  $Text" -ForegroundColor Red; exit 1 }

function Test-Python([string]$Exe) {
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return $false }
    if ($Exe -like '*\WindowsApps\*') { return $false }          # Microsoft Store stub, not a real Python
    $out = & $Exe -c "import sys;print('%d.%d.%d'%sys.version_info[:3]+' '+('64' if sys.maxsize>2**32 else '32'))" 2>$null
    return ($LASTEXITCODE -eq 0 -and $out -match '^3\.12\.\d+ 64$')
}

function Find-Python {
    $candidates = @()
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) { $candidates += (& py.exe -3.12 -c "import sys;print(sys.executable)" 2>$null) }
    $candidates += "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    $candidates += "$env:ProgramFiles\Python312\python.exe"
    $candidates += "${env:ProgramFiles(x86)}\Python312\python.exe"
    $onPath = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($onPath) { $candidates += $onPath.Source }
    foreach ($c in $candidates) { if (Test-Python $c) { return $c } }
    return $null
}

function Install-Python {
    Write-Step "Python 3.12 was not found. Installing it for your user account (no admin needed)..."
    $installer = Join-Path $env:TEMP "python-$PythonVersion-amd64.exe"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Write-Step "Downloading Python $PythonVersion from python.org (about 26 MB)..."
        Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe" -OutFile $installer
        $signature = Get-AuthenticodeSignature -FilePath $installer
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
            throw "The downloaded installer is not signed by the Python Software Foundation."
        }
        Write-Step "Installing (about a minute)..."
        $p = Start-Process -FilePath $installer -Wait -PassThru -ArgumentList @(
            '/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_launcher=0', 'Include_test=0',
            'Include_doc=0', 'Shortcuts=0', 'AssociateFiles=0', 'Include_tcltk=1')
        if ($p.ExitCode -ne 0) { throw "Installer exit code $($p.ExitCode)" }
    } catch {
        Write-Step "Direct install did not work ($($_.Exception.Message)). Trying Windows Package Manager..."
        if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
            & winget.exe install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
        }
    } finally {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
    }
    return (Find-Python)
}

Write-Host ""
Write-Host "  VisionDB Craft - Setup" -ForegroundColor White
Write-Host ""

if (-not [Environment]::Is64BitOperatingSystem) { Fail "This app needs 64-bit Windows 10 or 11." }

$python = Find-Python
if (-not $python) { $python = Install-Python }
if (-not $python) {
    Fail "Could not get Python 3.12. Install it from https://www.python.org/downloads/release/python-31210/ and run Setup.cmd again."
}
Write-Step "Using Python: $python"

# Prefer the graphical wizard; fall back to console questions when this Python has no Tcl/Tk.
$consoleRequested = $SetupArgs -contains '--console'
$unattended = ($SetupArgs | Where-Object { $_ -in @('--yes', '-y', '--dry-run', '--check', '--no-deps', '--reinstall', '--no-launcher', '--no-shortcuts', '--standalone', '--installer') })
& $python -c "import tkinter" 2>$null
$hasTk = ($LASTEXITCODE -eq 0)

if ($hasTk -and -not $consoleRequested -and -not $unattended) {
    $pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
    Write-Step "Opening the setup window..."
    $guiArgs = @('setup_gui.py')
    if ($SetupArgs) { $guiArgs += $SetupArgs }
    Start-Process -FilePath $pythonw -ArgumentList $guiArgs -WorkingDirectory $root
    exit 0
}
& $python (Join-Path $root 'setup_app.py') @SetupArgs
exit $LASTEXITCODE
