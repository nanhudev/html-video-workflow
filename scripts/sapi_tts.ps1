param(
  [Parameter(Mandatory=$true)][string]$TextFile,
  [Parameter(Mandatory=$true)][string]$OutputFile,
  [string]$Voice = "",
  [int]$Rate = 0
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$text = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8)
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($Voice) {
  try { $synth.SelectVoice($Voice) } catch { Write-Warning "Voice '$Voice' unavailable; using default." }
}
$synth.Rate = [Math]::Max(-10, [Math]::Min(10, $Rate))
$synth.SetOutputToWaveFile($OutputFile)
$synth.Speak($text)
$synth.Dispose()
