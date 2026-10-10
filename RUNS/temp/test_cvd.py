"""Тест CVD-фичи после деплоя: функция vs независимый контроль."""
import asyncio
import json
import sys
import time
import urllib.request

sys.path.insert(0, "/opt/cisdbotbybit")
import cisdbot as cb  # noqa: E402


def control(sk: str) -> float:
    sym = sk + "USDT"
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1m&limit=61"
    with urllib.request.urlopen(url, timeout=15) as r:
        rows = json.load(r)
    now = int(time.time() * 1000)
    closed = [k for k in rows if int(k[6]) <= now][-60:]
    vol = sum(float(k[5]) for k in closed)
    tb = sum(float(k[9]) for k in closed)
    return (2 * tb - vol) / vol


async def main():
    print("cvd_enabled:", cb.state.cvd_enabled, "| elliott_enabled:", cb.state.elliott_enabled)
    for sk in ("BNB", "SOL", "ETH", "KAS"):
        of, unav = await cb._cvd_order_flow_1h(sk)
        ctrl = control(sk)
        of_s = f"{of:+.5f}" if of is not None else "None"
        print(f"{sk}: функция={of_s} (unav={unav}) | контроль={ctrl:+.5f} | "
              f"вес L={cb._cvd_weight(of, 'LONG')} S={cb._cvd_weight(of, 'SHORT')}")


asyncio.run(main())
