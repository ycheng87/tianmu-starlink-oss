#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
田亩星链 · 省农业农村厅行情采集（图片→OCR→入库）
数据源：云南省农业农村厅「市场动态-数据」栏目（每日转载）
  - 王旗营蔬菜批发平均价格统计（~79 品种，两栏表格）
  - 斗南花卉市场价格信息（~24 品种，最高/最低/均价）
识别：RapidOCR（离线免费）；结构化后处理按坐标分栏配对
入库：prices.db 新表 nync_veg_prices / nync_flower_prices（幂等）
用法：python3 nync_collect.py [日期YYYY-MM-DD，默认今天]
"""
import os
import re
import sys
import json
import time
import sqlite3
import datetime
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "prices.db")
LIST_URL = "https://nync.yn.gov.cn/html/yunnonggaikuang/shichangdongtai/shuju-new/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def log(msg):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def fetch(url, timeout=25, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            log(f"  抓取失败重试({i+1}/{retries}): {url[:80]} - {e}")
            time.sleep(3 * (i + 1))
    raise last


def fetch_text(url, timeout=25):
    return fetch(url, timeout).decode("utf-8", errors="replace")


def find_articles(list_html, date_str):
    """从列表页找当天日期的王旗营/斗南文章，返回 {type: (url, title)}"""
    mmdd = date_str.replace("-", "")[4:]  # YYYY-MM-DD → MMDD（URL 用 0805 格式）
    want = {
        "王旗营": "蔬菜批发平均价格统计",
        "斗南": "花卉价格信息",
    }
    found = {}
    for a_type, kw in want.items():
        pat = re.compile(r'href="(/html/2026/shuju-new_' + mmdd + r'/(\d+)\.html)"[^>]*>([^<]*' + kw + r'[^<]*)')
        m = pat.search(list_html)
        if m:
            found[a_type] = ("https://nync.yn.gov.cn" + m.group(1), m.group(3).strip())
    return found


def find_body_img(article_html):
    """文章页正文第一张大图（uploadfile 路径）"""
    m = re.search(r'<img[^>]+src="(/uploadfile/[^"]+\.(?:png|jpg|jpeg))"', article_html, re.I)
    return "https://nync.yn.gov.cn" + m.group(1) if m else None


def ocr_texts(img_bytes):
    """RapidOCR 识别，返回按 y 排序的 [(x, y, text)]"""
    from rapidocr_onnxruntime import RapidOCR
    tmp = "/tmp/nync_ocr_tmp.png"
    with open(tmp, "wb") as f:
        f.write(img_bytes)
    ocr = RapidOCR()
    result, _ = ocr(tmp)
    os.remove(tmp)
    if not result:
        return []
    boxes = []
    for box, text, conf in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        boxes.append((min(xs), min(ys), max(ys), text.strip()))
    boxes.sort(key=lambda r: (r[1], r[0]))  # y 优先
    return boxes


def split_columns(boxes, width):
    """按 x 坐标分左右两栏"""
    mid = width / 2
    left = [b for b in boxes if b[0] < mid]
    right = [b for b in boxes if b[0] >= mid]
    return left, right


def parse_two_col_table(boxes, width):
    """通用表格解析：按 y 聚类成行 → 行内按 x 排序 → 品名/价格/数量交替提取。
    兼容 1 栏 / 2 栏（4 列并排：品名|价|量|品名|价|量）任意布局。"""
    # 1. y 聚类成行
    sorted_boxes = sorted(boxes, key=lambda r: (r[1], r[0]))
    rows = []
    current = []
    last_y = None
    for x, y0, y1, text in sorted_boxes:
        if last_y is not None and abs(y0 - last_y) > 15:
            rows.append(current)
            current = []
        current.append((x, text))
        last_y = y0
    if current:
        rows.append(current)

    # 2. 行内交替解析
    parsed = []
    for row in rows:
        row.sort(key=lambda r: r[0])
        items_in_row = []
        cur = None
        for x, t in row:
            if re.search(r'[\u4e00-\u9fff]', t):  # 含中文 = 品名
                cur = {"name": t, "nums": []}
                items_in_row.append(cur)
            else:
                cleaned = t.replace(" ", "").replace("一", "-")
                if cur and re.fullmatch(r"\d+(\.\d+)?", cleaned):
                    cur["nums"].append(float(cleaned))
        for it in items_in_row:
            name = it["name"]
            if name in ("品名", "前一日交", "价格（元") or name.startswith("综合平均价") or name.startswith("总吨位") or ("年" in name and "月" in name) or name.startswith("昆明市"):
                continue
            price = it["nums"][0] if it["nums"] else None
            qty = it["nums"][1] if len(it["nums"]) > 1 else None
            if price is not None:
                parsed.append({"name": name, "price": price, "qty": qty})
    return parsed


def parse_flower_table(boxes, width):
    """斗南花卉：品名 | 单位 | 最高 | 最低 | 均价（5列，数据行纯数字）"""
    # 1. 按 x 聚类成列
    cols = []
    for x, y0, y1, text in boxes:
        placed = False
        for col in cols:
            if abs(x - col["x"]) < 60:
                col["items"].append((y0, text))
                placed = True
                break
        if not placed:
            cols.append({"x": x, "items": [(y0, text)]})
    cols.sort(key=lambda c: c["x"])
    if len(cols) < 4:
        return []
    name_col = cols[0]
    price_cols = cols[2:]  # 最高/最低/均价（x 递增）
    name_col["items"].sort(key=lambda r: r[0])

    # 2. 品名列行锚点聚类（合并 (多头)/(单头) 子行）
    anchors = []  # [(y_min, name)]
    for y0, t in name_col["items"]:
        if re.search(r"[(（]", t):  # 子行：合并到上一个
            if anchors and y0 - anchors[-1][0] < 50:
                anchors[-1] = (anchors[-1][0], anchors[-1][1] + t)
            continue
        anchors.append((y0, t))

    # 3. 每行匹配价格列
    out = []
    for y0, name in anchors:
        nums = []
        for col in price_cols:
            matched = None
            for py, pt in col["items"]:
                if abs(py - y0) < 35:
                    m = re.search(r"[\d.]+", pt)
                    if m:
                        matched = float(m.group())
                    break
            nums.append(matched)
        clean_name = name.replace(",", "").replace("（", "(")
        if len(nums) >= 3 and nums[0] is not None:
            out.append({"name": clean_name, "high": nums[0], "low": nums[1], "avg": nums[2]})
    return out


def get_img_size(img_bytes):
    """简单判断图片宽度（PNG IHDR）"""
    if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        w = int.from_bytes(img_bytes[16:20], "big")
        return w
    return 600  # 默认


def page_url(pg):
    """列表页 URL：第1页用目录页(index)，后续用 N.html"""
    base = "https://nync.yn.gov.cn/html/yunnonggaikuang/shichangdongtai/shuju-new/"
    return base if pg <= 1 else f"{base}{pg}.html"


def iter_articles(date_str, max_pages=8):
    """跨列表页找 date_str 的王旗营/斗南文章（翻页直到找不到更新日期或超过 max_pages）。
    返回 {type: (url, title)}；找不到返回空 dict。"""
    mmdd = date_str.replace("-", "")[4:]
    want = {"王旗营": "蔬菜批发平均价格统计", "斗南": "花卉价格信息"}
    found = {}
    for pg in range(1, max_pages + 1):
        html = fetch_text(page_url(pg))
        dts = set(re.findall(r'shuju-new_(\d{4})', html))
        if not dts or int(max(dts)) < int(mmdd):
            # 本页已全是更早日期，目标不在更后面
            break
        for a_type, kw in want.items():
            if a_type in found:
                continue
            pat = re.compile(r'href="(/html/2026/shuju-new_' + mmdd + r'/(\d+)\.html)"[^>]*>([^<]*' + kw + r'[^<]*)')
            m = pat.search(html)
            if m:
                found[a_type] = ("https://nync.yn.gov.cn" + m.group(1), m.group(3).strip())
        if len(found) == len(want):
            break
        time.sleep(0.4)
    return found


def main():
    # 兼容旧用法：日期(可多个) 或 --backfill=开始,结束
    args = []
    backfill = None
    for a in sys.argv[1:]:
        if a.startswith("--backfill="):
            backfill = a.split("=", 1)[1]
        else:
            args.append(a)
    if not args:
        dates = [datetime.date.today().isoformat()]
    elif len(args) >= 2:
        # 起止日期区间，逐日回填
        d1 = datetime.date.fromisoformat(args[0])
        d2 = datetime.date.fromisoformat(args[1])
        dates = [(d1 + datetime.timedelta(days=i)).isoformat()
                 for i in range((d2 - d1).days + 1)]
    else:
        dates = [args[0]]
    if backfill:
        b1, b2 = backfill.split(",")
        d1 = datetime.date.fromisoformat(b1)
        d2 = datetime.date.fromisoformat(b2)
        dates = [(d1 + datetime.timedelta(days=i)).isoformat()
                 for i in range((d2 - d1).days + 1)]

    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS nync_veg_prices(
        ts TEXT, name TEXT, price REAL, qty REAL,
        PRIMARY KEY(ts, name))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS nync_flower_prices(
        ts TEXT, name TEXT, high REAL, low REAL, avg_price REAL,
        PRIMARY KEY(ts, name))""")

    log(f"待处理日期 {len(dates)} 个: {dates[0]} ~ {dates[-1]}")
    ok = fail = 0
    for date_str in dates:
        # 断点续跑：两表该日期已有数据则跳过
        v_exist = conn.execute("SELECT 1 FROM nync_veg_prices WHERE ts=? LIMIT 1", (date_str,)).fetchone()
        f_exist = conn.execute("SELECT 1 FROM nync_flower_prices WHERE ts=? LIMIT 1", (date_str,)).fetchone()
        if v_exist and f_exist:
            log(f"  {date_str} 已有数据，跳过（断点续跑）")
            ok += 1
            continue
        log(f"--- 采集 {date_str} ---")
        articles = iter_articles(date_str)
        if not articles:
            log(f"  {date_str}: 当天文章未找到（未发布/周六日/翻页完），跳过")
            continue
        day_ok = True
        for a_type, (url, title) in articles.items():
            try:
                article_html = fetch_text(url)
                img_url = find_body_img(article_html)
                if not img_url:
                    log(f"    {a_type}: 未找到正文图片")
                    continue
                img_bytes = fetch(img_url)
                width = get_img_size(img_bytes)
                boxes = ocr_texts(img_bytes)
                log(f"    {a_type}: 图 {len(img_bytes)}B, OCR {len(boxes)} 框")
                if a_type == "王旗营":
                    items = parse_two_col_table(boxes, width)
                    n = 0
                    for it in items:
                        cur = conn.execute("SELECT 1 FROM nync_veg_prices WHERE ts=? AND name=?",
                                           (date_str, it["name"])).fetchone()
                        if cur:
                            continue
                        conn.execute("INSERT INTO nync_veg_prices(ts,name,price,qty) VALUES(?,?,?,?)",
                                     (date_str, it["name"], it["price"], it.get("qty")))
                        n += 1
                    conn.commit()
                    log(f"    王旗营入库 {n} 条（新）")
                else:
                    items = parse_flower_table(boxes, width)
                    n = 0
                    for it in items:
                        cur = conn.execute("SELECT 1 FROM nync_flower_prices WHERE ts=? AND name=?",
                                           (date_str, it["name"])).fetchone()
                        if cur:
                            continue
                        def num(s):
                            if isinstance(s, (int, float)):
                                return float(s)
                            m = re.search(r"[\d.]+", s or "")
                            return float(m.group()) if m else None
                        conn.execute("INSERT INTO nync_flower_prices(ts,name,high,low,avg_price) VALUES(?,?,?,?,?)",
                                     (date_str, it["name"], num(it.get("high")), num(it.get("low")), num(it.get("avg"))))
                        n += 1
                    conn.commit()
                    log(f"    斗南入库 {n} 条（新）")
            except Exception as e:
                day_ok = False
                log(f"    {a_type} 失败: {e}")
        if day_ok:
            ok += 1
        else:
            fail += 1
        time.sleep(0.5)
    conn.close()
    log(f"完成：成功 {ok} 天，失败/未找到 {fail} 天")
    return 0


if __name__ == "__main__":
    sys.exit(main())
