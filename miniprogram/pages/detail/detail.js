// 田亩星链 v2.0 品种详情（C 稿实现 · 小墨 2026-10-22）
// 跨期比：取「不晚于目标日的最近一个有报价日」的接口原值，格子里写实际日期（休市日无数据，不插值、不冒充整周整月）
const api = require('../../utils/api.js');
const fmt = require('../../utils/format.js');

const CANVAS_DRAW_DELAY = 150;
const CMP_OFFSETS = [
  { label: '1 周前', days: 7 },
  { label: '1 个月前', days: 30 },
  { label: '3 个月前', days: 90 }
];
const COLORS = { line: '#14532D', fill: 'rgba(20,83,45,0.12)', grid: '#EEF2EE', text: '#8A978F', up: '#D9363E', down: '#1E9B5A' };

function isNum(v) { return v !== null && v !== undefined && v !== '' && !isNaN(Number(v)); }
function md(s) { const m = String(s || '').match(/^\d{4}-(\d{2})-(\d{2})/); return m ? m[1] + '-' + m[2] : String(s || ''); }
function toDate(s) { const p = String(s).split('-'); return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2])); }
function iso(d) { const z = (n) => (n < 10 ? '0' + n : '' + n); return d.getFullYear() + '-' + z(d.getMonth() + 1) + '-' + z(d.getDate()); }
function daysAgo(dateStr) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(dateStr || ''))) return 0;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((today - toDate(dateStr)) / 86400000);
}

Page({
  data: {
    name: '', type: 'flower', market: '', marketLabel: '',
    loading: true, error: '',
    quote: null, unit: '', source: '',
    range: null,
    cmp: [],
    rangeOptions: [{ days: 7, label: '7天' }, { days: 30, label: '30天' }, { days: 90, label: '90天' }, { days: 365, label: '1年' }],
    historyDays: 90,
    chartPoints: 0,
    chartNote: '',
    chartWidth: 311, chartHeight: 170,
    watched: false,
    festival: null
  },

  onLoad(options) {
    const name = decodeURIComponent(options.name || '');
    const type = options.type === 'veg' ? 'veg' : 'flower';
    const market = options.market ? decodeURIComponent(options.market) : '';
    this.setData({ name, type, market, marketLabel: type === 'flower' ? '斗南' : (market || '王旗营') });
    wx.setNavigationBarTitle({ title: name || '品种详情' });
    try {
      const info = wx.getSystemInfoSync();
      this.setData({ chartWidth: Math.max(240, info.windowWidth - 64) });
    } catch (e) { /* 默认尺寸 */ }
    this._refreshWatched();
    this.loadAll();
  },

  onPullDownRefresh() { this.loadAll(() => wx.stopPullDownRefresh()); },

  loadAll(done) {
    const { name, type } = this.data;
    if (!name) { this.setData({ loading: false, error: '缺少品种名' }); return; }
    this.setData({ loading: true, error: '' });
    // 一次拉 1 年（接口按 name 出单品），跨期比与各区间曲线都从这一份原值里取
    const pHist = api.getHistory(type, 365, name).then((h) => { this._applyHistory(h || {}); }).catch((err) => { throw err; });
    const pQuote = api.getQuotes().then((q) => this._applyQuote(q || {})).catch(() => { /* 报价失败只隐藏头部 */ });
    api.getFestivals().then((fd) => {
      const items = (fd && Array.isArray(fd.items)) ? fd.items.filter((x) => x && x.festival && x.date) : [];
      this.setData({ festival: type === 'flower' ? (items[0] || null) : null });
    }).catch(() => {});
    Promise.all([pHist, pQuote])
      .then(() => {
        this.setData({ loading: false });
        this._buildCmp();
        this._drawRange();
      })
      .catch((err) => this.setData({ loading: false, error: (err && err.message) || '加载失败' }))
      .then(() => { if (typeof done === 'function') done(); });
  },

  _applyQuote(data) {
    const t = this.data.type;
    let q = null;
    let date = '';
    if (t === 'flower') {
      const f = data.flower || {};
      q = (f.breeds || []).find((b) => b.name === this.data.name) || null;
      date = f.date || '';
    } else {
      q = (data.veg || []).find((v) => v.name === this.data.name && (!this.data.market || v.market === this.data.market)) || null;
      date = data.date || '';
    }
    if (!q) return;
    const price = t === 'flower' ? q.avg_price : q.price;
    const noQuote = !isNum(price) || Number(price) === 0;
    let range = null;
    if (isNum(q.low) && isNum(q.high) && Number(q.high) >= Number(q.low)) {
      const lo = Number(q.low), hi = Number(q.high), av = Number(price);
      range = {
        lowText: fmt.fmtPrice(lo), highText: fmt.fmtPrice(hi), avgText: fmt.fmtPrice(av),
        dot: (hi > lo ? Math.max(0, Math.min(100, (av - lo) / (hi - lo) * 100)) : 50).toFixed(1)
      };
    }
    const lag = daysAgo(date);
    this.setData({
      quote: {
        price: Number(price),
        priceText: noQuote ? '' : fmt.fmtPrice(price),
        noQuote: noQuote,
        pctText: fmt.pctText(q.change_pct),
        pctClass: fmt.pctClass(q.change_pct, fmt.getColorMode()),
        hasPct: isNum(q.change_pct),
        date: date,
        dateShort: md(date),
        lagText: lag >= 3 ? '距今 ' + lag + ' 天' : ''
      },
      unit: q.unit || this.data.unit,
      source: q.source || this.data.source,
      range: range
    });
  },

  _applyHistory(h) {
    const pts = (Array.isArray(h.points) ? h.points : []).filter((p) => p && p.date && isNum(p.value))
      .map((p) => ({ date: p.date, value: Number(p.value) }))
      .sort((a, b) => (a.date < b.date ? -1 : 1));
    this._points = pts;
    this.setData({ unit: this.data.unit || h.unit || '', source: this.data.source || h.source || '' });
  },

  // 跨期比：最新一格 = 历史最后一个点（与报价同源时日期一致）
  _buildCmp() {
    const pts = this._points || [];
    if (!pts.length) { this.setData({ cmp: [] }); return; }
    const last = pts[pts.length - 1];
    const lastDay = toDate(last.date);
    const cells = [{ label: md(last.date), valueText: fmt.fmtPrice(last.value), sub: '最新', now: true }];
    CMP_OFFSETS.forEach((o) => {
      const target = new Date(lastDay.getTime());
      target.setDate(target.getDate() - o.days);
      const t = iso(target);
      let hit = null;
      for (let i = pts.length - 1; i >= 0; i--) { if (pts[i].date <= t) { hit = pts[i]; break; } }
      cells.push(hit
        ? { label: o.label, valueText: fmt.fmtPrice(hit.value), sub: md(hit.date), now: false }
        : { label: o.label, valueText: '—', sub: '暂无数据', now: false, empty: true });
    });
    this.setData({ cmp: cells });
  },

  onChangeRange(e) {
    const days = Number(e.currentTarget.dataset.days);
    if (!days || days === this.data.historyDays) return;
    this.setData({ historyDays: days }, () => this._drawRange());
  },

  _drawRange() {
    const pts = this._points || [];
    if (!pts.length) { this.setData({ chartPoints: 0, chartNote: '' }); return; }
    const lastDay = toDate(pts[pts.length - 1].date);
    const from = new Date(lastDay.getTime());
    from.setDate(from.getDate() - this.data.historyDays);
    const f = iso(from);
    const sel = pts.filter((p) => p.date >= f);
    const firstAll = pts[0].date;
    let note = '共 ' + sel.length + ' 个有报价的日子 · 休市日无数据';
    if (this.data.historyDays >= 365 && firstAll > f) note += ' · 最早只到 ' + md(firstAll);
    if (this.data.quote && !this.data.quote.noQuote) note += ' · 虚线=最新均价';
    this.setData({ chartPoints: sel.length, chartNote: note }, () => {
      setTimeout(() => this._drawChart(sel), CANVAS_DRAW_DELAY);
    });
  },

  _drawChart(points) {
    if (!points || points.length < 2) return;
    const w = this.data.chartWidth, h = this.data.chartHeight;
    const padL = 4, padR = 4, padT = 22, padB = 22;
    const ctx = wx.createCanvasContext('detailChart', this);
    const vals = points.map((p) => p.value);
    let min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
    const iMax = vals.indexOf(max), iMin = vals.indexOf(min);
    if (max === min) { max += 0.5; min -= 0.5; }
    const n = points.length;
    const X = (i) => padL + (w - padL - padR) * i / (n - 1);
    const Y = (v) => padT + (h - padT - padB) * (1 - (v - min) / (max - min));

    // 面积
    ctx.beginPath();
    ctx.moveTo(X(0), h - padB);
    points.forEach((p, i) => ctx.lineTo(X(i), Y(p.value)));
    ctx.lineTo(X(n - 1), h - padB);
    ctx.closePath();
    ctx.setFillStyle(COLORS.fill);
    ctx.fill();
    // 最新均价虚线（只在区间内才画）
    const q = this.data.quote;
    if (q && !q.noQuote && q.price >= min && q.price <= max) {
      ctx.setLineDash([3, 4], 0);
      ctx.setStrokeStyle('rgba(20,83,45,0.4)');
      ctx.setLineWidth(1);
      ctx.beginPath(); ctx.moveTo(0, Y(q.price)); ctx.lineTo(w, Y(q.price)); ctx.stroke();
      ctx.setLineDash([], 0);
    }
    // 折线
    ctx.setStrokeStyle(COLORS.line);
    ctx.setLineWidth(2);
    ctx.setLineJoin('round');
    ctx.beginPath();
    points.forEach((p, i) => (i ? ctx.lineTo(X(i), Y(p.value)) : ctx.moveTo(X(i), Y(p.value))));
    ctx.stroke();
    // 最高 / 最低标注（接口原值 + 日期）
    ctx.setFontSize(10);
    const tag = (i, color, text, above) => {
      const x = X(i), y = Y(points[i].value);
      ctx.setFillStyle(color);
      ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 2 * Math.PI); ctx.fill();
      const tw = text.length * 6;
      const tx = Math.max(0, Math.min(w - tw, x - tw / 2));
      ctx.fillText(text, tx, above ? y - 7 : y + 15);
    };
    tag(iMax, COLORS.up, '最高 ' + fmt.fmtPrice(points[iMax].value) + ' · ' + md(points[iMax].date), true);
    if (iMin !== iMax) tag(iMin, COLORS.down, '最低 ' + fmt.fmtPrice(points[iMin].value) + ' · ' + md(points[iMin].date), false);
    // 末点
    ctx.setFillStyle('#FFFFFF');
    ctx.setStrokeStyle(COLORS.line);
    ctx.setLineWidth(2.5);
    ctx.beginPath(); ctx.arc(X(n - 1), Y(points[n - 1].value), 5, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
    // 首尾日期
    ctx.setFillStyle(COLORS.text);
    ctx.setFontSize(10);
    ctx.fillText(md(points[0].date), 0, h - 4);
    ctx.fillText(md(points[n - 1].date), w - 30, h - 4);
    ctx.draw();
  },

  // ─── 关注 ───
  _key() {
    return this.data.type === 'flower' ? 'flower:' + this.data.name : 'veg:' + this.data.name + ':' + (this.data.market || '');
  },
  _refreshWatched() {
    const list = wx.getStorageSync('watchlist');
    const key = this._key();
    this.setData({ watched: Array.isArray(list) && list.some((it) => it.key === key) });
  },
  onToggleWatch() {
    const key = this._key();
    let list = wx.getStorageSync('watchlist');
    if (!Array.isArray(list)) list = [];
    const idx = list.findIndex((it) => it.key === key);
    const adding = idx < 0;
    if (adding) {
      const q = this.data.quote || {};
      list.push({ key: key, type: this.data.type, name: this.data.name, market: this.data.market || '', created_at: '',
        price: q.noQuote ? null : q.price, pct: null, unit: this.data.unit, source: this.data.source, date: q.date || '' });
    } else {
      list.splice(idx, 1);
    }
    wx.setStorageSync('watchlist', list);
    this.setData({ watched: adding });
    wx.showToast({ title: adding ? '已关注' : '已取消关注', icon: 'none' });
    const openid = wx.getStorageSync('openid');
    if (openid) (adding ? api.addWatch(openid, key) : api.removeWatch(openid, key)).catch(() => {});
  },

  onShowFestival() {
    const f = this.data.festival;
    if (f) wx.showModal({ title: f.festival, content: f.rule || f.advice || f.date, showCancel: false });
  }
});
