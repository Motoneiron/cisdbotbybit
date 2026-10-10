@echo off
rem Авто-возобновление прогона абляций tf7 (устойчиво к убийству процесса).
rem Максимум 30 попыток; выход, если в логе появился DONE (все задачи сделаны).
cd /d D:\PYTHON\cisdbotbybit\RUNS\temp
set PY=D:\hermes-agent\.venv\Scripts\python.exe
set LOG=tf7_abl_run2.log
set N=0
:loop
set /a N+=1
if %N% GTR 30 goto :eof
%PY% -u tf7_ablations.py 18 >> %LOG% 2>&1
findstr /c:"DONE" %LOG% >nul && goto :eof
timeout /t 15 /nobreak >nul
goto loop
