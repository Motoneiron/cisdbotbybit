"""Проба доступности новых данных Bybit (OI, long/short ratio) с этой машины.

Проверяет историческую глубину: пробуем 2021, 2022, 2023, 2025 для SOLUSDT (1h).
Ликвидации: REST-истории на Bybit v5 нет (только WS) — проверяем, что отвечает market/recent-trade (для справки).
"""
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}


def get(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def probe(endpoint: str, params: str, name: str):
    url = f"https://api.bybit.com{endpoint}?{params}"
    try:
        d = get(url)
        rc = d.get("retCode")
        res = d.get("result") or {}
        lst = res.get("list") or []
        n = len(lst)
        sample = lst[0] if lst else None
        oldest = lst[-1] if lst else None
        print(f"[{name}] retCode={rc} n={n} first={sample} last={oldest}", flush=True)
        return d
    except Exception as e:
        print(f"[{name}] ERROR {e!r}", flush=True)
        return None


def ms(iso: str) -> int:
    import pandas as pd
    return int(pd.Timestamp(iso).timestamp() * 1000)


def main() -> None:
    for year in ["2021", "2022", "2023", "2025"]:
        t0 = ms(f"{year}-06-01")
        t1 = ms(f"{year}-06-02")
        probe(
            "/v5/market/open-interest",
            f"category=linear&symbol=SOLUSDT&intervalTime=1h&startTime={t0}&endTime={t1}",
            f"OI {year}-06",
        )
        time.sleep(0.3)
        probe(
            "/v5/market/account-ratio",
            f"category=linear&symbol=SOLUSDT&period=1h&startTime={t0}&endTime={t1}",
            f"LS {year}-06",
        )
        time.sleep(0.3)
    # свежие данные (последние сутки) — что вообще отдаёт
    probe("/v5/market/open-interest", "category=linear&symbol=SOLUSDT&intervalTime=1h&limit=5", "OI now")
    probe("/v5/market/account-ratio", "category=linear&symbol=SOLUSDT&period=1h&limit=5", "LS now")


if __name__ == "__main__":
    main()
