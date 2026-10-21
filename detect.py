#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""田亩星链 · 波动检测模块
对最近两天的价格算涨跌幅，超过阈值(默认 ±10%)就写一条预警到 alerts 表。
- 蔬菜: 按 (市场, 品种) 对比 昨天 vs 今天
- 花卉: 按 品种 对比最近两个交易日的均价
- 幂等: 同一天同一品种的重复预警会先删除再写（重跑不产生重复）

数据卫生(2026-08-14 小墨双份核验整改)：
  1. 市场废弃识别: 某 market 最新数据早于 today-STALE_DAYS 判定为废弃，
     从复算候选排除(不再为其写新预警)，并清理其遗留的所有 price 旧预警。
     背景: "昆明市王旗营蔬菜批发市场有限公司" 08-10 止数据废弃，
           被 "昆明景臻王旗营蔬菜批发市场"(08-11起) 接管。
  2. 有效市场近2条兜底: 对每个有效 market+品种，只保留最近2条 price 预警，
     删除更早的历史残留(警报表不再无限膨胀)。
用法: python3 detect.py [阈值%]
"""
import sqlite3, os, sys, datetime

BASE = os.path.expanduser("~/tianmu_starlink")
DB = os.path.join(BASE, "data", "prices.db")
THRESHOLD = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0  # 默认 ±10%
STALE_DAYS = 3  # 市场最新数据早于今天 N 天 → 判为废弃市场
# 注: 2026-08-14 采集源切换——旧市场"昆明市王旗营..."08-10止数据废弃,由
#   "昆明景臻王旗营..."(08-11起)接管。断更4天即需清理，故设3天(而非7)以覆盖切换场景；
#   周末/单日停更(如通海08-03空1天)不达3天不会误伤活跃市场。

def log(msg):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")

def detect_stale_markets(c, today):
    """返回废弃市场名集合：vegetable 市场最新数据日期早于 today-STALE_DAYS。"""
    cutoff = (datetime.date.fromisoformat(today)
              - datetime.timedelta(days=STALE_DAYS)).isoformat()
    stale = set()
    for (market, max_ts) in c.execute(
            "SELECT market, MAX(ts) FROM veg_prices GROUP BY market").fetchall():
        if market and max_ts and max_ts < cutoff:
            stale.add(market)
    return stale

def cleanup_stale_market_alerts(c, stale_markets):
    """清理废弃市场遗留的 price 预警（品种已由新市场接管，旧预警纯噪音）。"""
    if not stale_markets:
        return 0
    # 逐一删除(避免 IN 绑定过多)，同时按 market 全清(不区分 category)
    deleted = 0
    for m in stale_markets:
        cur = c.execute(
            "DELETE FROM alerts WHERE type='price' AND market=?", (m,))
        deleted += cur.rowcount
    return deleted

def cleanup_active_market_alerts(c, today, stale_markets):
    """有效市场兜底：每个 market+品种 只保留最近 2 条 price 预警，删除更早残留。
    对废弃市场跳过(已在上一步全清)。"""
    deleted = 0
    # 所有 price 预警按照 market+category 分组(蔬菜 market 非空；花卉 market 为 NULL)
    rows = c.execute(
        "SELECT market, category FROM alerts WHERE type='price' "
        "GROUP BY market, category").fetchall()
    for market, category in rows:
        if market in stale_markets:
            continue  # 废弃市场已全清
        # 取该组的 id，按 ts 降序，跳过前 2 条(保留)，删其余
        ids = [r[0] for r in c.execute(
            "SELECT id FROM alerts WHERE type='price' AND market IS ? AND category=? "
            "ORDER BY ts DESC, id DESC",
            (market, category)).fetchall()]
        if len(ids) > 2:
            drop = ids[2:]
            # 分块删除避免绑定参数过多
            chunk = 500
            for i in range(0, len(drop), chunk):
                part = drop[i:i + chunk]
                q = ",".join("?" * len(part))
                cur = c.execute(f"DELETE FROM alerts WHERE id IN ({q})", part)
                deleted += cur.rowcount
    return deleted

def main():
    c = sqlite3.connect(DB)
    today = datetime.date.today().isoformat()

    # ── 0. 数据卫生：识别废弃市场并清理旧预警 ──
    stale = detect_stale_markets(c, today)
    if stale:
        log(f"废弃市场({STALE_DAYS}天无数据): {sorted(stale)}")
        nd = cleanup_stale_market_alerts(c, stale)
        log(f"清理废弃市场旧 price 预警: {nd} 条")
    else:
        log("无废弃市场")
    na = cleanup_active_market_alerts(c, today, stale)
    if na:
        log(f"有效市场近2条兜底清理: {na} 条")
    c.commit()

    # 删除今天已有的价格类预警（重跑幂等）
    c.execute("DELETE FROM alerts WHERE type='price' AND ts=?", (today,))

    n = 0
    # ── 1. 蔬菜：按 (market, variety) 找最近两个不同日期(排除废弃市场) ──
    if stale:
        rows = c.execute(
            "SELECT market, variety FROM veg_prices "
            "WHERE ts <= ? AND market NOT IN ({}) "
            "GROUP BY market, variety".format(",".join("?" * len(stale))),
            (today, *sorted(stale))).fetchall()
    else:
        rows = c.execute(
            "SELECT market, variety FROM veg_prices "
            "WHERE ts <= ? GROUP BY market, variety",
            (today,)).fetchall()
    for market, variety in rows:
        dates = [r[0] for r in c.execute(
            "SELECT DISTINCT ts FROM veg_prices WHERE market=? AND variety=? AND ts<=? ORDER BY ts DESC LIMIT 2",
            (market, variety, today))]
        if len(dates) < 2:
            continue
        d_old, d_new = dates[1], dates[0]
        p_old = c.execute("SELECT price FROM veg_prices WHERE market=? AND variety=? AND ts=?",
                          (market, variety, d_old)).fetchone()
        p_new = c.execute("SELECT price FROM veg_prices WHERE market=? AND variety=? AND ts=?",
                          (market, variety, d_new)).fetchone()
        if not p_old or not p_new or not p_old[0]:
            continue
        pct = (p_new[0] - p_old[0]) / p_old[0] * 100
        if abs(pct) >= THRESHOLD:
            arrow = "📈" if pct > 0 else "📉"
            title = f"{arrow} {variety}({market}) {pct:+.1f}%"
            detail = f"{d_old} ¥{p_old[0]:.2f}/kg → {d_new} ¥{p_new[0]:.2f}/kg"
            # 幂等去重：写入前删除同一(日期,品种,涨跌幅)旧预警，重跑不产生重复
            c.execute(
                "DELETE FROM alerts WHERE ts=? AND type='price' AND category=? AND title=? AND change_pct=?",
                (d_new, variety, title, round(pct, 1)))
            c.execute("INSERT INTO alerts(ts,type,category,market,title,detail,change_pct) VALUES(?,?,?,?,?,?,?)",
                      (d_new, "price", variety, market, title, detail, round(pct, 1)))
            n += 1

    # ── 2. 花卉：按品种对比最近两个交易日 ──
    breeds = [r[0] for r in c.execute(
        "SELECT DISTINCT breed FROM flower_prices WHERE ts <= ?", (today,))]
    for breed in breeds:
        dates = [r[0] for r in c.execute(
            "SELECT DISTINCT ts FROM flower_prices WHERE breed=? AND ts<=? ORDER BY ts DESC LIMIT 2",
            (breed, today))]
        if len(dates) < 2:
            continue
        d_old, d_new = dates[1], dates[0]
        p_old = c.execute("SELECT avg_price FROM flower_prices WHERE breed=? AND ts=?",
                          (breed, d_old)).fetchone()
        p_new = c.execute("SELECT avg_price FROM flower_prices WHERE breed=? AND ts=?",
                          (breed, d_new)).fetchone()
        if not p_old or not p_new or not p_old[0]:
            continue
        pct = (p_new[0] - p_old[0]) / p_old[0] * 100
        if abs(pct) >= THRESHOLD:
            arrow = "📈" if pct > 0 else "📉"
            title = f"{arrow} {breed} {pct:+.1f}%"
            detail = f"{d_old} ¥{p_old[0]:.2f}/枝 → {d_new} ¥{p_new[0]:.2f}/枝"
            # 幂等去重（见蔬菜注释）
            c.execute(
                "DELETE FROM alerts WHERE ts=? AND type='price' AND category=? AND title=? AND change_pct=?",
                (d_new, breed, title, round(pct, 1)))
            c.execute("INSERT INTO alerts(ts,type,category,title,detail,change_pct) VALUES(?,?,?,?,?,?)",
                      (d_new, "price", breed, title, detail, round(pct, 1)))
            n += 1

    c.commit()
    log(f"波动检测完成：阈值 ±{THRESHOLD}%，今日新增 {n} 条预警")
    c.close()

if __name__ == "__main__":
    main()
