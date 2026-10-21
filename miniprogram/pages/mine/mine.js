const api = require('../../utils/api.js');
const fmt = require('../../utils/format.js');
const app = getApp();

Page({
  data: {
    loading: true,
    isLoggedIn: false,
    themeClass: '',
    userInfo: {
      avatarUrl: '',
      nickName: '',
      gender: 0,
      city: '',
      province: ''
    },
    watchCount: 0,
    msgCount: 0,
    // [优化] P1-13: 版本号更新
    appVersion: '1.6.0',
    // [优化] P1-9: 涨跌颜色模式
    colorMode: 'redUp',
    colorModeText: '涨红跌绿（A股习惯）',
    // 功能菜单
    menuList: [
      { key: 'watchlist', icon: '⭐', title: '我的关注', desc: '查看关注品种行情', path: '/pages/watch/watch' },
      { key: 'messages', icon: '📢', title: '消息中心', desc: '查看最新波动提示', path: '/pages/msgs/msgs' },
      { key: 'about', icon: 'ℹ️', title: '关于田亩星链', desc: '版本信息与说明', path: '' }
    ]
  },

  onLoad() {
    this._syncTheme();
    this.refreshCounts();
    this.checkLoginStatus();
  },

  onShow() {
    this._syncTheme();
    this.refreshCounts();
    // [优化] P1-9: 加载颜色模式
    this._loadColorMode();
    // 每次切回页面时尝试获取用户信息
    if (this.data.isLoggedIn && !this.data.userInfo.nickName) {
      this.loadUserInfo();
    }
  },

  _syncTheme() {
    const theme = app.syncTheme();
    this.setData({ themeClass: theme === 'dark' ? 'theme-dark' : '' });
  },

  // [优化] P1-9: 加载颜色模式
  _loadColorMode() {
    const mode = fmt.getColorMode();
    const text = mode === 'greenUp' ? '涨绿跌红（国际习惯）' : '涨红跌绿（A股习惯）';
    this.setData({ colorMode: mode, colorModeText: text });
  },

  // [优化] P1-9: 切换涨跌颜色模式
  onToggleColorMode() {
    const newMode = this.data.colorMode === 'redUp' ? 'greenUp' : 'redUp';
    wx.setStorageSync('color_mode', newMode);
    const text = newMode === 'greenUp' ? '涨绿跌红（国际习惯）' : '涨红跌绿（A股习惯）';
    this.setData({ colorMode: newMode, colorModeText: text });
    wx.showToast({ title: '颜色模式已切换', icon: 'success', duration: 1500 });
  },

  checkLoginStatus() {
    const openid = wx.getStorageSync('openid');
    this.setData({ isLoggedIn: !!openid, loading: false });
    if (openid) {
      this.loadUserInfo();
    }
  },

  loadUserInfo() {
    // 先从本地缓存加载，避免闪烁
    const cached = wx.getStorageSync('mine_userInfo');
    if (cached && cached.nickName) {
      this.setData({ userInfo: cached });
    }
  },

  refreshCounts() {
    const watchlist = wx.getStorageSync('watchlist');
    const watchCount = Array.isArray(watchlist) ? watchlist.length : 0;
    this.setData({ watchCount: watchCount });
  },

  // 登录
  onTapLogin() {
    api.login()
      .then((data) => {
        if (data && data.openid) {
          api.saveLogin(data);
          this.setData({ isLoggedIn: true });
        }
      })
      .catch(() => {
        wx.showToast({ title: '登录失败，请重试', icon: 'none' });
      });
  },

  // 点击菜单项
  onTapMenu(e) {
    const key = e.currentTarget.dataset.key;
    const path = e.currentTarget.dataset.path;
    if (path) {
      wx.switchTab({ url: path });
      return;
    }
    if (key === 'about') {
      wx.showModal({
        title: '关于田亩星链',
        content: '田亩星链 —— 花卉与蔬菜价格行情速览。\n\n' +
          '数据来源：\n' +
          '· 蔬菜：云南省农业农村厅《昆明市景臻-王旗营蔬菜批发市场蔬菜批发平均价格统计》\n' +
          '· 花卉：云南省农业农村厅《云南昆明斗南花卉市场花卉价格信息》\n' +
          '· 天气：和风天气\n' +
          '· 历史规律：基于 KIFA 花卉指数历史数据（2020–2026）统计\n\n' +
          '价格为批发/市场参考价，非地头收购价。本小程序仅供信息参考，不构成任何买卖或种收建议。\n\n' +
          '版本：v2.0.0',
        showCancel: false,
        confirmText: '我知道了'
      });
    }
  },

  // 退出登录
  onTapLogout() {
    const that = this;
    wx.showModal({
      title: '退出登录',
      content: '退出后关注列表将仅保存在本地。确定退出吗？',
      confirmText: '确定退出',
      cancelText: '取消',
      success(res) {
        if (res.confirm) {
          api.clearLogin();
          wx.removeStorageSync('mine_userInfo');
          that.setData({
            isLoggedIn: false,
            userInfo: {
              avatarUrl: '',
              nickName: '',
              gender: 0,
              city: '',
              province: ''
            }
          });
          wx.showToast({ title: '已退出登录', icon: 'none' });
        }
      }
    });
  },

  onPullDownRefresh() {
    this.refreshCounts();
    if (this.data.isLoggedIn) {
      this.loadUserInfo();
    }
    wx.stopPullDownRefresh();
  }
});
