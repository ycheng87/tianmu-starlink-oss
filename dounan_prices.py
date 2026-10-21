#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""田亩星链 · 斗南花卉品名级价格采集（多德花卉网 duood.com）

⚠️ 已废弃数据源（2026-08-16 标记）
  多德网 (duood.com) 为民间整理/非官方源，品名价疑似僵化(如卡罗拉 A/B 级价连续多日
  恒定不刷新)，不可作为交易决策依据。
  品名级历史已找到正牌源候选：贵阳数交所 DFETC（服务商=昆明斗南农产品拍卖有限公司）。
  → 本脚本已停止每日采集(cron 移除)，保留历史数据仅供参考追溯，勿用其做回测/决策。

数据源：http://www.duood.com/GoodsList.aspx?id=1..8（8 大类鲜花）
- id=1 玫瑰类, id=2 百合类, id=3 康乃馨类, ... id=8
- 字段：品名、种类、颜色、单位、A/B/C级价格、涨跌

存储：田亩星链 prices.db 的 dounan_prices 表（与信号追踪 signals.db 完全分离）
用法: python3 dounan_prices.py (仅手动补采/历史维护)
"""
import sqlite3, os, json, urllib.request, re, time, random, datetime, sys

BASE = os.path.expanduser("~/tianmu_starlink")
DB = os.path.join(BASE, "data", "prices.db")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

CATEGORIES = {
    1: "玫瑰", 2: "百合", 3: "康乃馨", 4: "非洲菊",
    5: "菊花", 6: "配花", 7: "叶材", 8: "其他",
}

def log(msg):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")

def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

def parse_table(html):
    """解析 duood.com 行情表格 → [{品名,种类,颜色,单位,C,B,A,涨跌}]"""
    items = []
    m = re.search(r"<table[^>]*>.*?</table>", html, re.S)
    if not m:
        return items
    table = m.group(0)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)
    for row in rows:
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < 9 or cells[0] == "名称":
            continue  # 跳表头
        name, _, kind, color, unit, c_price, b_price, a_price, chg, _ = cells[:10]
        if not name:
            continue
        def num(s):
            try:
                return float(re.sub(r"[^\d.]", "", s))
            except (ValueError, TypeError):
                return None
        items.append({
            "name": name, "kind": kind, "color": color, "unit": unit,
            "price_c": num(c_price), "price_b": num(b_price),
            "price_a": num(a_price), "change": chg,
        })
    return items

def init_db(c):
    c.execute("""CREATE TABLE IF NOT EXISTS dounan_prices(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT,                -- 采集日期 YYYY-MM-DD
        category TEXT,          -- 大类（玫瑰/百合/...）
        name TEXT,              -- 品名（卡罗拉）
        kind TEXT,              -- 种类（玫瑰花）
        color TEXT,             -- 颜色
        unit TEXT,              -- 单位（20枝/扎）
        price_c REAL,           -- C级价
        price_b REAL,           -- B级价
        price_a REAL,           -- A级价
        change TEXT,            -- 涨跌
        fetched_at TEXT,        -- 抓取时间
        UNIQUE(ts, category, name, color)
    )""")
    c.commit()

def main():
    c = sqlite3.connect(DB)
    init_db(c)
    today = datetime.date.today().isoformat()
    now = datetime.datetime.now().isoformat(timespec="seconds")

    total_new = 0
    for cid in range(1, 9):
        cat = CATEGORIES[cid]
        url = f"http://www.duood.com/GoodsList.aspx?id={cid}"
        try:
            html = fetch(url)
            items = parse_table(html)
            n = 0
            for it in items:
                cur = c.execute(
                    "SELECT 1 FROM dounan_prices WHERE ts=? AND category=? AND name=? AND color=?",
                    (today, cat, it["name"], it["color"])).fetchone()
                if cur:
                    continue
                c.execute("""INSERT INTO dounan_prices
                    (ts, category, name, kind, color, unit, price_c, price_b, price_a, change, fetched_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (today, cat, it["name"], it["kind"], it["color"], it["unit"],
                     it["price_c"], it["price_b"], it["price_a"], it["change"], now))
                n += 1
            c.commit()
            total_new += n
            log(f"  {cat}(id={cid}): {len(items)} 条, 新增 {n}")
        except Exception as e:
            log(f"  ❌ {cat}(id={cid}) 失败: {str(e)[:80]}")
        # 随机延时 1-2 秒（礼貌爬取）
        if cid < 8:
            time.sleep(random.uniform(1.0, 2.0))

    c.close()
    log(f"斗南品名级价格采集完成：今日新增 {total_new} 条")
    # 全部成功且无新增 = 静默（幂等）

if __name__ == "__main__":
    main()
