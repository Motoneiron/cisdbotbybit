"""Собирает per-minute дельту из aggTrades zip → компактный pkl (CVD-база для фич).

Использование: python _cvd_build_minute.py SOL
Выход: RUNS/temp/cvd/<SYM>USDT_minute.pkl (ts_ms, delta, buy, sell, n)
"""
import csv
import glob
import io
import os
import sys
import zipfile

import pandas as pd


def main() -> None:
    sym = sys.argv[1]
    d = rf"D:/PYTHON/cisdbotbybit/RUNS/temp/cvd/{sym}USDT"
    files = sorted(glob.glob(os.path.join(d, "*.zip")))
    print(f"{sym}: {len(files)} файлов", flush=True)
    rows = []
    for i, f in enumerate(files):
        try:
            with zipfile.ZipFile(f) as z:
                name = z.namelist()[0]
                with z.open(name) as fh:
                    reader = csv.reader(io.TextIOWrapper(fh, encoding="utf-8"))
                    buy = {}
                    sell = {}
                    cnt = {}
                    for row in reader:
                        if len(row) < 7:
                            continue
                        try:
                            q = float(row[2])
                            ts = int(row[5])
                            maker = row[6].strip().lower() == "true"
                        except ValueError:
                            continue
                        m = ts // 60000
                        cnt[m] = cnt.get(m, 0) + 1
                        if maker:
                            sell[m] = sell.get(m, 0.0) + q
                        else:
                            buy[m] = buy.get(m, 0.0) + q
            for m, c in cnt.items():
                rows.append((m * 60000, buy.get(m, 0.0) - sell.get(m, 0.0), buy.get(m, 0.0), sell.get(m, 0.0), c))
        except Exception as e:
            print("fail:", f, repr(e), flush=True)
        if (i + 1) % 200 == 0:
            print(f"[{i+1}/{len(files)}]", flush=True)
    df = pd.DataFrame(rows, columns=["ts_ms", "delta", "buy", "sell", "n"]).sort_values("ts_ms").drop_duplicates("ts_ms")
    out = rf"D:/PYTHON/cisdbotbybit/RUNS/temp/cvd/{sym}USDT_minute.pkl"
    df.to_pickle(out)
    print(f"saved {out} rows={len(df)}", flush=True)


if __name__ == "__main__":
    main()
