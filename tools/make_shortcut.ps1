# Creates Desktop / Start Menu shortcuts that point at the quick-launch EXE.
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$WorkDir,
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Description = '',
    [switch]$Desktop,
    [switch]$StartMenu
)
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell

function New-Link([string]$Folder) {
    if (-not (Test-Path -LiteralPath $Folder)) { New-Item -ItemType Directory -Path $Folder -Force | Out-Null }
    $path = Join-Path $Folder ($Name + '.lnk')
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $Target
    $link.WorkingDirectory = $WorkDir
    $link.IconLocation = $Target + ',0'
    $link.Description = $Description
    $link.Save()
    Write-Output ("CREATED: " + $path)
}

# GetFolderPath follows OneDrive-redirected Desktops correctly.
if ($Desktop)   { New-Link ([Environment]::GetFolderPath('Desktop')) }
if ($StartMenu) { New-Link ([Environment]::GetFolderPath('Programs')) }
