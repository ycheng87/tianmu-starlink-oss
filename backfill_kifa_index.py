#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KIFA 价格指数历史回填脚本（2024-01 ~ 2026-08 一次性回填）
- 仿 collect.py 的 fetch_kifa：按月请求 kIFAPriceIndex.do?timeSetString=YYYYMM
- 每次请求返回该月整月指数，INSERT OR REPLACE 幂等覆盖
- 延时 0.5s/次；失败自动重试 1 次；全程记录到 data/collect.log
用法: python3 backfill_kifa_index.py [起始YYYY-MM] [结束YYYY-MM]
"""
import sqlite3, json, urllib.request, os, datetime, ssl, sys, time

UNVERIFIED_SSL = ssl._create_unverified_context()
BASE = os.path.expanduser("~/tianmu_starlink")
DB = os.path.join(BASE, "data", "prices.db")
LOG = os.path.join(BASE, "data", "collect.log")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

HEADERS = {"User-Agent": UA, "Referer": "https://www.kifaonline.com.cn/",
           "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}


def log(msg):
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def to_iso(ts):
    s = str(ts)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def fetch_month(ym):
    """ym = 'YYYY-MM' → (rows, total_childs)；失败抛异常"""
    url = ("https://www.kifaonline.com.cn/kIFAPriceIndex.do?method=getInfo"
           f"&timeSetString={ym.replace('-', '')}&tag=0")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25, context=UNVERIFIED_SSL) as r:
        return json.loads(r.read())


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "2024-01"
    end = sys.argv[2] if len(sys.argv) > 2 else "2026-08"
    y1, m1 = map(int, start.split("-"))
    y2, m2 = map(int, end.split("-"))
    months = []
    y, m = y1, m1
    while (y, m) <= (y2, m2):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    log(f"=== KIFA 指数回填 {start} ~ {end}，共 {len(months)} 个月 ===")

    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS kifa_index("
              "ts TEXT, price_index_a REAL, price_index_q REAL, PRIMARY KEY(ts))")
    total = fail = 0
    for i, ym in enumerate(months, 1):
        if i > 1:
            time.sleep(0.5)  # 0.5s/次
        rows = None
        for attempt in (1, 2):  # 失败重试 1 次
            try:
                rows = fetch_month(ym)
                break
            except Exception as e:
                log(f"  {ym} 第{attempt}次失败: {repr(e)[:100]}")
                time.sleep(1.5 * attempt)
        if rows is None:
            fail += 1
            continue
        n = 0
        for item in rows:
            for r in item.get("childs", []):
                c.execute("INSERT OR REPLACE INTO kifa_index VALUES(?,?,?)",
                          (to_iso(r["timeString"]), r.get("priceIndexA"), r.get("priceIndexQ")))
                n += 1
        c.commit()
        total += n
        log(f"  {ym}: {n} 条（累计 {total}）")
    log(f"=== KIFA 回填完成：共 {total} 条，失败 {fail} 个月 ===")
    c.close()


if __name__ == "__main__":
    main()