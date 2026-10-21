App({
  onLaunch() {
    // [优化] P1-12: v1.1 关注功能使用本地缓存模拟，后端 watchlist 接口等登录后再接通
    const list = wx.getStorageSync('watchlist');
    if (!Array.isArray(list)) {
      wx.setStorageSync('watchlist', []);
    }

    // [优化] P1-12: openid 过期机制（7天），超期自动清除并重新登录
    this._checkOpenidExpiry();

    // [优化] P0-1: API_KEY 初始化，确保 storage 中有默认空值
    this._initApiKey();

    // 黑暗模式：检测系统主题
    this._detectTheme();
  },

  // 黑暗模式：检测系统主题（各页面 onShow 时也会调用以保持同步）
  _detectTheme() {
    try {
      const info = wx.getSystemInfoSync();
      this.globalData.theme = (info.theme === 'dark') ? 'dark' : 'light';
    } catch (e) {
      this.globalData.theme = 'light';
    }
  },

  // 黑暗模式：供页面 onShow 时调用，重新检测系统主题
  syncTheme() {
    // 强制浅色：用户常在户外看手机，强光下深色底更难看清（真机反馈"反光看不清"）
    this._detectTheme();
    return 'light';
  },

  // [优化] P1-12: 检查 openid 是否过期（7天）
  _checkOpenidExpiry() {
    try {
      const openid = wx.getStorageSync('openid');
      const openidTime = wx.getStorageSync('openid_time');
      if (openid && openidTime) {
        const now = Date.now();
        const sevenDays = 7 * 24 * 60 * 60 * 1000;
        if (now - openidTime > sevenDays) {
          // 超期，清除登录态
          wx.removeStorageSync('openid');
          wx.removeStorageSync('openid_time');
          wx.removeStorageSync('tms_token');
        }
      }
    } catch (e) {
      /* 静默处理 */
    }
  },

  // [优化] P0-1: 初始化 API_KEY（如果未配置则保持空）
  _initApiKey() {
    try {
      const key = wx.getStorageSync('api_key_config');
      if (key === undefined || key === null || key === '') {
        // 首次使用，设置空字符串占位
        wx.setStorageSync('api_key_config', '');
      }
    } catch (e) {
      /* 静默处理 */
    }
  },

  globalData: {
    watchlist: [],
    theme: 'light'
  }
});
