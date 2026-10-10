"""Пересчёт под TP1R:
A) стоимость правила пересвипа (моя цифра -260R) на R-значениях TP1R;
B) паритет по 28 сетапам 16-17.09 с выходом по 1R (пересчёт по 5m данным).
"""
import glob
import pickle

import pandas as pd

# ---------- A. R-значения TP1R из канонического потока ----------
stream = pd.read_pickle("D:/PYTHON/cisdbotbybit/RUNS/temp/stream_off_v1_lv0.pkl")
print("поток TP1R:", len(stream), "| по ТФ:", stream.groupby("prof").size().to_dict())
s8 = stream[stream.prof == "tf8"]
one_r = {}
for r in s8.itertuples():
    key = (r.sym, r.dir, round(float(r.entry), 6))
    one_r[key] = (float(r.r_net), str(r.outcome))
print("сделок tf8 в потоке TP1R:", len(s8), "| ключей:", len(one_r))

# ---------- геометрия сетапов из кэшей ----------
sigs, trades = [], {}
for f in sorted(glob.glob("D:/PYTHON/CISDBOT/RUNS/filters_off_full/*tf8*.pkl")):
    c = pickle.load(open(f, "rb"))
    sym = c.get("symbol")
    for s in c.get("signals") or []:
        sigs.append({"sym": sym, "dir": s.get("direction"), "htf": str(s.get("htf_time")),
                     "sweep": float(s.get("htf_sweep_level") or 0),
                     "ext": float(s.get("trigger_extreme") or 0),
                     "entry": float(s.get("entry") or 0),
                     "scan": s.get("scan_bar"), "hash": str(s.get("hash"))})
    for t in c.get("trades") or []:
        trades[str(t.get("hash"))] = {"r_native": float(t.get("r_net") or 0),
                                      "entry": float(t.get("entry_px") or 0),
                                      "entry_bar": t.get("entry_bar")}
df = pd.DataFrame(sigs).sort_values(["sym", "scan"]).reset_index(drop=True)

found = sum(1 for t in trades.values() if (None, None, round(t["entry"], 6)) in one_r)
print(f"сопоставлено сделок с TP1R-потоком по (sym,dir,entry): "
      f"{sum(1 for s, d, e in [(x['sym'], x['dir'], round(x['entry'], 6)) for x in sigs] if (s, d, e) in one_r)} / {len(sigs)} сигналов")


def r_of(sym, direction, entry, fallback):
    hit = one_r.get((sym, direction, round(float(entry), 6)))
    return hit[0] if hit else fallback


EPS = 1e-8


def deeper(direction, a, b):
    return a < b - EPS if direction == "LONG" else a > b + EPS


removed_1r = removed_nat = 0.0
n_removed = n_suppressed = 0
for sym, g in df.groupby("sym"):
    cands, win_order = {}, []
    for r in g.itertuples():
        key = (r.dir, r.htf)
        if r.htf not in win_order:
            win_order.append(r.htf)
        keep = set(win_order[-2:])
        cands = {k: v for k, v in cands.items() if k[1] in keep}
        sibs = {k: v for k, v in cands.items() if k[0] == r.dir and k != key}
        b_in = {k: (deeper(r.dir, r.ext, v["ext"]) or deeper(r.dir, r.sweep, v["sweep"])) for k, v in sibs.items()}
        b_sib = {k: (deeper(r.dir, v["ext"], r.ext) or deeper(r.dir, v["sweep"], r.sweep)) for k, v in sibs.items()}
        if any(b_sib[k] and not b_in[k] for k in sibs):
            n_suppressed += 1
            t = trades.get(r.hash)
            if t:
                n_removed += 1
                removed_1r += r_of(sym, r.dir, t["entry"], t["r_native"])
                removed_nat += t["r_native"]
            continue
        for k, v in sibs.items():
            if b_in[k] and not b_sib[k]:
                t = trades.get(v["hash"])
                if t and t["entry_bar"] is not None and r.scan is not None and float(t["entry_bar"]) <= float(r.scan):
                    pass
                elif t:
                    n_removed += 1
                    removed_1r += r_of(sym, r.dir, t["entry"], t["r_native"])
                    removed_nat += t["r_native"]
                cands.pop(k, None)
        cur = cands.get(key)
        if cur is None:
            cands[key] = dict(sweep=r.sweep, ext=r.ext, htf=r.htf, hash=r.hash)
        elif deeper(r.dir, r.ext, cur["ext"]) or deeper(r.dir, r.sweep, cur["sweep"]):
            t = trades.get(cur["hash"])
            if t and t["entry_bar"] is not None and r.scan is not None and float(t["entry_bar"]) <= float(r.scan):
                pass
            elif t:
                n_removed += 1
                removed_1r += r_of(sym, r.dir, t["entry"], t["r_native"])
                removed_nat += t["r_native"]
            cands[key] = dict(sweep=r.sweep, ext=r.ext, htf=r.htf, hash=r.hash)

base_1r = float(s8.r_net.sum())
base_nat = float(sum(t["r_native"] for t in trades.values()))
print()
print("=== A. Стоимость правила пересвипа: как я считал и как правильно ===")
print(f"  снято сделок: {n_removed} | сигналов «не берём»: {n_suppressed}")
print(f"  на «родном» TP движка (моя прошлая цифра): -{removed_nat:.1f}R")
print(f"  на TP1R (канон):                          -{removed_1r:.1f}R")
print(f"  база tf8: TP1R {base_1r:+.1f}R | родной {base_nat:+.1f}R")
print(f"  доля потери: от TP1R-потока {100*removed_1r/base_1r:.1f}%")

# ---------- B. Паритет 16-17.09 с выходом по 1R ----------
print()
print("=== B. Паритет 16-17.09: выход по 1R (пересчёт по 5m) ===")
bt = pickle.load(open("D:/PYTHON/cisdbotbybit/RUNS/temp/bt_recent_tf8.pkl", "rb"))
LIVE = {
    ("ADA", "LONG", 0.1946): "closed_time", ("KAS", "LONG", 0.03253): "closed_sl",
    ("LINK", "LONG", 10.812): "voided", ("ETH", "LONG", 2405.4): "voided",
    ("BTC", "LONG", 75999.9): "closed_time", ("DOGE", "LONG", 0.08019): "voided",
    ("BNB", "LONG", 713.9): "voided", ("SOL", "SHORT", 97.24): "closed_tp",
    ("XRP", "LONG", 1.2675): "voided", ("ADA", "LONG", 0.1923): "voided",
    ("DOGE", "LONG", 0.07924): "closed_tp", ("KAS", "LONG", 0.03225): "voided",
    ("LTC", "LONG", 50.72): "voided", ("BTC", "SHORT", 75681.0): "closed_time",
    ("ETH", "SHORT", 2387.67): "closed_sl", ("LTC", "SHORT", 50.58): "closed_sl",
    ("ADA", "LONG", 0.1942): "closed_time", ("BNB", "SHORT", 724.0): "closed_time",
    ("LINK", "SHORT", 11.084): "closed_sl", ("DOGE", "SHORT", 0.08113): "cancelled",
    ("LINK", "SHORT", 11.169): "cancelled", ("SOL", "SHORT", 99.98): "cancelled",
    ("KAS", "SHORT", 0.03416): "cancelled", ("XRP", "LONG", 1.3121): "open",
}


def five(sym):
    return pd.read_csv(f"D:/PYTHON/cisdbotbybit/RUNS/temp/data_recent/{sym}USDT_5m_recent.csv",
                       parse_dates=["timestamp"])


data = {s: five(s) for s in ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]}
START = pd.Timestamp("2026-08-20")

rows = []
for sym, d in bt.items():
    tr = {str(t.get("hash")): t for t in d["trades"]}
    for s in d["signals"]:
        ts = pd.to_datetime(str(s.get("trigger_bar_time")), errors="coerce")
        if pd.isna(ts) or not (pd.Timestamp("2026-09-16") <= ts <= pd.Timestamp("2026-09-18")):
            continue
        t = tr.get(str(s.get("hash"))) or {}
        entry, stop = float(s.get("entry") or 0), float(s.get("stop") or 0)
        direction = s.get("direction")
        risk = abs(entry - stop)
        tp1 = entry + risk if direction == "LONG" else entry - risk
        eb = t.get("entry_bar")
        fill_t = START + pd.Timedelta(minutes=30 * float(eb)) if eb is not None else None
        out1 = None
        if fill_t is not None and risk > 0:
            w = data[sym].loc[(data[sym]["timestamp"] >= fill_t) &
                              (data[sym]["timestamp"] <= fill_t + pd.Timedelta(hours=6))]
            hit_tp = w.loc[(w["high"] >= tp1) if direction == "LONG" else (w["low"] <= tp1)]
            hit_sl = w.loc[(w["low"] <= stop) if direction == "LONG" else (w["high"] >= stop)]
            ftp = hit_tp["timestamp"].iloc[0] if len(hit_tp) else None
            fsl = hit_sl["timestamp"].iloc[0] if len(hit_sl) else None
            if ftp is not None and (fsl is None or ftp <= fsl):
                out1 = "tp"
            elif fsl is not None:
                out1 = "sl"
            else:
                out1 = "time"
        live = None
        for (ls, ld, le), st in LIVE.items():
            if ls == sym and ld == direction and abs(le - entry) <= 6e-4 * max(abs(le), 1e-9):
                live = st
                break
        rows.append((str(ts)[5:16], sym, direction, entry, str(t.get("outcome")), out1, live))

print(f"{'триггер':12s} {'пара':5s} {'напр':5s} {'вход':>10s} {'бэк(родной)':>11s} {'бэк(1R)':>8s} {'живой':>16s}  совпало?")
agree = tot = 0
for r in sorted(rows):
    live_lbl = {"tp": "closed_tp", "sl": "closed_sl", "time": "closed_time", "voided": "voided", "cancelled": "cancelled", "open": "open"}.get(r[6], r[6])
    ok = ""
    if r[6] in ("tp", "sl", "time"):
        tot += 1
        ok = "✓" if r[5] == r[6] else "✗"
        agree += 1 if r[5] == r[6] else 0
    print(f"{r[0]:12s} {r[1]:5s} {r[2]:5s} {r[3]:>10} {str(r[4]):>11s} {str(r[5]):>8s} {str(live_lbl):>16s}  {ok}")
print(f"\nсравнимых сделок {tot} | совпало исходов под 1R: {agree}")
