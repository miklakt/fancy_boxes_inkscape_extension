param(
    [Parameter(Position = 0)]
    [string]$ExtensionsDir,

    [Alias("h")]
    [switch]$Help,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Show-Usage {
    @"
Usage: .\install.ps1 [EXTENSIONS_DIR]

Installs Fancy Boxes into a tidy fancy_boxes subfolder inside the per-user Inkscape extensions folder.

Destination selection:
  1. First command-line argument, if provided
  2. Windows default: `$env:APPDATA\inkscape\extensions

Examples:
  .\install.ps1
  .\install.ps1 "$env:APPDATA\inkscape\extensions"
"@
}

if ($Help) {
    Show-Usage
    exit 0
}

if ($ExtraArgs.Count -gt 0) {
    Show-Usage | Write-Error
    exit 2
}

$scriptDir = Split-Path -Parent $PSCommandPath
$sourceDir = Join-Path $scriptDir "fancy_boxes"
$sourceInx = Join-Path $sourceDir "fancy_boxes.inx"
$sourcePy = Join-Path $sourceDir "fancy_boxes.py"

if (-not (Test-Path -LiteralPath $sourceInx -PathType Leaf) -or -not (Test-Path -LiteralPath $sourcePy -PathType Leaf)) {
    Write-Error "Could not find fancy_boxes\fancy_boxes.inx and fancy_boxes\fancy_boxes.py next to this installer."
    exit 1
}

if ([string]::IsNullOrWhiteSpace($ExtensionsDir)) {
    if ([string]::IsNullOrWhiteSpace($env:APPDATA)) {
        Write-Error "APPDATA is not set. Pass the Inkscape extensions directory explicitly."
        exit 1
    }

    $ExtensionsDir = Join-Path $env:APPDATA "inkscape\extensions"
}

$targetDir = Join-Path $ExtensionsDir "fancy_boxes"
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

# Remove flat installs made by older versions of this installer.
$oldInx = Join-Path $ExtensionsDir "fancy_boxes.inx"
$oldPy = Join-Path $ExtensionsDir "fancy_boxes.py"
Remove-Item -LiteralPath $oldInx, $oldPy -Force -ErrorAction SilentlyContinue

Copy-Item -LiteralPath $sourceInx -Destination (Join-Path $targetDir "fancy_boxes.inx") -Force
Copy-Item -LiteralPath $sourcePy -Destination (Join-Path $targetDir "fancy_boxes.py") -Force

@"
Installed Fancy Boxes to:
  $targetDir

Restart Inkscape, then open:
  Extensions > Render > Fancy Boxes
"@
