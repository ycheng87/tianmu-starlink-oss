#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商务部商务预报 · 全国农产品/生产资料周度价格回填采集
数据源: https://cif.mofcom.gov.cn/cif/getWeekLineChart2021.fhtml (POST)
- body: indexIds=<品种ID(逗号分隔,至多3个)>&startDate=&endDate=
- ⚠️ 必须 curl -k 调用（python urllib SSL 握手被拒，curl 可过）
- 品种ID清单: 从 zhouduData.js 解析（93 个：粮油/肉禽蛋/蔬菜/水果/农资/工业品）
- 返回: 周度批发价序列（2016-09~今 全量 500+ 点）
存储: prices.db 新表 mofcom_week_prices(ts, variety, price REAL, unit, PRIMARY KEY(ts, variety))
用法: python3 backfill_mofcom.py [--ids 18055947,224060] [--start 2016-09-01] [--end 2026-08-16]
"""
import sqlite3, os, re, json, datetime, subprocess, sys, time, urllib.request

BASE = os.path.expanduser("~/tianmu_starlink")
DB = os.path.join(BASE, "data", "prices.db")
API = "https://cif.mofcom.gov.cn/cif/getWeekLineChart2021.fhtml"
JS_URL = "https://cif.mofcom.gov.cn/cif/resDataIndex/js/zhouduData.js"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def log(msg):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def load_ids():
    """抓 zhouduData.js 解析品种 (id, name) 列表；失败回退本地缓存"""
    cache = os.path.join(BASE, "data", "mofcom_zhoudu_ids.json")
    try:
        req = urllib.request.Request(JS_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            js = r.read().decode("utf-8", errors="replace")
        pairs = re.findall(r'\{id:\s*[\"\']?([0-9]+)[\"\']?\s*,\s*name:\s*[\"\']([^\"\']+)[\"\']', js)
        if not pairs:
            raise ValueError("no ids parsed")
        ids = [{"id": i, "name": n} for i, n in pairs]
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(ids, f, ensure_ascii=False, indent=1)
        return ids
    except Exception as e:
        log(f"抓 zhouduData.js 失败: {e}，尝试本地缓存")
        if os.path.exists(cache):
            return json.load(open(cache, encoding="utf-8"))
        raise


def fetch_week(index_ids, start, end):
    """curl -k POST 拉周度数据，返回解析后的 series 列表"""
    body = f"indexIds={index_ids}&startDate={start}&endDate={end}"
    cmd = ["curl", "-sk", "-X", "POST", API,
           "-A", UA, "-H", "Content-Type: application/x-www-form-urlencoded",
           "-d", body]
    out = subprocess.run(cmd, capture_output=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"curl exit {out.returncode}: {out.stderr[:200]}")
    raw = out.stdout.decode("utf-8", errors="replace").strip()
    if not raw or raw == "[]":
        return []
    return json.loads(raw)


def main():
    args = sys.argv[1:]
    opt_ids = None
    start = "2016-09-01"
    end = datetime.date.today().isoformat()
    i = 0
    while i < len(args):
        if args[i] == "--ids":
            opt_ids = args[i + 1].split(",")
            i += 2
        elif args[i] == "--start":
            start = args[i + 1]
            i += 2
        elif args[i] == "--end":
            end = args[i + 1]
            i += 2
        else:
            i += 1

    ids = load_ids()
    if opt_ids:
        ids = [x for x in ids if x["id"] in opt_ids]
    log(f"品种数: {len(ids)}，区间 {start} ~ {end}")

    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS mofcom_week_prices(
        ts TEXT, variety TEXT, price REAL, unit TEXT,
        source TEXT DEFAULT '商务部·全国口径',
        PRIMARY KEY(ts, variety))""")
    # 旧库补列
    cols = [r[1] for r in c.execute("PRAGMA table_info(mofcom_week_prices)")]
    if 'source' not in cols:
        c.execute("ALTER TABLE mofcom_week_prices ADD COLUMN source TEXT DEFAULT '商务部·全国口径'")
    c.execute("UPDATE mofcom_week_prices SET source='商务部·全国口径' WHERE source IS NULL")

    total = 0
    for k in range(0, len(ids), 3):  # 一次至多 3 品种
        batch = ids[k:k + 3]
        if k > 0:
            time.sleep(0.8)
        try:
            series = fetch_week(",".join(x["id"] for x in batch), start, end)
            for s in series:
                unit = s.get("unit", "")
                # datas 是单品种时间序列（每行一个日期，NAME 恒定）；table 是展示用可能重复，以 datas 为准
                seen = set()
                for d in s.get("datas", []):
                    ts = d.get("DATADATE")
                    v = d.get("NAME")
                    if not ts:
                        continue
                    try:
                        price = float(d["DATA"])
                    except (ValueError, TypeError, KeyError):
                        continue
                    c.execute("INSERT OR REPLACE INTO mofcom_week_prices VALUES(?,?,?,?,?)",
                              (ts, v, price, unit, '商务部·全国口径'))
                    total += 1
            c.commit()
            names = "、".join(x["name"] for x in batch)
            log(f"  [{names}] {sum(len(s.get('datas', [])) for s in series)} 点 (累计 {total})")
        except Exception as e:
            names = "、".join(x["name"] for x in batch)
            log(f"  [{names}] 失败: {repr(e)[:120]}")
    log(f"=== 商务预报回填完成：共 {total} 条 ===")
    c.close()


if __name__ == "__main__":
    main()