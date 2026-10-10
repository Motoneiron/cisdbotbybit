"""НОЧЬ, шаг 2 — анализ: базовые линии, vwap-сетка, режимные индикаторы, портфельный сим.

Читает RUNS/temp/night_core/*.pkl (сделочная база, посчитана night_core.py).
Пишет отчёт в RUNS/temp/NIGHT_REPORT_ALIGNED.md (добавлением).
"""
import glob
import pickle
import sys

import numpy as np
import pandas as pd

OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/NIGHT_REPORT_ALIGNED.md"
files = sorted(glob.glob("D:/PYTHON/cisdbotbybit/RUNS/temp/night_core_aligned/*.pkl"))
if not files:
    print("нет данных night_core")
    sys.exit(1)
raw = pd.concat([pd.DataFrame(pickle.load(open(f, "rb"))) for f in files], ignore_index=True)
df = raw[raw.filled].copy()
df["t_entry"] = pd.to_datetime(df.cbt) + pd.to_timedelta(df.anchor, unit="m") + pd.to_timedelta(df.fill_min, unit="m")
df["t_exit"] = df.t_entry + pd.to_timedelta(df.exit_min, unit="m")
lines = []


def w(s=""):
    print(s, flush=True)
    lines.append(s)


def stat(d, name, base):
    if not len(d):
        w(f"  {name:38s} —")
        return
    tp = int((d.out == "tp").sum())
    sl = int((d.out == "sl").sum())
    ti = int((d.out == "time").sum())
    w(f"  {name:38s} n={len(d):6d} ({100*len(d)/max(1,len(base)):4.1f}%) TP={tp:5d} SL={sl:5d} TIME={ti:5d} "
      f"WR={100*tp/max(1,tp+sl):5.1f}% ΣR={d.r.sum():+9.1f} avg={d.r.mean():+.3f}")


def portfolio(d, max_pos=7, risk=0.01, start=100.0, tag=""):
    """Портфель: max_pos слотов, одна поза на пару, риск % от текущего баланса, реинвест."""
    d = d.sort_values(["t_entry", "sym"])
    events = []
    for i, r in enumerate(d.itertuples()):
        events.append((r.t_entry, 0, i))
        events.append((r.t_exit, 1, i))
    events.sort(key=lambda e: (e[0], e[1]))
    open_pairs, bal, cur_risk = {}, start, {}
    peak, maxdd, curve = start, 0.0, []
    accepted = 0
    rsum = 0.0
    for ts, kind, i in events:
        r = d.iloc[i]
        if kind == 0:
            if len(open_pairs) >= max_pos or r.sym in open_pairs:
                continue
            rk = bal * risk
            open_pairs[r.sym] = (rk, r.r)
            acc = True
            accepted += 1
            curve.append((ts, bal))
        else:
            if r.sym in open_pairs:
                rk, rr = open_pairs.pop(r.sym)
                bal += rk * rr
                rsum += rk * rr / max(1e-9, rk)
                peak = max(peak, bal)
                maxdd = max(maxdd, (peak - bal) / peak * 100)
                curve.append((ts, bal))
    return {"final": bal, "maxdd": maxdd, "n": accepted, "tag": tag}


w("=" * 96)
w("# НОЧНОЙ ОТЧЁТ: фильтры и режимы на ЧЕСТНОЙ (исполнимой) базе")
w(f"\nсделочная база: {len(raw)} строк, налившихся {len(df)}; пар {df.sym.nunique()}, лет {df.year.min()}–{df.year.max()}")

w("\n## 1. Базовая линия: якорь × окно (TP1R, комиссии Bybit, min_stop 0.25%)")
w("   anchor=5  = канон (вход внутри 30m-бара, look-ahead); anchor=30 = исполнимый (после закрытия 30m)")
for a in (5, 30):
    for win in (15, 20, 30, 45, 60):
        d = df[(df.anchor == a) & (df.win == win)]
        stat(d, f"anchor={a} win={win}м", d)

BASE = df[(df.anchor == 30) & (df.win == 30)]
w(f"\nИСПОЛНИМАЯ БАЗА для фильтров: anchor=30, win=30 → {len(BASE)} сделок")

w("\n## 2. VWAP-сетка на исполнимой базе")
w("   правило бота: LONG нужен vd>=0, SHORT нужен vd<=0; здесь проверяем и пороги |vd|>=th")
stat(BASE, "все (raw)", BASE)
for th in (0.0, 0.5, 1.0, 2.0):
    keep = BASE[((BASE["dir"] == "LONG") & (BASE.vd >= th)) | ((BASE["dir"] == "SHORT") & (BASE.vd <= -th))]
    stat(keep, f"vwap |vd|>={th:g} (обе ноги)", BASE)
for dd in ("LONG", "SHORT"):
    b = BASE[BASE["dir"] == dd]
    stat(b, f"{dd}: все", b)
    stat(b[b.vd >= 0] if dd == "LONG" else b[b.vd <= 0], f"{dd}: vd {'>=0' if dd=='LONG' else '<=0'}", b)

w("\n## 3. Режимные индикаторы (наклон EMA3 по закрытым барам) на исполнимой базе")
for col, lbl in (("s1h", "EMA3 1H"), ("s4h", "EMA3 4H"), ("s1d", "EMA3 1D")):
    for th in (0.0, 0.02, 0.1, 0.3):
        d = BASE.dropna(subset=[col])
        keep = d[((d["dir"] == "LONG") & ((d[col] > th) | (d[col].abs() <= th)))
                 | ((d["dir"] == "SHORT") & ((d[col] < -th) | (d[col].abs() <= th)))]
        stat(keep, f"{lbl}: порог {th:g}%", d)
d = BASE.dropna(subset=["dopen_atr"])
stat(d[((d["dir"] == "LONG") & (d.dopen_atr >= 0)) | ((d["dir"] == "SHORT") & (d.dopen_atr <= 0))],
     "цена по сторону дневного open", d)

w("\n## 4. Портфельный сим (7 слотов, 1 поз/пара, риск 1% от баланса, реинвест)")
variants = {"raw": BASE,
            "vwap (vd>=0 / <=0)": BASE[((BASE["dir"] == "LONG") & (BASE.vd >= 0)) | ((BASE["dir"] == "SHORT") & (BASE.vd <= 0))],
            "vwap |vd|>=1": BASE[((BASE["dir"] == "LONG") & (BASE.vd >= 1)) | ((BASE["dir"] == "SHORT") & (BASE.vd <= -1))]}
for col, lbl in (("s1h", "EMA3 1H"), ("s4h", "EMA3 4H"), ("s1d", "EMA3 1D")):
    for th in (0.0, 0.1):
        d = BASE.dropna(subset=[col])
        variants[f"{lbl} порог {th:g}%"] = d[((d["dir"] == "LONG") & ((d[col] > th) | (d[col].abs() <= th)))
                                             | ((d["dir"] == "SHORT") & ((d[col] < -th) | (d[col].abs() <= th)))]
w(f"  {'вариант':28s} {'сделок':>7s} {'финал $':>10s} {'maxDD %':>8s}")
rows = []
for name, d in variants.items():
    p = portfolio(d, tag=name)
    w(f"  {name:28s} {p['n']:7d} {p['final']:10.2f} {p['maxdd']:8.1f}")
    rows.append({"variant": name, **p})
pd.DataFrame(rows).to_csv("D:/PYTHON/cisdbotbybit/RUNS/temp/night_portfolio.csv", index=False)

w("\n## 5. По годам (исполнимая база и два фильтра): ΣR и портфель-деньги")
for name, d in (("raw", BASE), ("vwap", variants["vwap (vd>=0 / <=0)"])):
    w(f"\n  {name}:")
    for y in sorted(df.year.unique()):
        dy = d[d.year == y]
        if not len(dy):
            continue
        tp = int((dy.out == "tp").sum()); sl = int((dy.out == "sl").sum())
        p = portfolio(dy, tag=f"{name}{y}")
        w(f"    {y}: n={len(dy):5d} WR={100*tp/max(1,tp+sl):5.1f}% ΣR={dy.r.sum():+8.1f} | портфель за год ${p['final']-100:+8.2f} (DD {p['maxdd']:.1f}%)")

open(OUT, "a", encoding="utf-8").write("\n".join(lines) + "\n")
print("\nзаписано в", OUT)
