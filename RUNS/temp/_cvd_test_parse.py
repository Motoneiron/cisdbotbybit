"""Тест механики CVD: streaming-парсинг aggTrades zip → дельта по минутам.

Формат aggTrades (futures UM CSV): agg_id, price, qty, first_id, last_id, timestamp_ms, is_buyer_maker
Дельта = агрессивные покупки (m=False) − агрессивные продажи (m=True), в единицах qty.
Использование: python _cvd_test_parse.py <zip_path>
"""
import csv
import io
import sys
import zipfile
from collections import defaultdict


def main() -> None:
    path = sys.argv[1]
    per_min = defaultdict(float)  # ts_min → delta
    n = 0
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            reader = csv.reader(io.TextIOWrapper(fh, encoding="utf-8"))
            for row in reader:
                if len(row) < 7:
                    continue
                try:
                    q = float(row[2])
                    ts = int(row[5])
                    maker = row[6].strip().lower() == "true"
                except ValueError:
                    continue
                n += 1
                per_min[ts // 60000] += -q if maker else q
    mins = sorted(per_min)
    print(f"rows={n} minutes={len(mins)}")
    if mins:
        tot = sum(per_min.values())
        print(f"delta_total={tot:.1f} (в единицах qty)")
        print("первые 5 минут:")
        for m in mins[:5]:
            print(f"  {m*60000}: {per_min[m]:.2f}")
        print("последние 3:")
        for m in mins[-3:]:
            print(f"  {m*60000}: {per_min[m]:.2f}")


if __name__ == "__main__":
    main()
