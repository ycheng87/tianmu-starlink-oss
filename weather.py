#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""田亩星链 · 天气采集模块（和风天气 QWeather）
- 免费版：5万次/月，县域天气 + 预警全免费
- 采集: 指定地点的当日天气 + 3天预报，写入 weather 表（含 precip/wind_scale/text_day/text_night）
- 预警: 命中规则时写 alerts(type='weather')，当天幂等（先删当天再插，重跑不重复）
- 背景: 连续≥3天降水/雨 → 生成「雨季」背景（叶菜供应减少价格易涨）；低温/大风同理（花卉）
  背景以 context 预警形式写入 alerts（type='context'），当天幂等
- 用法: python3 weather.py   （读取 ~/.tms_weather_key 中的 API Key）
- 注册: https://console.qweather.com（邮箱注册即可，免费版）
  API Key 填入 ~/.tms_weather_key（第一行，末尾无换行也行）
"""
import sqlite3, os, json, urllib.request, datetime, sys, gzip, time

BASE = os.path.expanduser("~/tianmu_starlink")
DB = os.path.join(BASE, "data", "prices.db")
KEY_FILE = os.path.expanduser("~/.tms_weather_key")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
# 和风天气新账号必须用专属子域名访问 API（devapi 会报 403 Invalid Host）
API_HOST = "https://n34wcw83bv.re.qweatherapi.com"
# 温度骤降阈值（°C）：明天最低温比今天最低温低超过该值 → 生成降温提醒
TEMP_DROP = 6.0
# 暴雨/大雨降雨量阈值（mm）：precip ≥ 此值 认为强降水（配合文本）
HEAVY_RAIN_MM = 25.0
# 大风风力等级阈值：windScale ≥ 此级 认为大风
WIND_SCALE_LEVEL = 6
# 雨季判定：连续 ≥N 天有降水（precip>0 或 文本含"雨"）
RAINY_DAYS = 3
# 背景展示用的上一个交易日价格日期（见 gen_background）

# 关注地点：昆明 14 区县 + 周边主要州市（LocationID 由和风 GeoAPI /geo/v2/city/lookup 验证，
# 2026-08-16 统一以 GeoAPI 权威为准，晋宁=101290105 等——历史用 101290110/101290106/101290111 为错误偏移，已修正）
LOCATIONS = {
    # ── 昆明 14 区县 ──
    "昆明": "101290101",        # 昆明市区
    "昆明-五华": "101290102",   # 五华区
    "昆明-东川": "101290103",   # 东川区
    "昆明-寻甸": "101290104",   # 寻甸县
    "昆明-晋宁": "101290105",   # 晋宁区（花卉主产区，GeoAPI 权威 ID）
    "昆明-宜良": "101290106",   # 宜良县
    "昆明-石林": "101290107",   # 石林县
    "昆明-呈贡": "101290108",   # 呈贡区
    "昆明-富民": "101290109",   # 富民县
    "昆明-嵩明": "101290110",   # 嵩明县（蔬菜产区）
    "昆明-禄劝": "101290111",   # 禄劝县
    "昆明-安宁": "101290112",   # 安宁市
    "昆明-盘龙": "101290114",   # 盘龙区
    "昆明-官渡": "101290115",   # 官渡区
    "昆明-西山": "101290116",   # 西山区
    # ── 周边主要州市 ──
    "大理州": "101290201",      # 大理
    "红河州": "101290301",      # 红河
    "曲靖市": "101290401",      # 曲靖
    "文山州": "101290601",      # 文山
    "玉溪市": "101290701",      # 玉溪
    "楚雄市": "101290811",      # 楚雄
}

# 部分地点通用中文名→LOCATIONS 内部键 别名（逆地理/入参归一化用）
ALIASES = {
    "晋宁": "昆明-晋宁", "宜良": "昆明-宜良", "嵩明": "昆明-嵩明",
    "禄劝": "昆明-禄劝", "寻甸": "昆明-寻甸", "石林": "昆明-石林",
    "安宁": "昆明-安宁", "呈贡": "昆明-呈贡", "富民": "昆明-富民",
    "五华": "昆明-五华", "盘龙": "昆明-盘龙", "官渡": "昆明-官渡",
    "西山": "昆明-西山", "东川": "昆明-东川",
    "大理": "大理州", "红河": "红河州", "曲靖": "曲靖市",
    "文山": "文山州", "玉溪": "玉溪市", "楚雄": "楚雄市",
}
# GeoAPI 权威 ID → LOCATIONS 内部键（供入参 ID 归一化）
ID2NAME = {v: k for k, v in LOCATIONS.items()}
# 和风 LocationID → 本地 weather 表展示名（用于 /weather?location=ID 查询）
DISPLAY_NAMES = {v: k for k, v in LOCATIONS.items()}

def log(msg):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")

def http(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return json.loads(data.decode())

def load_key():
    if not os.path.exists(KEY_FILE):
        log(f"❌ 未找到 API Key 文件 {KEY_FILE}，请先注册和风天气并把 Key 填入")
        return None
    with open(KEY_FILE) as f:
        return f.read().strip()

def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def _wind_scale(v):
    """windScaleDay 形如 '3' / '小于3级' / '10-12'，取主等级整数；无法解析返回 None"""
    if v is None:
        return None
    s = str(v)
    import re
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else None

def _is_rainy(day):
    """判断某日是否降水：precip>0 或 文本含雨"""
    precip = _to_float(day.get("precip"))
    if precip is not None and precip > 0:
        return True
    for k in ("textDay", "textNight"):
        t = str(day.get(k) or "")
        if "雨" in t or "雪" in t:
            return True
    return False


# ─────────────────────────────────────────────
# 一、预警判定 + 幂等写入（当天先删再插）
# ─────────────────────────────────────────────
def _clear_alerts(c, typ, ts):
    """当天该类型先删除（幂等），再重新插入"""
    c.execute("DELETE FROM alerts WHERE type=? AND ts=?", (typ, ts))

def _add_alert(c, typ, ts, category, title, detail):
    c.execute("INSERT INTO alerts(ts,type,category,title,detail) VALUES(?,?,?,?,?)",
              (ts, typ, category, title, detail))

def process_alerts(c, ts, daily):
    """遍历各地点，按规则生成天气预警。daily: {地点: [today, tomorrow, ...3日]}"""
    _clear_alerts(c, "weather", ts)
    n = 0
    for name, days in daily.items():
        if len(days) < 2:
            continue
        today, tomorrow = days[0], days[1]
        today_min = _to_float(today.get("tempMin"))
        tomorrow_min = _to_float(tomorrow.get("tempMin"))
        # 1) 温度骤降：明天最低比今天最低低 ≥ TEMP_DROP
        if (today_min is not None and tomorrow_min is not None
                and today_min - tomorrow_min >= TEMP_DROP):
            title = f"🌡️ 降温提醒：{name} 明日最低 {tomorrow_min:.0f}°C"
            detail = (f"今日最低 {today_min:.0f}°C → 明日最低 {tomorrow_min:.0f}°C，"
                      f"骤降 {today_min - tomorrow_min:.0f}°C，注意防霜冻/保暖")
            _add_alert(c, "weather", ts, name, title, detail)
            n += 1
        # 2) 暴雨/大雨：文本含 暴雨/大雨/中雨 或 precip ≥ HEAVY_RAIN_MM
        today_precip = _to_float(today.get("precip"))
        text_day = str(today.get("textDay") or "")
        text_night = str(today.get("textNight") or "")
        heavy_text = any(k in text_day + text_night for k in ("暴雨", "大雨", "中雨"))
        if heavy_text or (today_precip is not None and today_precip >= HEAVY_RAIN_MM):
            why = "降水" if today_precip is not None else "天气"
            fdate = today.get("date") or today.get("fxDate") or ""
            title = f"🌧️ {name} 强降水提醒"
            detail = (f"{fdate} 预报 {text_day}/{text_night}"
                      f"，降雨量 {today_precip if today_precip is not None else '未知'}mm，"
                      f"注意排水防涝，露地作物防渍害")
            _add_alert(c, "weather", ts, name, title, detail)
            n += 1
        # 3) 大风：风力等级 ≥ WIND_SCALE_LEVEL（花卉/大棚防倒伏）
        wind = _wind_scale(today.get("windScaleDay"))
        if wind is not None and wind >= WIND_SCALE_LEVEL:
            title = f"💨 {name} 大风提醒"
            detail = (f"今日风力 {wind} 级（{today.get('windDirDay','')}风），"
                      f"大棚/花卉防倒伏，注意加固")
            _add_alert(c, "weather", ts, name, title, detail)
            n += 1
    c.commit()
    log(f"天气预警处理完成：今日新增 {n} 条(type=weather)")


# ─────────────────────────────────────────────
# 二、大背景（先跑起来攒数据）：连续降水→雨季 / 低温大风→花卉
#    产出形式：alerts(type='context')，当天幂等；数据留痕供后续消费
# ─────────────────────────────────────────────
def process_background(c, ts, daily):
    """根据各地点最近连续降水天数，生成「雨季」等背景提示。
    daily: {地点: [最近的天数列表(倒序, 最早在前)] } —— 这里传的是3日预报的截断，
    无法覆盖历史，因此改为查询 weather 表累计连续降水天数。"""
    _clear_alerts(c, "context", ts)
    n = 0
    for name in LOCATIONS:
        # 取该地点所有历史天气（含本次已写入，ts 已提交），按日期正序
        rows = c.execute(
            "SELECT ts, precip_mm, text_day, text_night FROM weather "
            "WHERE location=? ORDER BY ts ASC", (name,)).fetchall()
        if not rows:
            continue
        # 从最新一天向前数连续降水天数
        streak = 0
        for r in reversed(rows):
            precip = r[1]
            text_all = f"{r[2] or ''}{r[3] or ''}"
            rainy = (precip is not None and precip > 0) or "雨" in text_all or "雪" in text_all
            if rainy:
                streak += 1
            else:
                break
        if streak >= RAINY_DAYS:
            title = f"🌧️ 背景·雨季（{name}）"
            detail = (f"已连续 {streak} 天降水，雨季叶菜供应减少、价格易涨；"
                      f"建议叶菜类关注涨价、露地作物防渍")
            _add_alert(c, "context", ts, name, title, detail)
            n += 1
            log(f"  📌 {name}: 雨季背景（连续{streak}天降水）")
    c.commit()
    if n:
        log(f"大背景处理完成：今日新增 {n} 条(type=context)")
    else:
        log("大背景处理完成：今日无命中（雨季/低温大风未触发）")


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def fetch(c, key):
    today = datetime.date.today().isoformat()
    daily = {}   # {地点: [today, tomorrow, ...]}
    for name, loc_id in LOCATIONS.items():
        try:
            # 3天预报（含 precip/windScaleDay/textDay/textNight），作为当日规范数据源
            f3 = http(f"{API_HOST}/v7/weather/3d?location={loc_id}&key={key}")
            if f3.get("code") != "200":
                log(f"  {name}: 3天预报接口异常 code={f3.get('code')} {f3.get('error')}")
                continue
            d3 = f3["daily"]   # [今天, 明天, 后天]
            t0 = d3[0]
            temp_max = _to_float(t0.get("tempMax") or t0.get("temp"))
            temp_min = _to_float(t0.get("tempMin") or t0.get("temp"))
            precip = _to_float(t0.get("precip"))
            wind = _wind_scale(t0.get("windScaleDay"))
            text_day = t0.get("textDay")
            text_night = t0.get("textNight")
            cond = text_day or text_night or t0.get("text")
            c.execute("""INSERT OR REPLACE INTO weather
                (ts,location,temp_max,temp_min,condition_text,precip_mm,wind_scale,text_day,text_night)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (today, name, temp_max, temp_min, cond, precip, wind, text_day, text_night))
            daily[name] = d3
            log(f"  {name}: {cond} {temp_max if temp_max is not None else '?'}°C"
                f"({temp_min if temp_min is not None else '?'}°C)"
                f" 降水{precip if precip is not None else 0}mm 风{wind if wind is not None else '?'}级")
        except Exception as e:
            log(f"  {name} 失败: {e}")
        time.sleep(0.5)  # GeoAPI/天气接口 0.5s 延时，防免费版限流
    c.commit()
    return daily

def main():
    key = load_key()
    if not key:
        sys.exit(1)
    c = sqlite3.connect(DB)
    log("=== 天气采集开始 ===")
    daily = fetch(c, key)
    if daily:
        process_alerts(c, datetime.date.today().isoformat(), daily)
        process_background(c, datetime.date.today().isoformat(), daily)
    log("=== 天气采集结束 ===")
    c.close()

if __name__ == "__main__":
    main()
