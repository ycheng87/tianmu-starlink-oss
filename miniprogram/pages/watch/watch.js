const api = require('../../utils/api.js');
const fmt = require('../../utils/format.js');
const app = getApp();

Page({
  data: {
    loading: true,
    error: '',
    list: [],
    displayList: [],
    activeFilter: 'all',
    filterOptions: [
      { key: 'all', label: '全部' },
      { key: 'flower', label: '鲜花' },
      { key: 'veg', label: '菜品' }
    ],
    editing: false,
    themeClass: ''
  },

  onLoad() {
    this._syncTheme();
  },

  onShow() {
    this._syncTheme();
    this.loadWatch();
  },

  _syncTheme() {
    const theme = app.syncTheme();
    this.setData({ themeClass: theme === 'dark' ? 'theme-dark' : '' });
  },

  onPullDownRefresh() {
    this.loadWatch(() => {
      wx.stopPullDownRefresh();
    });
  },

  loadWatch(done) {
    const openid = wx.getStorageSync('openid');
    this.setData({ loading: true, error: '' });

    // 优先从云端拉关注列表，失败 fallback 本地
    const fetchCloud = openid
      ? api.getWatchList(openid).then((data) => {
          const items = (data && data.items) || [];
          if (items.length > 0) {
            // 云端有数据时，以云端为准同步到本地
            const localList = this.getWatchList();
            const cloudKeys = {};
            items.forEach((it) => { cloudKeys[it.key] = true; });
            const merged = items.map((it) => {
              const local = localList.find((item) => item.key === it.key) || {};
              return {
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
              };
            });
            // 保留本地独有的
            localList.forEach((it) => {
              if (!cloudKeys[it.key]) merged.push(it);
            });
            wx.setStorageSync('watchlist', merged);
            return merged;
          }
          return this.getWatchList();
        })
      : Promise.resolve(this.getWatchList());

    fetchCloud
      .catch(() => this.getWatchList())
      .then((stored) => {
        if (!stored || !stored.length) {
          this.setData({ loading: false, error: '', list: [], displayList: [] });
          if (typeof done === 'function') done();
          return;
        }
        return api.getQuotes()
          .then((data) => {
            const list = this.resolve(stored, data);
            this.setData({ loading: false, error: '', list: list }, () => this.applyView());
          })
          .catch((err) => {
            // 接口失败时用关注时缓存的快照兜底
            const list = this.fromSnapshot(stored);
            if (list.length) {
              this.setData({ loading: false, error: '', list: list }, () => this.applyView());
            } else {
              this.setData({
                loading: false,
                error: (err && err.message) || '加载失败，请检查网络后重试',
                list: []
              });
            }
          });
      })
      .then(() => {
        if (typeof done === 'function') {
          done();
        }
      });
  },

  getWatchList() {
    const list = wx.getStorageSync('watchlist');
    return Array.isArray(list) ? list : [];
  },

  resolve(stored, data) {
    if (!stored.length) {
      return [];
    }
    const veg = (data && data.veg) || [];
    const breeds = (data && data.flower && data.flower.breeds) || [];
    return stored.map((it) => {
      let price = null;
      let pct = null;
      let unit = '';
      let sub = '';
      let found = false;
      if (it.type === 'veg') {
        const hit = veg.find((v) => {
          return v.name === it.name && (v.market || '') === (it.market || '');
        });
        if (hit) {
          found = true;
          price = hit.price;
          pct = hit.change_pct;
          unit = hit.unit || it.unit;
        }
        sub = [it.market || (hit && hit.market) || '', (hit && hit.source) || it.source || '', (data && data.date) || ''].filter(Boolean).join(' · ');
      } else {
        const hit = breeds.find((b) => b.name === it.name);
        if (hit) {
          found = true;
          price = hit.avg_price;
          pct = hit.change_pct;
          unit = hit.unit || it.unit;
        }
        sub = [(hit && hit.source) || it.source || '', (data && data.flower && data.flower.date) || ''].filter(Boolean).join(' · ');
      }
      // 展示的涨跌来自 /quotes change_pct；关注记录中的 it.pct 仅为离线快照。
      const displayPrice = found ? price : it.price;
      const displayPct = found ? pct : it.pct;
      return Object.assign({}, it, {
        sub: sub,
        priceText: fmt.fmtPrice(displayPrice),
        pctText: fmt.pctText(displayPct),
        pctClass: fmt.pctClass(displayPct),
        unit: unit || it.unit || '',
        noQuote: it.type === 'veg' && displayPrice !== null && displayPrice !== undefined && Number(displayPrice) === 0
      });
    });
  },

  fromSnapshot(stored) {
    return stored.map((it) => {
      return Object.assign({}, it, {
        sub: it.type === 'veg'
          ? [it.market || '', it.source || '', it.date || ''].filter(Boolean).join(' · ')
          : [it.source || '', it.date || ''].filter(Boolean).join(' · '),
        priceText: fmt.fmtPrice(it.price),
        pctText: fmt.pctText(it.pct),
        pctClass: fmt.pctClass(it.pct),
        unit: it.unit || '',
        noQuote: it.type === 'veg' && it.price !== null && it.price !== undefined && Number(it.price) === 0
      });
    });
  },

  onRemove(e) {
    const key = e.currentTarget.dataset.key;
    const openid = wx.getStorageSync('openid');
    let list = this.getWatchList();
    list = list.filter((it) => it.key !== key);
    wx.setStorageSync('watchlist', list);
    this.setData({
      list: this.data.list.filter((it) => it.key !== key)
    }, () => this.applyView());
    // 云端同步
    if (openid) {
      api.removeWatch(openid, key).catch(() => {});
    }
  },

  onRetry() {
    this.loadWatch();
  },

  onSelectFilter(e) {
    const filter = e.currentTarget.dataset.filter || 'all';
    this.setData({ activeFilter: filter }, () => this.applyView());
  },

  onToggleEdit() {
    this.setData({ editing: !this.data.editing });
  },

  applyView() {
    const list = this.data.list || [];
    const visible = this.data.activeFilter === 'all'
      ? list
      : list.filter((item) => item.type === this.data.activeFilter);
    this.setData({ displayList: visible });
  },

  onGoIndex() {
    wx.switchTab({
      url: '/pages/index/index'
    });
  }
});
