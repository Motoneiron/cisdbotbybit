"""Скачивает OI (open-interest) и LS ratio (account-ratio) по 10 парам с Bybit v5, 1h.
Диапазон: с 2022-05-01 до сейчас (раньше 2022-06 пусто — проверено пробой).
Выход: RUNS/temp/q_oi/<SYM>_oi.pkl и <SYM>_ls.pkl (ts_ms, val [+ ts_ms, buy, sell для LS])."""
import json
import os
import time
import urllib.request

import pandas as pd

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
OUT = BASE + "/q_oi"
SYMS = ["SOL", "BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP"]
START = int(pd.Timestamp("2022-05-01").timestamp() * 1000)


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def fetch(endpoint: str, sym: str, start_ms: int, name: str, extra: str) -> pd.DataFrame:
    rows = []
    end = int(time.time() * 1000)
    for page in range(600):
        url = (
            f"https://api.bybit.com{endpoint}?category=linear&symbol={sym}USDT"
            f"&{extra}&limit=200&startTime={start_ms}&endTime={end}"
        )
        try:
            d = get(url)
        except Exception as e:
            print(f"[{name}] page {page} error {e!r} — пауза 3с", flush=True)
            time.sleep(3)
            continue
        if page == 0:
            print(f"[{name}] retCode={d.get('retCode')} retMsg={d.get('retMsg')}", flush=True)
        lst = (d.get("result") or {}).get("list") or []
        if not lst:
            break
        rows += lst
        last_ts = int(lst[-1]["timestamp"])
        if last_ts <= start_ms:
            break
        end = last_ts - 1
        if page % 25 == 0:
            print(f"[{name}] page {page} rows={len(rows)} cur_ts={pd.Timestamp(last_ts, unit='ms')}", flush=True)
        time.sleep(0.15)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    df["ts_ms"] = df["timestamp"].astype("int64")
    return df


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for sym in SYMS:
        f_oi = f"{OUT}/{sym}_oi.pkl"
        f_ls = f"{OUT}/{sym}_ls.pkl"
        if not os.path.exists(f_oi):
            d = fetch("/v5/market/open-interest", sym, START, f"OI {sym}", "intervalTime=1h")
            if len(d):
                out = d[["ts_ms", "openInterest"]].copy()
                out["oi"] = out["openInterest"].astype(float)
                out[["ts_ms", "oi"]].to_pickle(f_oi)
                print(f"[OI {sym}] saved n={len(out)} {pd.Timestamp(out.ts_ms.min(), unit='ms')} → {pd.Timestamp(out.ts_ms.max(), unit='ms')}", flush=True)
            else:
                print(f"[OI {sym}] ПУСТО", flush=True)
        if not os.path.exists(f_ls):
            d = fetch("/v5/market/account-ratio", sym, START, f"LS {sym}", "period=1h")
            if len(d):
                out = d[["ts_ms", "buyRatio", "sellRatio"]].copy()
                out["buy"] = out["buyRatio"].astype(float)
                out["sell"] = out["sellRatio"].astype(float)
                out[["ts_ms", "buy", "sell"]].to_pickle(f_ls)
                print(f"[LS {sym}] saved n={len(out)} {pd.Timestamp(out.ts_ms.min(), unit='ms')} → {pd.Timestamp(out.ts_ms.max(), unit='ms')}", flush=True)
            else:
                print(f"[LS {sym}] ПУСТО", flush=True)
    print("OI/LS DONE", flush=True)


if __name__ == "__main__":
    main()
