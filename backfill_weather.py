#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天气后报 · 昆明历史天气回填（tianqihoubao.com，GBK 编码）
数据源: https://www.tianqihoubao.com/lishi/kunming/month/YYYYMM.html
- 表格 class="weather-table"：日期 | 天气状况(白天/夜间) | 最高/最低气温 | 风力风向(白天/夜间)
- ⚠️ 必须带 Referer: https://www.tianqihoubao.com/lishi/kunming.htm（否则 403）
按月循环，断点续跑（已有月份的日期跳过），延时 0.6s/次
存储: prices.db 新表 hist_weather(ts, weather_day, weather_night, temp_high, temp_low, wind_day, wind_night, PRIMARY KEY(ts))
用法: python3 backfill_weather.py [起始YYYYMM] [结束YYYYMM，默认今天]
"""
import sqlite3, os, re, datetime, time, sys, urllib.request

BASE = os.path.expanduser("~/tianmu_starlink")
DB = os.path.join(BASE, "data", "prices.db")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def log(msg):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://www.tianqihoubao.com/lishi/kunming.htm",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def decode_html(raw):
    """网站实际返回 UTF-8（2026 实测），GBK 兼容：先 UTF-8 严格解码，失败再 GBK"""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def parse_month(html):
    """解析 weather-table，返回 [(ts, weather_day, weather_night, high, low, wind_day, wind_night)]"""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    out = []
    for r in rows:
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        if len(cells) < 4 or not re.match(r"^\d{4}年\d{1,2}月\d{1,2}日$", cells[0]):
            continue
        ts = datetime.datetime.strptime(cells[0], "%Y年%m月%d日").date().isoformat()
        daynight = cells[1].split("/")  # 白天/夜间(可能多个 /)
        weather_day = daynight[0].strip() if daynight else ""
        weather_night = daynight[-1].strip() if len(daynight) > 1 else ""
        t = re.findall(r"(-?\d+)℃", cells[2])
        high = int(t[0]) if t else None
        low = int(t[1]) if len(t) > 1 else None
        winds = cells[3].split("/")
        wind_day = winds[0].strip() if winds else ""
        wind_night = winds[-1].strip() if len(winds) > 1 else ""
        out.append((ts, weather_day, weather_night, high, low, wind_day, wind_night))
    return out


def main():
    today = datetime.date.today()
    start = sys.argv[1] if len(sys.argv) > 1 else "202001"
    end = sys.argv[2] if len(sys.argv) > 2 else today.strftime("%Y%m")
    y1, m1 = int(start[:4]), int(start[4:6])
    y2, m2 = int(end[:4]), int(end[4:6])
    months = []
    y, m = y1, m1
    while (y, m) <= (y2, m2):
        months.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    log(f"=== 天气回填 {start} ~ {end}，共 {len(months)} 个月 ===")

    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS hist_weather(
        ts TEXT, weather_day TEXT, weather_night TEXT,
        temp_high INTEGER, temp_low INTEGER,
        wind_day TEXT, wind_night TEXT,
        source TEXT DEFAULT '天气后报·民间整理',
        PRIMARY KEY(ts))""")
    # 旧库补列
    cols = [r[1] for r in c.execute("PRAGMA table_info(hist_weather)")]
    if 'source' not in cols:
        c.execute("ALTER TABLE hist_weather ADD COLUMN source TEXT DEFAULT '天气后报·民间整理'")
    c.execute("UPDATE hist_weather SET source='天气后报·民间整理' WHERE source IS NULL")
    total = skip = fail = 0
    for i, ym in enumerate(months):
        if i > 0:
            time.sleep(0.6)
        url = f"https://www.tianqihoubao.com/lishi/kunming/month/{ym}.html"
        try:
            html = decode_html(fetch(url))
            items = parse_month(html)
            if not items:
                log(f"  {ym}: 无数据（可能月份未收录/反爬）")
                fail += 1
                continue
            n = 0
            for it in items:
                existed = c.execute("SELECT 1 FROM hist_weather WHERE ts=?", (it[0],)).fetchone()
                if existed:
                    skip += 1
                    continue
                c.execute("INSERT INTO hist_weather VALUES(?,?,?,?,?,?,?,?)",
                          (*it, '天气后报·民间整理'))
                n += 1
            c.commit()
            total += n
            log(f"  {ym}: 新增 {n} 条（跳过 {skip}，累计 {total}）")
        except Exception as e:
            log(f"  {ym} 失败: {repr(e)[:120]}")
            fail += 1
    log(f"=== 天气回填完成：新增 {total} 条，跳过 {skip}，失败 {fail} 个月 ===")
    c.close()


if __name__ == "__main__":
    main()