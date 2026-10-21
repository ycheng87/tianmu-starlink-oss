// 田亩星链 v2.0 首页（C 稿实现 · 小墨 2026-10-22）
// 铁律：数字一律取接口原值；涨跌只用接口 change_pct；鲜花/蔬菜日期分开标；不同单位不进同一个排行。
const app = getApp();
const api = require('../../utils/api.js');
const fmt = require('../../utils/format.js');
const privacy = require('../../utils/privacy.js');

// 菜品分组沿用 v1.8（后端返回 category 后以接口值替换）
const VEG_CATEGORY_NAMES = {
  '叶菜': '京白菜、儿菜、大白菜、大芫荽、大苦菜、大莲白、大葱、娃娃菜、小白菜、小米菜、小苦菜、小莲白、小葱、松花菜、瓜尖、生菜、白花、空心菜、篱蒿菜、紫莲白、芥兰菜、芦笋、芹菜、茴香菜、茼蒿菜、菜心、菠菜、蒜苔、蒜苗、薄荷、西芹、青笋尖、青花、韭菜、韭菜苔、韭黄、香菜',
  '根茎': '土豆、山药、折耳根、毛芋头、洋葱、独蒜、生姜、白大蒜、白萝卜、红萝卜、红薯、胡萝卜、茨菇、莲藕、青笋',
  '瓜果': '丝瓜、冬瓜、南瓜、姜柄瓜、小米辣、小香瓜、小黄瓜、尖椒、洋丝瓜、玉米、番茄、皱皮椒、红椒、苦瓜、茄子、葫芦瓜、青椒、黄瓜',
  '豆类': '四季豆、大豆芽、毛豆、绿豆芽、豇豆、豌豆、豌豆尖',
  '菌菇': '人工菌、木耳、香菇'
};
const VEG_CATEGORIES = Object.keys(VEG_CATEGORY_NAMES).map((name) => ({ name: name, names: new Set(VEG_CATEGORY_NAMES[name].split('、')) }));
const RANK_LIMIT = 8;
const FLOWER_RANK_UNIT = '元/枝'; // 元/把 的品种不进涨跌榜（单位不同不比大小）
const SEARCH_LIMIT = 30;

function isNum(v) {
  return v !== null && v !== undefined && v !== '' && !isNaN(Number(v));
}
function md(dateStr) {
  const m = String(dateStr || '').match(/^\d{4}-(\d{2})-(\d{2})/);
  return m ? m[1] + '-' + m[2] : String(dateStr || '');
}
function isStale(dateStr) {
  const m = String(dateStr || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return false;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((today - d) / 86400000) >= 3;
}
function unitShort(unit) {
  return String(unit || '').replace(/^元/, '');
}

Page({
  data: {
    loading: true,
    error: '',
    isOffline: false,
    refreshing: false,
    // 天气
    weather: null,
    weatherCells: [],
    weatherAlerts: [],
    weatherLocationDenied: false,
    // 节日
    festival: null,
    // 行情
    activeCategory: 'flower',
    rankMode: 'up',
    vegChip: '全部',
    vegChips: ['全部', '叶菜', '根茎', '瓜果', '豆类', '菌菇'],
    flowerDate: '',
    vegDate: '',
    flowerCount: 0,
    vegCount: 0,
    hero: null,
    heroKicker: '',
    dist: { up: 0, down: 0, flat: 0, total: 0 },
    rankRows: [],
    rankUnitNote: '',
    rankEmptyText: '',
    // 搜索
    keyword: '',
    searchRows: [],
    searchHistory: [],
    showHistory: false,
    // 登录
    openid: ''
  },

  onLoad() {
    this._flower = [];
    this._veg = [];
    this._initLogin();
    this.loadAll();
    this.loadWeather('昆明-晋宁');
    this.locateWeather();
  },

  onShow() {
    if (this._flower && (this._flower.length || this._veg.length)) this._rebuild();
  },

  onPullDownRefresh() {
    this.setData({ refreshing: true });
    this.loadAll(() => {
      this.setData({ refreshing: false });
      wx.stopPullDownRefresh();
    });
  },

  // ─── 登录（10-05 登录态签名：拿 token，写关注时带上）───
  _initLogin() {
    const openid = wx.getStorageSync('openid');
    if (openid) {
      this.setData({ openid: openid });
      this._syncWatchlistFromCloud();
    }
    // 没 openid，或旧版本用户只有 openid 没 token → 静默重登一次拿 token
    if (!openid || !api.getToken()) {
      api.login()
        .then((data) => {
          if (data && data.openid) {
            api.saveLogin(data);
            this.setData({ openid: data.openid });
            this._syncWatchlistFromCloud();
          }
        })
        .catch((err) => {
          // 不再静默：留痕，下次启动自动重试
          try { wx.setStorageSync('login_fail_at', Date.now()); } catch (e) { /* ignore */ }
          console.warn('[login] 登录失败，下次启动重试：', err && err.message);
        });
    }
  },

  _syncWatchlistFromCloud() {
    const openid = this.data.openid;
    if (!openid) return;
    api.getWatchList(openid)
      .then((data) => {
        const items = (data && data.items) || [];
        const localList = this._getWatchList();
        const merged = [];
        const seen = {};
        items.forEach((it) => {
          const local = localList.find((item) => item.key === it.key) || {};
          merged.push({
            key: it.key,
            type: it.type || local.type || '',
            name: it.name || local.name || '',
            market: it.market || local.market || '',
            created_at: it.created_at || local.created_at || '',
            price: local.price,
            pct: local.pct,
            unit: local.unit || '',
            source: local.source || '',
            date: local.date || ''
          });
          seen[it.key] = true;
        });
        localList.forEach((it) => { if (!seen[it.key]) merged.push(it); });
        wx.setStorageSync('watchlist', merged);
        this._rebuild();
      })
      .catch(() => { /* 云端失败保留本地 */ });
  },

  // ─── 数据加载 ───
  loadAll(done) {
    this.setData({ loading: !this._flower.length && !this._veg.length, error: '', isOffline: false });

    api.getFestivals()
      .then((fd) => {
        const items = (fd && Array.isArray(fd.items)) ? fd.items : [];
        const first = items.filter((it) => it && it.festival && it.date)[0] || null;
        this.setData({ festival: first });
        if (fd && fd._fromCache) this.setData({ isOffline: true });
      })
      .catch(() => { /* 节日失败不阻塞 */ });

    api.getQuotes()
      .then((data) => {
        this.applyQuotes(data || {});
        if (data && data._fromCache) this.setData({ isOffline: true });
      })
      .catch((err) => {
        this.setData({ loading: false, error: (err && err.message) || '加载失败，请检查网络后重试' });
      })
      .then(() => { if (typeof done === 'function') done(); });
  },

  applyQuotes(data) {
    const f = data.flower || {};
    const flowerDate = f.date || '';
    const vegDate = data.date || '';
    this._flower = (f.breeds || []).map((b) => this._buildFlower(b, flowerDate));
    this._veg = (data.veg || []).map((v) => this._buildVeg(v, vegDate));
    this.setData({
      loading: false,
      error: '',
      flowerDate: md(flowerDate),
      vegDate: md(vegDate),
      flowerCount: this._flower.length,
      vegCount: this._veg.length
    });
    this._rebuild();
  },

  _buildFlower(b, date) {
    const low = isNum(b.low) ? Number(b.low) : null;
    const high = isNum(b.high) ? Number(b.high) : null;
    const avg = Number(b.avg_price);
    const hasRange = low !== null && high !== null && high >= low;
    let dotLeft = 50;
    if (hasRange && high > low) dotLeft = Math.max(0, Math.min(100, (avg - low) / (high - low) * 100));
    return {
      key: 'flower:' + b.name,
      type: 'flower',
      name: b.name,
      market: '',
      marketLabel: '斗南',
      source: b.source || '',
      unit: b.unit || '',
      unitShort: unitShort(b.unit),
      price: b.avg_price,
      priceText: fmt.fmtPrice(b.avg_price),
      low: low,
      high: high,
      lowText: fmt.fmtPrice(low),
      highText: fmt.fmtPrice(high),
      hasRange: hasRange,
      dotLeft: dotLeft.toFixed(1),
      pct: isNum(b.change_pct) ? Number(b.change_pct) : null,
      pctText: fmt.pctText(b.change_pct),
      pctClass: fmt.pctClass(b.change_pct, fmt.getColorMode()),
      noQuote: !isNum(b.avg_price),
      date: date,
      stale: isStale(date),
      watched: false
    };
  },

  _buildVeg(v, date) {
    const cat = VEG_CATEGORIES.find((c) => c.names.has(v.name));
    return {
      key: 'veg:' + v.name + ':' + (v.market || ''),
      type: 'veg',
      name: v.name,
      market: v.market || '',
      marketLabel: v.market || '王旗营',
      source: v.source || '',
      unit: v.unit || '',
      unitShort: unitShort(v.unit),
      price: v.price,
      priceText: fmt.fmtPrice(v.price),
      hasRange: false,
      category: cat ? cat.name : '',
      pct: isNum(v.change_pct) ? Number(v.change_pct) : null,
      pctText: fmt.pctText(v.change_pct),
      pctClass: fmt.pctClass(v.change_pct, fmt.getColorMode()),
      noQuote: !isNum(v.price) || Number(v.price) === 0,
      date: date,
      stale: isStale(date),
      watched: false
    };
  },

  // ─── 视图重算（头条卡 / 分布条 / 榜单 / 搜索结果）───
  _rebuild() {
    const keys = {};
    this._getWatchList().forEach((it) => { keys[it.key] = true; });
    const mark = (it) => Object.assign({}, it, { watched: !!keys[it.key] });

    const cat = this.data.activeCategory;
    const mode = this.data.rankMode;
    const list = cat === 'flower' ? this._flower : this._veg;
    const priced = list.filter((it) => !it.noQuote && it.pct !== null);
    const rankable = cat === 'flower' ? priced.filter((it) => it.unit === FLOWER_RANK_UNIT) : priced;
    const byUp = rankable.slice().sort((a, b) => b.pct - a.pct);

    let hero = null;
    let heroKicker = '';
    const dateLabel = cat === 'flower' ? this.data.flowerDate : this.data.vegDate;
    const marketLabel = cat === 'flower' ? '斗南' : '王旗营';
    if (byUp.length) {
      hero = mark(byUp[0]);
      heroKicker = dateLabel + ' ' + marketLabel + (byUp[0].pct > 0 ? ' · 涨幅第一' : ' · 今日无上涨品种');
    }

    const dist = {
      up: priced.filter((it) => it.pct > 0).length,
      down: priced.filter((it) => it.pct < 0).length,
      flat: priced.filter((it) => it.pct === 0).length,
      total: priced.length
    };

    let rows = [];
    let rankEmptyText = '';
    if (mode === 'up') {
      rows = byUp.filter((it) => it.pct > 0).slice(0, RANK_LIMIT);
      rankEmptyText = '今日没有上涨的品种';
    } else if (mode === 'down') {
      rows = rankable.slice().sort((a, b) => a.pct - b.pct).filter((it) => it.pct < 0).slice(0, RANK_LIMIT);
      rankEmptyText = '今日没有下跌的品种';
    } else {
      rows = list.slice();
      if (cat === 'veg' && this.data.vegChip !== '全部') {
        rows = rows.filter((it) => it.category === this.data.vegChip);
      }
      rankEmptyText = '暂无报价';
    }

    // 单位注脚从实际上榜行动态生成（不把"蔬菜都是元/公斤"的假设写死进 UI）
    let rankUnitNote = '';
    if (mode === 'all') {
      rankUnitNote = '单位见各行';
    } else {
      const units = Array.from(new Set(rows.map((r) => r.unit).filter(Boolean)));
      rankUnitNote = units.length === 1 ? units[0] : '单位见各行';
      if (cat === 'flower' && units.length === 1) rankUnitNote += ' · 条=当日最低–最高';
    }

    this.setData({
      hero: hero,
      heroKicker: heroKicker,
      dist: dist,
      rankRows: rows.map(mark),
      rankUnitNote: rankUnitNote,
      rankEmptyText: rankEmptyText,
      searchRows: this._search(this.data.keyword).map((it) => Object.assign(mark(it), { showTag: true }))
    });
  },

  _search(kw) {
    const k = String(kw || '').trim();
    if (!k) return [];
    return this._flower.concat(this._veg).filter((it) => it.name.indexOf(k) >= 0).slice(0, SEARCH_LIMIT);
  },

  // ─── 交互 ───
  onSelectCategory(e) {
    const c = e.currentTarget.dataset.category;
    if ((c !== 'flower' && c !== 'veg') || c === this.data.activeCategory) return;
    this.setData({ activeCategory: c, vegChip: '全部' }, () => this._rebuild());
  },

  onSelectRank(e) {
    const m = e.currentTarget.dataset.mode;
    if (['up', 'down', 'all'].indexOf(m) < 0 || m === this.data.rankMode) return;
    this.setData({ rankMode: m }, () => this._rebuild());
  },

  onSelectChip(e) {
    const c = e.currentTarget.dataset.chip || '全部';
    this.setData({ vegChip: c }, () => this._rebuild());
  },

  onSearchInput(e) {
    this.setData({ keyword: e.detail.value || '' }, () => this._rebuild());
  },

  onSearchConfirm(e) {
    const kw = String((e.detail && e.detail.value) || this.data.keyword || '').trim();
    if (kw) this._saveSearchHistory(kw);
  },

  onSearchFocus() {
    let h = [];
    try { h = wx.getStorageSync('search_history'); } catch (e) { h = []; }
    this.setData({ searchHistory: Array.isArray(h) ? h.slice(0, 8) : [], showHistory: true });
  },

  onSearchBlur() {
    const kw = String(this.data.keyword || '').trim();
    if (kw) this._saveSearchHistory(kw);
    setTimeout(() => this.setData({ showHistory: false }), 200);
  },

  onSearchClear() {
    this.setData({ keyword: '' }, () => this._rebuild());
  },

  onTapHistory(e) {
    this.setData({ keyword: e.currentTarget.dataset.value || '', showHistory: false }, () => this._rebuild());
  },

  _saveSearchHistory(kw) {
    try {
      let h = wx.getStorageSync('search_history');
      if (!Array.isArray(h)) h = [];
      h = [kw].concat(h.filter((x) => x !== kw)).slice(0, 10);
      wx.setStorageSync('search_history', h);
    } catch (e) { /* ignore */ }
  },

  onGoDetail(e) {
    const d = e.currentTarget.dataset;
    if (!d.name) return;
    const marketQuery = d.market ? '&market=' + encodeURIComponent(d.market) : '';
    wx.navigateTo({ url: '/pages/detail/detail?name=' + encodeURIComponent(d.name) + '&type=' + d.type + marketQuery });
  },

  onOpenFestival() {
    const f = this.data.festival;
    if (!f) return;
    wx.showModal({ title: f.festival || '', content: f.rule || f.advice || f.date || '', showCancel: false });
  },

  // ─── 关注 ───
  _getWatchList() {
    const list = wx.getStorageSync('watchlist');
    return Array.isArray(list) ? list : [];
  },

  _findItem(key) {
    return this._flower.concat(this._veg).find((it) => it.key === key) || null;
  },

  onToggleWatch(e) {
    const key = e.currentTarget.dataset.key;
    if (!key) return;
    const list = this._getWatchList();
    const idx = list.findIndex((it) => it.key === key);
    const isAdding = idx < 0;
    if (isAdding) {
      const it = this._findItem(key);
      if (!it) return;
      list.push({
        key: it.key, type: it.type, name: it.name, market: it.market || '', created_at: '',
        price: it.price, pct: it.pct, unit: it.unit, source: it.source, date: it.date || ''
      });
    } else {
      list.splice(idx, 1);
    }
    wx.setStorageSync('watchlist', list);
    this._rebuild();
    const openid = this.data.openid;
    if (openid) {
      (isAdding ? api.addWatch(openid, key) : api.removeWatch(openid, key)).catch(() => { /* 失败不影响本地 */ });
    }
  },

  // ─── 天气 ───
  loadWeather(location) {
    return api.getWeather(location || '昆明-晋宁')
      .then((w) => {
        const weather = w || {};
        const cells = [];
        if (weather.date) {
          const d = weather.text_day || weather.text || '';
          const n = weather.text_night || '';
          cells.push({
            key: weather.date,
            label: md(weather.date) + ' 实况',
            text: (n && n !== d) ? d + '转' + n : d,
            temp: this._tempText(weather.temp_min, weather.temp_max)
          });
        }
        (Array.isArray(weather.forecast) ? weather.forecast : [])
          .filter((f) => f && f.date && f.date !== weather.date)
          .forEach((f) => {
            if (cells.length >= 3) return;
            cells.push({ key: f.date, label: md(f.date), text: f.text_day || '', temp: this._tempText(f.temp_min, f.temp_max) });
          });
        this.setData({
          weather: weather,
          weatherCells: cells,
          weatherAlerts: Array.isArray(weather.weather_alerts) ? weather.weather_alerts : [],
          weatherLocationDenied: false
        });
        return weather;
      })
      .catch(() => null);
  },

  _tempText(min, max) {
    if (!isNum(min) || !isNum(max)) return '';
    return Math.round(Number(min)) + '–' + Math.round(Number(max)) + '°';
  },

  locateWeather() {
    privacy.ensure().then((ok) => {
      if (!ok) return;
      return privacy.locationAuthorized().then((allowed) => {
        if (!allowed) {
          this.setData({ weatherLocationDenied: true });
          return;
        }
        wx.getLocation({
          type: 'gcj02',
          isHighAccuracy: false,
          timeout: 8000,
          success: (res) => { this.loadWeather(String(res.longitude) + ',' + String(res.latitude)); },
          fail: () => { this.setData({ weatherLocationDenied: true }); }
        });
      });
    }).catch(() => { /* 隐私协议异常 */ });
  },

  onRefreshWeather() {
    wx.getSetting({
      success: (s) => {
        const authed = s.authSetting && s.authSetting['scope.userLocation'] !== false;
        if (!authed) {
          wx.openSetting({ success: () => this.locateWeather(), fail: () => {} });
        } else {
          this.locateWeather();
        }
      },
      fail: () => this.locateWeather()
    });
  },

  onRetry() {
    this.loadAll();
  }
});
