#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""田亩星链 · 统一数据库初始化（幂等，可重复执行）
用法: python3 db_schema.py
"""
import sqlite3, os

BASE = os.path.expanduser("~/tianmu_starlink")
DB = os.path.join(BASE, "data", "prices.db")

# 存量库迁移：为已存在的 weather 表补齐新增列（幂等，缺哪列补哪列）
WEATHER_NEW_COLS = {
    "precip_mm": "REAL",
    "wind_scale": "INTEGER",
    "text_day": "TEXT",
    "text_night": "TEXT",
}

def migrate(c):
    cols = {r[1] for r in c.execute("PRAGMA table_info(weather)").fetchall()}
    for name, typ in WEATHER_NEW_COLS.items():
        if name not in cols:
            c.execute(f"ALTER TABLE weather ADD COLUMN {name} {typ}")
            print(f"✅ weather 表新增列: {name} {typ}")
    c.commit()

SCHEMA = """
-- 蔬菜价格（已有）
CREATE TABLE IF NOT EXISTS veg_prices(
  ts TEXT, market TEXT, variety TEXT, price REAL,
  PRIMARY KEY(ts, market, variety));

-- 花卉价格（已有）
CREATE TABLE IF NOT EXISTS flower_prices(
  ts TEXT, breed TEXT, avg_price REAL, highest REAL,
  PRIMARY KEY(ts, breed));

-- KIFA 指数（已有）
CREATE TABLE IF NOT EXISTS kifa_index(
  ts TEXT, price_index_a REAL, price_index_q REAL,
  PRIMARY KEY(ts));

-- 天气（按 日期+地点 一行）
CREATE TABLE IF NOT EXISTS weather(
  ts TEXT, location TEXT,
  temp_max REAL, temp_min REAL,
  condition_text TEXT,
  precip_mm REAL,        -- 降雨量(mm)
  wind_scale INTEGER,    -- 风力等级
  text_day TEXT,         -- 白天天气现象
  text_night TEXT,       -- 夜间天气现象
  PRIMARY KEY(ts, location));

-- 预警中心（价格异动 + 天气预警 统一入库）
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,               -- 发生日期
  type TEXT,             -- 'price' 价格异动 / 'weather' 天气预警
  category TEXT,         -- 品种名 / 地点
  market TEXT,           -- 市场（价格类）
  title TEXT,            -- 一句话标题
  detail TEXT,           -- 详情说明
  change_pct REAL,       -- 涨跌幅 %（价格类）
  is_read INTEGER DEFAULT 0
);

-- 关注列表（预留多用户，user_id 默认 'default'）
CREATE TABLE IF NOT EXISTS watchlist(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT DEFAULT 'default',
  item_type TEXT,        -- 'veg' / 'flower' / 'location'
  item_key TEXT,         -- 品种名 或 地点
  market TEXT,           -- 市场（veg 用；flower/location 为 NULL）
  created_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(user_id, item_type, item_key, market));
"""

def init():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    migrate(c)   # 存量 weather 表补齐新增列
    c.commit()
    tables = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    c.close()
    print("✅ 数据库就绪:", DB)
    print("   表:", ", ".join(tables))

if __name__ == "__main__":
    init()
