"""Keepalive прогона абляций tf7 — БЕЗ ОКОН (запускается pythonw.exe планировщиком).

- DONE в логе  -> удалить задачи, поставить флаг-файл;
- пул жив (главный процесс tf7_ablations.py) -> тихо выйти;
- иначе        -> скрыто перезапустить прогон (CREATE_NO_WINDOW), лог перезапуска.
Все subprocess-вызовы скрытые, чтобы не мигали окна.
"""
import os
import subprocess
import time
import traceback

import psutil

TEMP = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
LOG = TEMP + "/tf7_abl_run2.log"
PY = r"D:\hermes-agent\.venv\Scripts\python.exe"
SCRIPT = TEMP + "/tf7_ablations.py"
DONE_FLAG = TEMP + "/tf7_abl_KEEPALIVE_DONE.txt"
RESTARTS = TEMP + "/tf7_abl_keepalive_restarts.log"
ERRORS = TEMP + "/tf7_abl_keepalive_error.log"

CNW = 0x08000000          # CREATE_NO_WINDOW
CNPG = 0x00000200         # CREATE_NEW_PROCESS_GROUP


def main() -> None:
    alive = False
    for p in psutil.process_iter(["cmdline"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
            if "tf7_ablations.py" in cl and "keepalive" not in cl:
                alive = True
                break
        except Exception:
            pass

    txt = ""
    if os.path.exists(LOG):
        txt = open(LOG, encoding="utf-8", errors="replace").read()
    done = "DONE" in txt

    if done:
        for tn in ("tf7abl_keepalive", "tf7abl_resume"):
            subprocess.run(["schtasks", "/delete", "/tn", tn, "/f"],
                           capture_output=True, creationflags=CNW)
        with open(DONE_FLAG, "w", encoding="utf-8") as f:
            f.write(f"done at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    elif alive:
        pass
    else:
        out = open(LOG, "ab")
        subprocess.Popen(
            [PY, "-u", SCRIPT, "18"],
            stdout=out, stderr=out, cwd=TEMP,
            creationflags=CNW | CNPG, close_fds=True,
        )
        with open(RESTARTS, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} restart issued (pool not alive)\n")


try:
    main()
except Exception:
    with open(ERRORS, "a", encoding="utf-8") as f:
        f.write(f"\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n{traceback.format_exc()}\n")
