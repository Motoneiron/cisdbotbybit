"""Сборка live-recon данных для сверки с живыми SOL tf7 сделками (июнь-август 2026).

1m full_hdr покрывает до ~21.08.2026; 5m full_hdr — только до 24.06.
Режем 1m окно 2026-05-10..2026-08-19, валидируем, сверяем ресемпл-5m
с нативным 5m на пересечении, пишем единый файл:
  live_recon/SOLUSDT_1m_recon.csv
Движок (load_ltf) сам отресемплит из него 5m, т.к. имя содержит '1m'.
"""
import sys
from pathlib import Path

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

import pandas as pd  # noqa: E402

from backtest.data import RESAMPLE_FROM_1M, read_ohlcv_csv_range, resample_ohlcv  # noqa: E402

ONEM = Path(r"D:\databtcusdt\SOLUSDT-1m\SOLUSDT_1m_full_hdr.csv")
FIVEM = Path(r"D:\databtcusdt\SOLUSDT-5m\SOLUSDT_5m_full_hdr.csv")
OUT = Path(r"D:/PYTHON/cisdbotbybit/RUNS/temp/live_recon")
OUT.mkdir(parents=True, exist_ok=True)

SINCE = pd.Timestamp("2026-05-10")
UNTIL = pd.Timestamp("2026-08-22")

raw = read_ohlcv_csv_range(ONEM, SINCE, UNTIL)
print("1m:", len(raw), raw.index[0], "->", raw.index[-1], "| cols:", list(raw.columns))

d = raw.index.to_series().diff().dt.total_seconds()
gaps = d[d > 60]
print(f"1m пропусков(>60s): {len(gaps)} | дублей: {raw.index.duplicated().sum()}")
if len(gaps):
    print("  топ-5 дыр (сек):", [int(x) for x in gaps.nlargest(5)])

# ресемпл 5m и сверка с нативным 5m на пересечении
df5 = resample_ohlcv(raw, RESAMPLE_FROM_1M["5m"])
nat = read_ohlcv_csv_range(FIVEM, SINCE, min(UNTIL, pd.Timestamp("2026-06-25")))
inter = df5.index.intersection(nat.index)
print("5m ресемпл:", len(df5), "| пересечение с нативными 5m:", len(inter))
if len(inter):
    a, b = df5.loc[inter], nat.loc[inter]
    for c in ("open", "high", "low", "close"):
        err = (a[c] - b[c]).abs()
        print(f"  {c}: max={err.max():.6f} mean={err.mean():.6f} | err>1e-9: {(err > 1e-9).sum()}")
    verr = (a["volume"] - b["volume"]).abs()
    print(f"  volume: max={verr.max():.2f} mean={verr.mean():.2f}")

# кросс-чек с оконной выгрузкой (той, что использовалась в live-аудитах)
try:
    lw = pd.read_csv(r"D:/PYTHON/CISDBOT/.tmp_live_compare/SOLUSDT_1m_mexc_live_window.csv")
    print("live_window cols:", list(lw.columns)[:8], "rows:", len(lw))
    if "open_time" in lw.columns:
        lw["ts"] = pd.to_datetime(lw["open_time"], unit="ms")
        lw = lw.set_index("ts")
        ccol = "close" if "close" in lw.columns else lw.columns[4]
        ii = raw.index.intersection(lw.index)
        if len(ii):
            dd = (raw.loc[ii, "close"] - lw.loc[ii, ccol]).abs()
            print(f"  1m close vs live_window: overlap={len(ii)} max={dd.max():.6f} mean={dd.mean():.6f}")
except Exception as e:
    print("live_window cross-check skipped:", e)

# запись recon
out = raw.copy()
out.index.name = "timestamp"
out = out.reset_index()
out = out[["timestamp", "open", "high", "low", "close", "volume"]]
out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
p = OUT / "SOLUSDT_1m_recon.csv"
out.to_csv(p, index=False)
print("written:", p, len(out), "строк |", out["timestamp"].iloc[0], "->", out["timestamp"].iloc[-1])
