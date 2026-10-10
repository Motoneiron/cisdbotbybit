$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'"
foreach ($p in $procs) {
    $cl = $p.CommandLine
    $isOurs = ($cl -like '*CISDBOT*') -or ($cl -like '*multiprocessing*') -or ($cl -like '*live_tf_grid*')
    Write-Output ("{0} | OURS={1} | {2}" -f $p.ProcessId, $isOurs, $cl)
    if ($isOurs) {
        Stop-Process -Id $p.ProcessId -Force
        Write-Output ("  -> killed " + $p.ProcessId)
    }
}
$b = Get-CimInstance Win32_Process -Filter "Name='bash.exe'"
foreach ($p in $b) { Write-Output ("bash {0} | {1}" -f $p.ProcessId, $p.CommandLine) }
