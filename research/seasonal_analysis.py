#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""田亩星链·第一轮预测验证：KIFA指数季节性分析
输入：prices.db kifa_index（2014-12~2026-08，全年无休）
输出：节日效应/月度规律/周内规律 → 预测可行性报告
"""
import sqlite3, os, datetime, statistics
from collections import defaultdict
from lunarcalendar import Converter, Solar, Lunar

DB = os.path.expanduser("~/tianmu_starlink/data/prices.db")
conn = sqlite3.connect(DB)
cur = conn.cursor()

rows = cur.execute("SELECT ts, price_index_a FROM kifa_index WHERE price_index_a IS NOT NULL").fetchall()
data = {ts: a for ts, a in rows}  # ts -> index_a
dates_sorted = sorted(data.keys())

def idx(ts):
    return data.get(ts)

def avg_range(start_ts, end_ts):
    """[start, end] 闭区间日均指数"""
    vals = [v for t, v in data.items() if start_ts <= t <= end_ts]
    return statistics.mean(vals) if vals else None

def shift_days(d, n):
    return (d + datetime.timedelta(days=n)).isoformat()

# ---------- 节日表（2020-2026，农历用库算） ----------
FESTIVALS = {}
def add_fest(name, dates):
    for y, md in dates.items():
        FESTIVALS.setdefault(name, []).append((y, md))

# 阳历固定
solar = {
    "元旦": {y: (1, 1) for y in range(2020, 2027)},
    "情人节": {y: (2, 14) for y in range(2020, 2027)},
    "妇女节": {y: (3, 8) for y in range(2020, 2027)},
    "5.20": {y: (5, 20) for y in range(2020, 2027)},
    "教师节": {y: (9, 10) for y in range(2020, 2027)},
    "国庆": {y: (10, 1) for y in range(2020, 2027)},
    "圣诞": {y: (12, 25) for y in range(2020, 2027)},
}
for name, d in solar.items():
    add_fest(name, d)

# 农历节日（lunarcalendar 计算）：春节=正月初一、七夕=七月初七、中秋=八月十五
for y in range(2020, 2027):
    cny = Converter.Lunar2Solar(Lunar(y, 1, 1))
    qx = Converter.Lunar2Solar(Lunar(y, 7, 7))
    mid = Converter.Lunar2Solar(Lunar(y, 8, 15))
    add_fest("春节", {y: (cny.month, cny.day)})
    add_fest("七夕", {y: (qx.month, qx.day)})
    add_fest("中秋", {y: (mid.month, mid.day)})

# 母亲节=5月第2个周日、父亲节=6月第3个周日
def nth_sunday(y, m, n):
    d = datetime.date(y, m, 1)
    first_sun = d + datetime.timedelta(days=(6 - d.weekday()) % 7)
    return first_sun + datetime.timedelta(weeks=n - 1)
add_fest("母亲节", {y: (nth_sunday(y, 5, 2).month, nth_sunday(y, 5, 2).day) for y in range(2020, 2027)})
add_fest("父亲节", {y: (nth_sunday(y, 6, 3).month, nth_sunday(y, 6, 3).day) for y in range(2020, 2027)})

# ---------- 节日效应分析 ----------
print("=" * 70)
print("【1】节日效应（前7天 vs 后7天 vs 基线，2020-2026）")
print("=" * 70)
print(f"{'节日':<6}{'样本':<4}{'前7天均涨%':<10}{'前7方向准确率':<12}{'后7天均涨%':<10}{'后7方向':<8}{'峰值日':<6}")
results = []
for name in ["春节", "情人节", "七夕", "中秋", "母亲节", "5.20", "教师节", "妇女节", "国庆", "圣诞", "元旦", "父亲节"]:
    fs = FESTIVALS.get(name, [])
    pre_gains, post_gains, pre_dirs, post_dirs = [], [], [], []
    peak_offsets = []
    for y, (m, d) in fs:
        if (m, d) == (2, 29):
            continue
        fday = datetime.date(y, m, d)
        fts = fday.isoformat()
        base = avg_range(shift_days(fday, -25), shift_days(fday, -15))  # 基线=前15~25天
        # 窗口内可用数据（不要求节日当天有数据：春节/中秋常停市）
        pre_vals = [data[t] for t in data if shift_days(fday, -7) <= t <= shift_days(fday, -1)]
        post_vals = [data[t] for t in data if shift_days(fday, 1) <= t <= shift_days(fday, 7)]
        if not base or len(pre_vals) < 5 or len(post_vals) < 5 or base == 0:
            continue
        pre = statistics.mean(pre_vals)
        post = statistics.mean(post_vals)
        pre_g = (pre - base) / base * 100
        post_g = (post - base) / base * 100
        pre_gains.append(pre_g); post_gains.append(post_g)
        pre_dirs.append(1 if pre_g > 0 else 0)
        post_dirs.append(1 if post_g > 0 else 0)
        # 峰值日（窗口内哪天最高）
        win = [(shift_days(fday, o), data.get(shift_days(fday, o))) for o in range(-7, 8)]
        win = [x for x in win if x[1]]
        if win:
            peak_off = max(win, key=lambda x: x[1])[0]
            try:
                peak_offsets.append((datetime.date.fromisoformat(peak_off) - fday).days)
            except:
                pass
    n = len(pre_gains)
    if n < 5:
        continue
    avg_pre = statistics.mean(pre_gains)
    avg_post = statistics.mean(post_gains)
    pre_acc = sum(pre_dirs) / n * 100
    post_acc = sum(post_dirs) / n * 100
    peak = statistics.median(peak_offsets) if peak_offsets else None
    results.append((name, n, avg_pre, pre_acc, avg_post, post_acc, peak))
    print(f"{name:<6}{n:<4}{avg_pre:>+7.1f}%  {pre_acc:>5.0f}%   {avg_post:>+7.1f}%  {post_acc:>3.0f}%   {peak}")

print()
print("=" * 70)
print("【2】月度规律（2020-2026 各月相对全年均值）")
print("=" * 70)
by_month = defaultdict(list)
for ts, v in data.items():
    y = int(ts[:4])
    if 2020 <= y <= 2026:
        by_month[int(ts[5:7])].append(v)
yr_avg = statistics.mean([v for t, v in data.items() if 2020 <= int(t[:4]) <= 2026])
for m in range(1, 13):
    vals = by_month[m]
    if vals:
        mm = statistics.mean(vals)
        print(f"{m:>2}月: 均值{mm:6.1f}  相对全年{ (mm-yr_avg)/yr_avg*100:>+5.1f}%  样本{len(vals)}")

print()
print("=" * 70)
print("【3】周内规律（2020-2026 全样本 + 非节日周）")
print("=" * 70)
by_dow = defaultdict(list)
fest_days = set()
for name, fs in FESTIVALS.items():
    for y, (m, d) in fs:
        if m != 2 or d != 29:
            fest_days.add(datetime.date(y, m, d))
        else:
            fest_days.add(datetime.date(y, 2, 28))
# 节日窗口（±3天）剔除
for ts, v in data.items():
    y = int(ts[:4])
    if not (2020 <= y <= 2026):
        continue
    d = datetime.date.fromisoformat(ts)
    in_window = any(abs((d - f).days) <= 3 for f in fest_days if f.year == y)
    if not in_window:
        by_dow[d.weekday()].append(v)
dow_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
for i in range(7):
    vals = by_dow[i]
    if vals:
        print(f"{dow_names[i]}: 均值{statistics.mean(vals):6.1f}  样本{len(vals)}")
