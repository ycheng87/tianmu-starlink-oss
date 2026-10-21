#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""田亩星链 · API 服务（纯标准库，零依赖）
提供小程序/网页要用的 JSON 接口：
  GET  /api/health                   健康检查
  GET  /api/quotes/veg               今日蔬菜行情（含涨跌幅）
  GET  /api/quotes/flower            今日花卉行情（含涨跌幅）
  GET  /api/alerts                   消息中心（预警列表）
  POST /api/alerts/{id}/read         标记已读
  GET  /api/watchlist                关注列表
  POST /api/watchlist                添加关注  body: {"item_type":"veg","item_key":"大白菜","market":"..."}
  DELETE /api/watchlist/{id}         取消关注
  GET  /api/weather?loc=昆明         天气（含预警）
用法: python3 server.py [端口]   默认 8080

── API v1（小程序，端口 8090，设计稿 research/API设计稿_v1.md）──
  GET  /api/v1/quotes                今日行情聚合
  GET  /api/v1/history?type=&days=   历史走势
  GET  /api/v1/festivals             节日事件日历
  GET  /api/v1/alerts?category=&date= 波动预警
  GET  /api/v1/weather?location=ID|中文名|经度,纬度  实时天气+预警（三态入参）
  GET  /api/v1/geo?lat=&lon=   逆地理定位+该地天气
  GET  /api/v1/health                健康检查（health.json 透传）
  POST /api/v1/subscribe             订阅协议（v1.1 预留占位）
鉴权: X-API-Key 请求头（配置文件 ~/.tms_api_keys，第一行key，后续行IP白名单可选）
限流: 100次/分钟/IP（只统计 /api/v1/*）
"""
import json, sqlite3, os, datetime, time, base64
import urllib.request, urllib.parse, gzip
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# QWeather 配置（复用 weather.py 的专属域名 + ~/.tms_weather_key）
def _qweather_meta():
    host = None
    try:
        with open(os.path.join(BASE, "weather.py")) as f:
            for ln in f:
                if ln.startswith("API_HOST = "):
                    host = ln.split('"')[1]
                    break
    except Exception:
        pass
    key = None
    try:
        with open(os.path.expanduser("~/.tms_weather_key")) as f:
            key = f.read().strip()
    except Exception:
        pass
    return host, key

def _qhttp(params, path="/geo/v2/city/lookup"):
    """调和风 GeoAPI（逆地理/城市搜索）。返回 json dict 或 None"""
    host, key = _qweather_meta()
    if not host or not key:
        return None
    url = host + path + "?" + urllib.parse.urlencode(params) + "&key=" + key
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                               "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
            return json.loads(data.decode("utf-8"))
    except Exception:
        return None

def _reverse_geocode(lat, lon):
    """经纬度 → 和风逆地理 → 返回 (地点权威名, LocationID) 或 None"""
    d = _qhttp({"location": f"{lon},{lat}"})
    if not d or d.get("code") != "200":
        return None
    locs = d.get("location") or []
    if not locs:
        return None
    best = locs[0]
    # 把逆地理返回名规整成 weather 表里的展示名（昆明-XX / XX市）
    return best.get("name"), best.get("id")

# 兼容天气地点映射（与 weather.py LOCATIONS 保持一致：GeoAPI 权威 ID）
_QT_LOC = {
    "昆明": "101290101", "昆明-五华": "101290102", "昆明-东川": "101290103",
    "昆明-寻甸": "101290104", "昆明-晋宁": "101290105", "昆明-宜良": "101290106",
    "昆明-石林": "101290107", "昆明-呈贡": "101290108", "昆明-富民": "101290109",
    "昆明-嵩明": "101290110", "昆明-禄劝": "101290111", "昆明-安宁": "101290112",
    "昆明-盘龙": "101290114", "昆明-官渡": "101290115", "昆明-西山": "101290116",
    "大理州": "101290201", "红河州": "101290301", "曲靖市": "101290401",
    "文山州": "101290601", "玉溪市": "101290701", "楚雄市": "101290811",
}
_QT_ALIAS = {"晋宁": "昆明-晋宁", "宜良": "昆明-宜良", "嵩明": "昆明-嵩明",
             "禄劝": "昆明-禄劝", "寻甸": "昆明-寻甸", "石林": "昆明-石林",
             "安宁": "昆明-安宁", "呈贡": "昆明-呈贡", "富民": "昆明-富民",
             "五华": "昆明-五华", "盘龙": "昆明-盘龙", "官渡": "昆明-官渡",
             "西山": "昆明-西山", "东川": "昆明-东川", "大理": "大理州",
             "红河": "红河州", "曲靖": "曲靖市", "文山": "文山州",
             "玉溪": "玉溪市", "楚雄": "楚雄市"}
_QT_ID2NAME = {v: k for k, v in _QT_LOC.items()}

def _norm_location(loc):
    """入参归一化：ID→展示名 / 中文名(含别名)/经纬度。返回 (展示名 or None)"""
    loc = _fix_garbled(loc or "").strip()
    if not loc:
        return None
    # 1) 纯数字 ID
    if loc.isdigit():
        return _QT_ID2NAME.get(loc)
    # 2) 已知展示名或其别名
    if loc in _QT_LOC:
        return loc
    return _QT_ALIAS.get(loc)

# ─────────────────────────────────────────────
# API v1：鉴权 + 限流 + 统一返回
# ─────────────────────────────────────────────
def _load_api_config():
    """~/.tms_api_keys: 第一行=API Key, 后续行=IP白名单(可选)"""
    path = os.path.expanduser("~/.tms_api_keys")
    try:
        with open(path) as f:
            lines = [l.strip() for l in f if l.strip()]
        key = lines[0] if lines else None
        allow = set(lines[1:]) if len(lines) > 1 else None  # None=不限制IP
        return key, allow
    except FileNotFoundError:
        return None, None

def _client_ip(self):
    # 优先 X-Forwarded-For（Nginx 反代时取最左真实 IP）
    xff = self.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return self.client_address[0]

# 限流器: {ip: (分钟时间戳, 计数)}
_RATE = {}
def _rate_limit(self):
    """100次/分钟/IP。超限返回 False（调用方发 429）"""
    ip = _client_ip(self)
    now = int(time.time())
    minute = now // 60
    cur = _RATE.get(ip)
    if cur is None or cur[0] != minute:
        _RATE[ip] = (minute, 1)
        return True
    if cur[1] >= 100:
        return False
    _RATE[ip] = (minute, cur[1] + 1)
    return True

def _check_api_key(self):
    """X-API-Key 校验。返回 (ok, err_msg)"""
    key, allow = _load_api_config()
    if not key:
        return False, "服务端未配置 API Key"
    got = self.headers.get("X-API-Key", "")
    if got != key:
        return False, "无效的 API Key"
    if allow:  # 有IP白名单才限制
        ip = _client_ip(self)
        if ip not in allow:
            return False, f"IP 不在白名单: {ip}"
    return True, ""

def _ok(data=None, msg="ok"):
    return {"code": 0, "msg": msg, "data": data if data is not None else {}}
def _err(msg, code=1):
    return {"code": code, "msg": msg, "data": {}}


BASE = os.path.expanduser("~/tianmu_starlink")
DB = os.path.join(BASE, "data", "prices.db")
PORT = int(os.environ.get("TMS_PORT", "8080"))
# 访问密码（文件第一行用户名, 第二行密码; 权限600）
AUTH_FILE = os.path.expanduser("~/.tms_web_auth")

def check_auth(self):
    """HTTP Basic 认证：读 Authorization 头，比对密码文件"""
    auth = self.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
    except Exception:
        return False
    user, _, pw = decoded.partition(":")
    try:
        with open(AUTH_FILE) as f:
            lines = [l.strip() for l in f if l.strip()]
        if len(lines) >= 2:
            return user == lines[0] and pw == lines[1]
    except FileNotFoundError:
        pass
    return False

def require_auth(self):
    """未认证时返回 401 + 浏览器弹出密码框"""
    self.send_response(401)
    self.send_header("WWW-Authenticate", 'Basic realm="Tianmu Starlink"')
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Access-Control-Allow-Origin", "*")
    body = json.dumps({"error": "需要密码"}).encode("utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def latest_veg(c):
    """今日蔬菜行情 + 与昨日涨跌幅（含价格口径：批发价）"""
    rows = c.execute("SELECT market, variety, price, ts, price_type FROM veg_prices "
                     "WHERE ts=(SELECT MAX(ts) FROM veg_prices)").fetchall()
    prev = {}
    dates = [r[0] for r in c.execute("SELECT DISTINCT ts FROM veg_prices ORDER BY ts DESC LIMIT 2")]
    if len(dates) >= 2:
        for r in c.execute("SELECT market, variety, price FROM veg_prices WHERE ts=?", (dates[1],)):
            prev[(r["market"], r["variety"])] = r["price"]
    out = []
    for r in rows:
        old = prev.get((r["market"], r["variety"]))
        pct = round((r["price"] - old) / old * 100, 1) if old else None
        out.append({"variety": r["variety"], "market": r["market"],
                    "price": r["price"], "change_pct": pct,
                    "price_type": r["price_type"] or "批发"})
    return out

def latest_flower(c):
    rows = c.execute("SELECT breed, avg_price, highest, ts FROM flower_prices "
                     "WHERE ts=(SELECT MAX(ts) FROM flower_prices)").fetchall()
    dates = [r[0] for r in c.execute("SELECT DISTINCT ts FROM flower_prices ORDER BY ts DESC LIMIT 2")]
    prev = {}
    if len(dates) >= 2:
        for r in c.execute("SELECT breed, avg_price FROM flower_prices WHERE ts=?", (dates[1],)):
            prev[r["breed"]] = r["avg_price"]
    out = []
    for r in rows:
        old = prev.get(r["breed"])
        pct = round((r["avg_price"] - old) / old * 100, 1) if old else None
        out.append({"breed": r["breed"], "avg_price": r["avg_price"],
                    "highest": r["highest"], "change_pct": pct})
    return out

def latest_context(c):
    """读取今天的 type=context 预警（如雨季背景），无则返回 None"""
    r = c.execute("SELECT title, detail, category FROM alerts "
                  "WHERE type='context' AND date(ts)=date('now','localtime') "
                  "ORDER BY id DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def latest_weather(c, loc="昆明"):
    r = c.execute("SELECT * FROM weather WHERE location=? ORDER BY ts DESC LIMIT 1",
                  (loc,)).fetchone()
    return dict(r) if r else None

def all_weather(c):
    rows = c.execute(
        "SELECT w.* FROM weather w JOIN (SELECT location, MAX(ts) m FROM weather GROUP BY location) t "
        "ON w.location=t.location AND w.ts=t.m ORDER BY w.location").fetchall()
    return [dict(r) for r in rows]

# ─────────────────────────────────────────────
# API v1 数据装配
# ─────────────────────────────────────────────
VEG_MARKET_MAP = {"昆明": "王旗营", "昆明-晋宁": "晋宁"}

def v1_quotes(c):
    """今日行情聚合：花卉指数 + 蔬菜 + 天气"""
    # 花卉指数 (KIFA)
    k = c.execute("SELECT ts, price_index_a, price_index_q FROM kifa_index ORDER BY ts DESC LIMIT 2").fetchall()
    flower = None
    if k:
        latest, prev = k[0], (k[1] if len(k) > 1 else None)
        prev_a = prev["price_index_a"] if prev else None
        chg = round((latest["price_index_a"] - prev_a) / prev_a * 100, 1) if prev_a else None
        # 花卉拍卖价（斗南·本地口径，元/枝）
        breeds = []
        for r in c.execute("SELECT name, avg_price FROM nync_flower_prices "
                           "WHERE ts=(SELECT MAX(ts) FROM nync_flower_prices) ORDER BY avg_price DESC LIMIT 8"):
            breeds.append({"name": r["name"], "avg_price": round(r["avg_price"], 2), "unit": "元/枝",
                           "source": "本地·斗南拍卖"})
        flower = {"date": latest["ts"], "kifa_index_a": latest["price_index_a"],
                  "kifa_index_q": latest["price_index_q"], "change_pct": chg,
                  "unit": "指数", "source": "KIFA官方", "breeds": breeds}
    # 蔬菜（王旗营·本地口径，元/公斤）
    veg = []
    for r in c.execute("SELECT name, price, qty FROM nync_veg_prices "
                       "WHERE ts=(SELECT MAX(ts) FROM nync_veg_prices) ORDER BY price DESC LIMIT 8"):
        veg.append({"name": r["name"], "price": r["price"], "market": "王旗营",
                    "unit": "元/公斤", "qty": r["qty"], "source": "本地·省厅"})
    # 天气（昆明-晋宁，花卉主产区）
    w = c.execute("SELECT * FROM weather WHERE location='昆明-晋宁' "
                  "ORDER BY ts DESC LIMIT 1").fetchone()
    weather = None
    if w:
        weather = {"location": w["location"], "temp_max": w["temp_max"], "temp_min": w["temp_min"],
                   "text": w["condition_text"], "precip_mm": w["precip_mm"],
                   "wind": f"{w['wind_scale']}级", "alert": ""}
    return {"date": datetime.date.today().isoformat(),
            "flower": flower, "veg": veg, "weather": weather}

def v1_history(c, htype, days):
    """历史走势。type: kifa/veg/flower/mofcom/weather"""
    try:
        days = max(1, min(int(days), 3650))
    except Exception:
        days = 90
    cfg = {
        "kifa":    ("kifa_index", "ts", "price_index_q", "KIFA官方", "指数"),
        "mofcom":  ("mofcom_week_prices", "ts", "price", "商务部·全国口径", "元/公斤"),
        "flower":  ("nync_flower_prices", "ts", "avg_price", "本地·斗南拍卖", "元/枝"),
        "veg":     ("nync_veg_prices", "ts", "price", "本地·省厅", "元/公斤"),
        "weather": ("hist_weather", "ts", "temp_high", "天气后报·民间整理", "°C"),
    }
    if htype not in cfg:
        return None, "未知 type，可选 kifa/veg/flower/mofcom/weather"
    tbl, tcol, vcol, source, unit = cfg[htype]
    rows = c.execute(f"SELECT {tcol} AS ts, {vcol} AS v FROM {tbl} "
                     f"ORDER BY {tcol} DESC LIMIT ?", (days,)).fetchall()
    # 非单值类型的表（veg/flower/mofcom 每天多行），按日期聚合为均值，图形更平顺
    agg = {}
    for r in rows:
        if r["v"] is None:
            continue
        agg.setdefault(r["ts"], []).append(float(r["v"]))
    ordered = sorted(agg.keys())
    points = []
    for d in ordered[-min(days, len(ordered)):]:
        vals = agg[d]
        avg = round(sum(vals) / len(vals), 2) if vals else None
        points.append({"date": d, "value": avg})
    return {"type": htype, "points": points, "source": source, "unit": unit}, None

def v1_festivals(c):
    """未来30天节日 + 历史规律（复用 research/festival_calendar.py 的节日表）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "festival_calendar", os.path.join(BASE, "research", "festival_calendar.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    today = datetime.date.today()
    items = []
    for key, (name, rule) in mod.FESTIVALS.items():
        if len(key) == 3:
            y, mm, dd = key
            if y != today.year:
                continue
        else:
            mm, dd = key
        try:
            fday = datetime.date(today.year, mm, dd)
        except ValueError:
            continue
        delta = (fday - today).days
        if 0 <= delta <= 30:
            items.append({"festival": name, "date": fday.isoformat(), "days_left": delta,
                          "rule": rule or "", "advice": ""})
    items.sort(key=lambda x: x["days_left"])
    # 规律寄语（用节日自带 rule 摘要）
    if items:
        for it in items:
            if "+77.2%" in (it["rule"] or "") or "7涨" in (it["rule"] or "") \
               or "100%" in (it["rule"] or "") and "反向" not in (it["rule"] or ""):
                it["advice"] = "把握出货窗口"
            elif "反向" in (it["rule"] or ""):
                it["advice"] = "节后别压货"
    return {"items": items, "note": "规律来自2020-2026年KIFA指数统计，仅供参考，非买卖指令"}

def v1_alerts(c, category, date):
    """当日波动预警（±阈值），默认当天"""
    if not date:
        date = datetime.date.today().isoformat()
    q = "SELECT * FROM alerts WHERE date(ts)=? "
    args = [date]
    if category:
        q += "AND category=? "
        args.append(category)
    q += "ORDER BY id DESC LIMIT 50"
    rows = c.execute(q, args).fetchall()
    items = []
    for r in rows:
        items.append({"title": r["title"], "category": r["category"], "detail": r["detail"],
                      "change_pct": r["change_pct"], "type": r["type"],
                      "market": r["market"], "date": (r["ts"] or "")[:10], "is_read": r["is_read"]})
    return {"date": date, "items": items}

def _fix_garbled(s):
    """修复客户端把中文未百分号编码直接塞 URL 导致的 mojibake。
    BaseHTTPRequestHandler 按 latin-1 解码请求行，原始 UTF-8 中文字节会被拆成
    'æ\x98\x86...' 乱码；重新 latin-1 编码回去再 utf-8 解码即可还原原文。
    还原失败（本就不是 UTF-8）则原样返回。"""
    if not s or s.isascii():
        return s
    try:
        fixed = s.encode('latin-1').decode('utf-8')
        if fixed and not fixed.isascii():
            return fixed
    except Exception:
        pass
    return s

def v1_weather(c, location):
    """实时天气+预警。
    location 三态：和风 LocationID / 中文名（含别名）/ '经度,纬度'（自动逆地理）"""
    if not location:
        location = "昆明-晋宁"
    loc = _fix_garbled(str(location).strip())
    # ① 经纬度入参：xx.xx,yy.yy → 逆地理 → 地点名
    if "," in loc or "，" in loc:
        loc = loc.replace("，", ",")
        parts = loc.split(",")
        if len(parts) == 2:
            try:
                lon, lat = float(parts[0]), float(parts[1])
            except ValueError:
                lon = lat = None
            if lon is not None and lat is not None:
                gname, gid = _reverse_geocode(lat, lon) or (None, None)
                if gname:
                    norm = _norm_location(gname) or gname
                    row = c.execute("SELECT * FROM weather WHERE location=? "
                                    "ORDER BY ts DESC LIMIT 1", (norm,)).fetchone()
                    if row:
                        return _fmt_weather(row, {"from_geo": True, "lat": lat, "lon": lon}), None
    # ② ID / 中文名：归一化后查本地表
    norm = _norm_location(loc)
    name = norm or loc
    row = c.execute("SELECT * FROM weather WHERE location=? ORDER BY ts DESC LIMIT 1",
                    (name,)).fetchone()
    if not row:
        row = c.execute("SELECT * FROM weather WHERE location LIKE ? ORDER BY ts DESC LIMIT 1",
                        (f"%{name}%",)).fetchone()
    if not row:
        return None, "暂无该地点天气数据"
    return _fmt_weather(row, {}), None

def _fmt_weather(row, extra=None):
    d = {"date": row["ts"], "location": row["location"], "temp_max": row["temp_max"],
         "temp_min": row["temp_min"], "text": row["condition_text"],
         "precip_mm": row["precip_mm"], "wind": f"{row['wind_scale']}级",
         "text_day": row["text_day"], "text_night": row["text_night"], "alert": "",
         "source": "和风天气"}
    if extra:
        d.update(extra)
    return d

def v1_geo(c, lat, lon):
    """GET /api/v1/geo?lat=&lon= : 经纬度 → 逆地理 → 定位信息 + 该地天气"""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None, "lat/lon 必须为数值"
    gname, gid = _reverse_geocode(lat, lon) or (None, None)
    if not gname or not gid:
        return None, "逆地理定位失败"
    norm = _norm_location(gname) or gname
    row = c.execute("SELECT * FROM weather WHERE location=? ORDER BY ts DESC LIMIT 1",
                    (norm,)).fetchone()
    weather = _fmt_weather(row, {}) if row else None
    return {"lat": lat, "lon": lon, "location": norm,
            "location_id": gid, "weather": weather}, None

def v1_health(c):
    """health.json 透传（运维/监控用）"""
    hp = os.path.join(BASE, "data", "health.json")
    if os.path.isfile(hp):
        with open(hp) as f:
            return json.load(f)
    return {"status": "ok", "note": "health.json 不存在", "data_ok": False}

def v1_subscribe(c, body):
    """订阅协议（v1.1 预留占位，返回 echo）"""
    openid = (body or {}).get("openid") or ""
    items = (body or {}).get("items") or []
    channel = (body or {}).get("channel") or "wechat_subscribe"
    # v1 不落库不推送，仅校验协议格式
    if not openid:
        return None, "openid 必填（v1.1 微信登录后获得）"
    if not isinstance(items, list) or not items:
        return None, "items 必填（订阅的品种/节日列表）"
    return {"subscriptions": [{"item": it, "status": "pending"} for it in items],
            "channel": channel, "note": "v1.1 实现微信订阅消息推送"}, None


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, rel):
        import mimetypes
        path = os.path.join(BASE, rel)
        if not os.path.isfile(path):
            self._send(404, {"error": "not found"})
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        # API v1：X-API-Key 鉴权 + 限流 + 统一 {code,msg,data}
        if u.path.startswith("/api/v1/"):
            return self._v1_handle("GET")
        if not check_auth(self):
            return require_auth(self)
        c = db()
        p, q = u.path, parse_qs(u.query)
        try:
            if p == "/api/health":
                self._send(200, {"ok": True, "time": datetime.datetime.now().isoformat()})
            elif p == "/api/quotes/veg":
                self._send(200, {"date": c.execute("SELECT MAX(ts) FROM veg_prices").fetchone()[0],
                                 "context": latest_context(c),
                                 "items": latest_veg(c)})
            elif p == "/api/quotes/flower":
                self._send(200, {"date": c.execute("SELECT MAX(ts) FROM flower_prices").fetchone()[0],
                                 "context": latest_context(c),
                                 "items": latest_flower(c)})
            elif p == "/api/alerts":
                rows = c.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 50").fetchall()
                self._send(200, {"items": [dict(r) for r in rows]})
            elif p == "/api/watchlist":
                rows = c.execute("SELECT * FROM watchlist ORDER BY id").fetchall()
                self._send(200, {"items": [dict(r) for r in rows]})
            elif p == "/api/weather":
                self._send(200, latest_weather(c, (q.get("loc") or ["昆明"])[0]) or {"error": "暂无数据"})
            elif p == "/api/weather-all":
                self._send(200, {"items": all_weather(c)})
            elif p == "/" or p == "/index.html":
                self._send_file("web/index.html")
            elif p.startswith("/web/"):
                self._send_file(p.lstrip("/"))
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)})
        finally:
            c.close()

    def do_POST(self):
        u = urlparse(self.path)
        if u.path.startswith("/api/v1/"):
            return self._v1_handle("POST")
        if not check_auth(self):
            return require_auth(self)
        c = db()
        try:
            if u.path == "/api/watchlist":
                b = self._body()
                c.execute("INSERT OR IGNORE INTO watchlist(user_id,item_type,item_key,market) VALUES(?,?,?,?)",
                          ("default", b.get("item_type"), b.get("item_key"), b.get("market")))
                c.commit()
                self._send(200, {"ok": True})
            elif u.path.startswith("/api/alerts/") and u.path.endswith("/read"):
                aid = int(u.path.split("/")[3])
                c.execute("UPDATE alerts SET is_read=1 WHERE id=?", (aid,))
                c.commit()
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)})
        finally:
            c.close()

    def do_DELETE(self):
        if not check_auth(self):
            return require_auth(self)
        c = db()
        u = urlparse(self.path)
        try:
            if u.path.startswith("/api/watchlist/"):
                wid = int(u.path.split("/")[3])
                c.execute("DELETE FROM watchlist WHERE id=?", (wid,))
                c.commit()
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)})
        finally:
            c.close()

    def log_message(self, *a):  # 静默访问日志
        pass

    def _v1_handle(self, method):
        """API v1 统一入口：鉴权→限流→路由→{code,msg,data}"""
        ok, err = _check_api_key(self)
        if not ok:
            return self._send(401, _err(err, 401))
        if not _rate_limit(self):
            return self._send(429, _err("请求过于频繁：100次/分钟/IP", 429))
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        def g(k, d=""):
            return (q.get(k) or [d])[0]
        try:
            c = db()
            try:
                if method == "GET":
                    if p == "/api/v1/quotes":
                        return self._send(200, _ok(v1_quotes(c)))
                    if p == "/api/v1/history":
                        data, e = v1_history(c, g("type"), g("days", "90"))
                        return self._send(200, _ok(data) if data else _err(e))
                    if p == "/api/v1/festivals":
                        return self._send(200, _ok(v1_festivals(c)))
                    if p == "/api/v1/alerts":
                        return self._send(200, _ok(v1_alerts(c, g("category", ""), g("date", ""))))
                    if p == "/api/v1/weather":
                        data, e = v1_weather(c, g("location", ""))
                        return self._send(200, _ok(data) if data else _err(e))
                    if p == "/api/v1/geo":
                        data, e = v1_geo(c, g("lat"), g("lon"))
                        return self._send(200, _ok(data) if data else _err(e))
                    if p == "/api/v1/health":
                        return self._send(200, _ok(v1_health(c)))
                else:  # POST
                    if p == "/api/v1/subscribe":
                        data, e = v1_subscribe(c, self._body())
                        return self._send(200, _ok(data) if data else _err(e))
                return self._send(404, _err("not found", 404))
            finally:
                c.close()
        except Exception as e:
            return self._send(500, _err(str(e), 500))

if __name__ == "__main__":
    print(f"🌾 田亩星链 API 服务启动: http://0.0.0.0:{PORT}")
    HTTPServer(("0.0.0.0", PORT), H).serve_forever()
