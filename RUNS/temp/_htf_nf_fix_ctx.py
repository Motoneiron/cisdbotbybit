# -*- coding: utf-8 -*-
"""Фикс: достроить HTF-контексты для строк nofilter-CSV, которым они не строились
(прошли все фильтры, пропущены busy/htf — у них q=r_cf, но фичи пустые). Обновляет CSV."""
import glob
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")
from HTF_CONTEXT.htf_context import HTFContextEngine
from HTF_CONTEXT.htf_resample import load_1m, make_frames
from HTF_CONTEXT.research_htf_context import PAIRS10, PATHS, PREHISTORY, UNTIL

CSV = r"D:\PYTHON\cisdbotbybit\RUNS\cache\nofilter_summary.csv"
NF_DIR = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_htfctx_nf\rows_tf1v2_nofilter"

df = pd.read_csv(CSV)
df["taken"] = df["taken"].astype(bool)
df["key"] = (df["symbol"].astype(str) + "|" + df["scan"].astype(str) + "|"
             + df["cbt"].astype(str) + "|" + df["direction"].astype(str))
missing = df[(~df["taken"]) & df["r_cf"].notna() & df["nearest_opposing_R"].isna()]
print("строк без контекста (но с cf):", len(missing))
tags_any = missing["gate_rej"].fillna(False).astype(bool) | missing["ms_rej"].fillna(False).astype(bool) | \
           missing["dt_rej"].fillna(False).astype(bool) | missing["sweep_rej"].fillna(False).astype(bool)
print("   из них с тегами (не ожидалось):", int(tags_any.sum()))
if not len(missing):
    print("нечего чинить"); raise SystemExit(0)

need = set(missing["key"])

rows_by_sym: dict[str, list] = {}
for f in sorted(glob.glob(os.path.join(NF_DIR, "*.pkl"))):
    sym = os.path.basename(f).rsplit("_", 1)[0]
    if sym not in PAIRS10:
        continue
    for r in pickle.load(open(f, "rb")):
        k = f"{r['sym']}|{r['scan']}|{r['cbt']}|{r['direction']}"
        if k in need:
            rows_by_sym.setdefault(sym, []).append(r)
print("к обработке:", sum(len(v) for v in rows_by_sym.values()))

fix: dict[str, dict] = {}
t0 = time.time()
for sym, rows in rows_by_sym.items():
    df1 = load_1m(PATHS[sym], PREHISTORY, UNTIL)
    frames = make_frames(df1)
    eng = HTFContextEngine(sym, frames)
    idx_ns = df1.index.to_numpy(dtype="datetime64[ns]")
    closes = df1["close"].to_numpy(dtype="float64")
    for r in rows:
        scan = pd.Timestamp(r["scan"])
        j = int(np.searchsorted(idx_ns, np.datetime64(scan), side="left")) - 1
        px = float(closes[j]) if j >= 0 else float(r["entry"])
        signal = {"direction": r["direction"], "entry": r["entry"], "stop": r["stop"], "tp": r["tp"],
                  "cbt": r.get("cbt"), "tbt": r.get("tbt"), "htf": r.get("htf"), "scan": r.get("scan"),
                  "cisd_level": r.get("cisd_level"), "htf_sweep_level": r.get("htf_sweep_level")}
        ctx = eng.context(scan, signal, tp_r=1.0, px=px)
        s = ctx["summary"]
        fix[f"{r['sym']}|{r['scan']}|{r['cbt']}|{r['direction']}"] = {
            "nearest_opposing_R": s.get("nearest_opposing_obstacle_R"),
            "nearest_internal_R": s.get("nearest_internal_liquidity_R"),
            "nearest_external_R": s.get("nearest_external_liquidity_R"),
            "tp_blocked": s.get("tp_blocked"),
        }
    print(f"[{sym}] {len(rows)} ок ({time.time()-t0:.0f}s)", flush=True)

m = df["key"].map(fix)
for col in ("nearest_opposing_R", "nearest_internal_R", "nearest_external_R", "tp_blocked"):
    filled = m.map(lambda x: x[col] if isinstance(x, dict) else None)
    df[col] = df[col].fillna(filled)

df.drop(columns=["key"]).to_csv(CSV, index=False)
still = df[(~df["taken"]) & df["r_cf"].notna() & df["nearest_opposing_R"].isna()]
print("после фикса строк без контекста:", len(still))
print("осталось без nearest (истинные >5R или без филла):", int(df["nearest_opposing_R"].isna().sum()))
