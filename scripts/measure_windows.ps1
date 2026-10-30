param(
    [string]$ProcessName = "obs-browser-page",
    [int]$Seconds = 10
)

$samples = @()
for ($i = 0; $i -lt $Seconds; $i++) {
    $processes = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue
    if ($processes) {
        $samples += [pscustomobject]@{
            WorkingSetMB = [math]::Round((($processes | Measure-Object WorkingSet64 -Sum).Sum / 1MB), 1)
            PrivateMB = [math]::Round((($processes | Measure-Object PrivateMemorySize64 -Sum).Sum / 1MB), 1)
            CpuSeconds = [math]::Round((($processes | Measure-Object CPU -Sum).Sum), 3)
        }
    }
    Start-Sleep -Seconds 1
}

if (-not $samples) {
    Write-Error "No process named '$ProcessName' was found."
    exit 1
}

$working = $samples | Measure-Object WorkingSetMB -Average -Maximum
$private = $samples | Measure-Object PrivateMB -Average -Maximum
$cpuDelta = $samples[-1].CpuSeconds - $samples[0].CpuSeconds

[pscustomobject]@{
    Process = $ProcessName
    Samples = $samples.Count
    WorkingSetAverageMB = [math]::Round($working.Average, 1)
    WorkingSetPeakMB = $working.Maximum
    PrivateAverageMB = [math]::Round($private.Average, 1)
    PrivatePeakMB = $private.Maximum
    CpuPercentAcrossAllCores = [math]::Round($cpuDelta / $Seconds * 100, 2)
} | Format-List
