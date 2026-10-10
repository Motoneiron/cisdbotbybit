"""Сопоставление живых SOL tf7 сделок с бэк-прогонами (окно 06-22..08-22 2026).

Матчинг:
  1) exact: sig_hash == bt hash
  2) key:   (direction, signal_time[:13]) == (direction, htf_time[:13])
  3) key1h: то же с допуском ±1 час
Отчёты: LIVE_RECON_{cfg}.md + сводка в консоль.
"""
import json
import pickle
from collections import Counter
from pathlib import Path

BASE = Path(r"D:/PYTHON/cisdbotbybit/RUNS/temp/live_recon")
live = json.load(open(BASE / "live_sol_tf7_trades.json", encoding="utf-8"))
print("живых:", len(live))


def bt_load(cfg):
    return pickle.load(open(BASE / f"recon_{cfg}.pkl", "rb"))


def hkey(direction, tstr):
    return f"{direction}|{str(tstr)[:13]}"


def nearest_hour_keys(direction, tstr):
    from datetime import datetime, timedelta
    try:
        t = datetime.fromisoformat(str(tstr)[:19])
    except Exception:
        return {hkey(direction, tstr)}
    return {hkey(direction, (t + timedelta(hours=dh)).isoformat()) for dh in (-1, 0, 1)}


def analyze(cfg):
    res = bt_load(cfg)
    tr = res.get("trades") or []
    sg = res.get("signals") or []
    print(f"\n===== {cfg}: бэк-сделок {len(tr)}, сигналов {len(sg) if isinstance(sg, list) else sg}")

    if tr:
        print("пример трейда:", {k: tr[0].get(k) for k in sorted(tr[0])[:20]})
    if isinstance(sg, list) and sg:
        print("пример сигнала:", {k: sg[0].get(k) for k in sorted(sg[0])[:20]})

    by_hash = {}
    for t in tr:
        by_hash.setdefault(str(t.get("hash")), []).append(t)
    sig_hash = set()
    for s in sg if isinstance(sg, list) else []:
        sig_hash.add(str(s.get("hash")))

    by_key = {}
    for t in tr:
        by_key.setdefault(hkey(t.get("direction"), t.get("htf_time")), []).append(t)

    lines = [f"# Сверка живых SOL tf7 с бэком [{cfg}]", ""]
    m_exact = m_key = m_1h = m_none = 0
    live_r_matched, live_r_unmatched = [], []
    bt_used = set()
    detail_none = []
    for t in live:
        lh = str(t.get("sig_hash"))
        keys = nearest_hour_keys(t.get("direction"), t.get("signal_time"))
        keys0 = hkey(t.get("direction"), t.get("signal_time"))
        cand = by_hash.get(lh)
        if cand:
            m_exact += 1
            bt_used.add(id(cand[0]))
            if t.get("net_r") is not None:
                live_r_matched.append(t["net_r"])
            continue
        if keys0 in by_key:
            m_key += 1
            bt_used.add(id(by_key[keys0][0]))
            if t.get("net_r") is not None:
                live_r_matched.append(t["net_r"])
            continue
        hit1 = next((k for k in keys if k in by_key), None)
        if hit1:
            m_1h += 1
            bt_used.add(id(by_key[hit1][0]))
            if t.get("net_r") is not None:
                live_r_matched.append(t["net_r"])
            continue
        m_none += 1
        if t.get("net_r") is not None:
            live_r_unmatched.append(t["net_r"])
        detail_none.append(
            f"  {t.get('id')} {t.get('direction')} {t.get('entry_kind')} sig={t.get('signal_time')} "
            f"entry={t.get('entry_time','')[:16]} cisd={t.get('cisd_level')} ур={t.get('exit_reason')} netR={t.get('net_r'):+.2f}"
        )

    lines.append(f"живых: {len(live)} | hash-матч: {m_exact} | key: {m_key} | key±1h: {m_1h} | НЕ найдено: {m_none}")
    lines.append(f"матч итого: {m_exact+m_key+m_1h}/{len(live)} = {100*(m_exact+m_key+m_1h)/len(live):.0f}%")
    if live_r_matched or live_r_unmatched:
        lines.append(f"netR живых: найденные {sum(live_r_matched):+.1f} (n={len(live_r_matched)}) | "
                     f"не найденные {sum(live_r_unmatched):+.1f} (n={len(live_r_unmatched)})")
    n_unused = len(tr) - len(bt_used)
    lines.append(f"бэк-сделок без живого соответствия (лишние): {n_unused}")
    lines.append("")
    lines.append("## Живые, которых нет в бэке")
    lines.extend(detail_none or ["  (нет)"])
    out = BASE / f"LIVE_RECON_{cfg}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"written: {out}")
    print("\n".join(lines[:8]))


if __name__ == "__main__":
    import sys
    for cfg in (sys.argv[1:] or ["LIVE_EMUL", "CORE_C5"]):
        p = BASE / f"recon_{cfg}.pkl"
        if not p.exists():
            print(f"нет {p}")
            continue
        analyze(cfg)
