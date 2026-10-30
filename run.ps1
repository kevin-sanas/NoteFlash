param([switch]$Open)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$arguments = @('-m', 'note_flash')
if ($Open) { $arguments += '--open' }
& python @arguments
