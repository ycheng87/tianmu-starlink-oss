// 隐私协议统一入口：微信版 v1.4
// ⚠️ 从抖音版搬来时必须改：抖音无 requirePrivacyAuthorize（平台托管、直接放行），
// 微信调隐私/定位接口前必须先 requirePrivacyAuthorize 获同意，否则隐私合规不过。
let granted = false;

function ensure() {
  if (granted || !wx.requirePrivacyAuthorize) {
    return Promise.resolve(true);
  }
  return new Promise((resolve) => {
    wx.requirePrivacyAuthorize({
      success: () => { granted = true; resolve(true); },
      fail: () => resolve(false)
    });
  });
}

function locationAuthorized() {
  return new Promise((resolve) => {
    wx.getSetting({
      success: (s) => {
        const v = s.authSetting && s.authSetting['scope.userLocation'];
        resolve(v !== false);
      },
      fail: () => resolve(false)
    });
  });
}

module.exports = { ensure, locationAuthorized };
