Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -like 'python*' -and $_.CommandLine -like '*live_tf_grid*') -or
  ($_.Name -like 'bash*' -and $_.CommandLine -like '*tf1full*')
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output ('killed ' + $_.Name + ' ' + $_.ProcessId) }
