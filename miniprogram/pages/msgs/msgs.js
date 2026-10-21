const api = require('../../utils/api.js');
const app = getApp();

function tagInfo(m) {
  const type = m && m.type;
  if (type === 'weather') {
    return { tagText: '天气', tagClass: 'weather' };
  }
  if (type === 'price') {
    return { tagText: '价格', tagClass: 'price' };
  }
  return { tagText: (m && m.category) || '资讯', tagClass: 'context' };
}

Page({
  data: {
    loading: true,
    error: '',
    list: [],
    dateText: '',
    themeClass: ''
  },

  onLoad() {
    this._syncTheme();
    this.loadMsgs();
  },

  onShow() {
    this._syncTheme();
  },

  _syncTheme() {
    const theme = app.syncTheme();
    this.setData({ themeClass: theme === 'dark' ? 'theme-dark' : '' });
  },

  onPullDownRefresh() {
    this.loadMsgs(() => {
      wx.stopPullDownRefresh();
    });
  },

  loadMsgs(done) {
    this.setData({ loading: true, error: '' });
    api.getAlerts()
      .then((data) => {
        const items = (data && data.items) || [];
        const list = items.map((m, i) => {
          const tag = tagInfo(m);
          return {
            key: 'msg' + i,
            title: m.title || '',
            detail: m.detail || '',
            category: m.category || '',
            type: m.type || '',
            market: m.market || '',
            change_pct: m.change_pct,
            date: m.date || '',
            time: m.time || '',
            tagText: tag.tagText,
            tagClass: tag.tagClass
          };
        });
        this.setData({
          loading: false,
          error: '',
          list: list,
          dateText: (data && data.date) || ''
        });
      })
      .catch((err) => {
        this.setData({
          loading: false,
          error: (err && err.message) || '加载失败，请检查网络后重试',
          list: []
        });
      })
      .then(() => {
        if (typeof done === 'function') {
          done();
        }
      });
  },

  onRetry() {
    this.loadMsgs();
  },

  onGoIndex() {
    wx.switchTab({
      url: '/pages/index/index'
    });
  }
});
