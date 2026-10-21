#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""田亩星链 · 斗南花卉行情简讯采集（简讯级）
数据源：斗南花卉电子交易平台官网 https://cms-web.dounanflowers.com
接口：/admin/ArticlePublishedList（纯 GET，无需登录）

⚠️ 数据颗粒度标注：简讯级
  斗南官网发布的行情为「每日快讯/行情简评」，仅含：
  - 按色系的均价区间（如单头玫瑰 0.15-1.11元/枝）
  - 成交率（如 99.12%）
  不含：等级(A/B/C)细分价、具体品名价（卡罗拉/戴安娜）、供货量明细
  用途：市场趋势判断 / 宏观参考；不可作为直接交易决策依据

本脚本只存文章标题+日期（元数据），不解析价格明细。
等找到更细的数据入口（如 App/小程序抓包）再替换升级。

只存不推：cron no_agent 模式下 stdout 为空=不推送
用法: python3 dounan_collect.py
"""
import sqlite3, os, json, urllib.request, datetime, sys

BASE = os.path.expanduser("~/tianmu_starlink")
DB = os.path.join(BASE, "data", "prices.db")
API = "https://cms-web.dounanflowers.com/admin/ArticlePublishedList"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

def log(msg):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")

def http(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Referer": "https://cms-web.dounanflowers.com/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def init_db(c):
    c.execute("""CREATE TABLE IF NOT EXISTS dounan_articles(
        id TEXT PRIMARY KEY,          -- 文章ID
        ts TEXT,                      -- 行情日期 (YYYY-MM-DD)
        title TEXT,                   -- 完整标题
        category TEXT,                -- 拍卖行情 / 对手交易行情
        published_time TEXT,          -- 发布时间
        fetched_at TEXT,              -- 抓取时间
        data_grade TEXT DEFAULT '简讯级'  -- 数据颗粒度标注
    )""")
    c.commit()

def parse_title(title):
    """从标题提取日期和类别：斗南鲜花【拍卖行情】8月1日"""
    import re
    m = re.search(r"【([^】]+)】", title)
    category = m.group(1) if m else ""
    m2 = re.search(r"(\d+)月(\d+)日", title)
    if m2:
        month, day = int(m2.group(1)), int(m2.group(2))
        year = datetime.date.today().year
        ts = f"{year}-{month:02d}-{day:02d}"
        if ts > datetime.date.today().isoformat():
            ts = f"{year-1}-{month:02d}-{day:02d}"
        return ts, category
    return "", category

def main():
    c = sqlite3.connect(DB)
    init_db(c)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        data = http(API)
    except Exception as e:
        log(f"❌ 斗南接口请求失败: {e}")
        c.close()
        sys.exit(1)

    models = data.get("models") or []
    if not models:
        log("⚠️ 接口返回空")
        c.close()
        sys.exit(0)

    n_new, n_dup = 0, 0
    for m in models:
        aid = m.get("id")
        title = (m.get("title") or "").strip()
        if not aid or not title:
            continue
        # 只存行情类文章（拍卖/对手交易），过滤其他新闻
        if "行情" not in title:
            continue
        ts, category = parse_title(title)
        pub = m.get("publishedTime") or ""
        cur = c.execute("SELECT 1 FROM dounan_articles WHERE id=?", (aid,)).fetchone()
        if cur:
            n_dup += 1
            continue
        c.execute("INSERT INTO dounan_articles(id,ts,title,category,published_time,fetched_at,data_grade) "
                  "VALUES(?,?,?,?,?,?,'简讯级')",
                  (aid, ts, title, category, pub, now))
        n_new += 1
    c.commit()
    c.close()

    if n_new:
        log(f"斗南简讯采集：新增 {n_new} 篇，重复 {n_dup} 篇（简讯级，仅标题+日期）")
    # 完全无新增 = 静默

if __name__ == "__main__":
    main()
