// [优化] P0-1: 田亩星链 API v1 封装
// 正式域名：https://chengmo.top/api/v1
// 联调期内网 IP：http://175.178.219.189:8090/api/v1
const baseURL = 'https://chengmo.top/api/v1';
const BUILTIN_API_KEY = ''; // redacted in public repo: set via storage 'api_key_config'

// [优化] P0-1: 移除硬编码 API_KEY，改为从 storage 动态读取
function getApiKey() {
  try {
    const key = wx.getStorageSync('api_key_config');
    if (key && typeof key === 'string' && key.trim()) {
      return key.trim();
    }
  } catch (e) {
    /* storage 读取失败，使用空 key */
  }
  return BUILTIN_API_KEY;
}

// [优化] P0-2: 生成缓存 key（包含请求参数，避免不同参数缓存互相覆盖）
function cacheKey(path, data) {
  let base = 'cache_' + path.replace(/\//g, '_').replace(/[^a-zA-Z0-9_]/g, '');
  if (data && typeof data === 'object') {
    const keys = Object.keys(data).sort();
    const parts = [];
    for (let i = 0; i < keys.length; i++) {
      const k = keys[i];
      const v = data[k];
      if (v !== undefined && v !== null) {
        parts.push(k + '=' + String(v));
      }
    }
    if (parts.length > 0) {
      base += '|' + parts.join('&');
    }
  }
  return base;
}

// [优化] P0-2: 写入缓存
function setCache(path, data, payload) {
  try {
    wx.setStorageSync(cacheKey(path, data), {
      data: payload,
      _cacheTime: Date.now()
    });
  } catch (e) {
    /* 缓存写入失败静默 */
  }
}

// [优化] P0-2: 读取缓存
function getCache(path, data) {
  try {
    const cached = wx.getStorageSync(cacheKey(path, data));
    if (cached && cached.data) {
      return cached;
    }
  } catch (e) {
    /* 缓存读取失败静默 */
  }
  return null;
}

function request(path, data, method, extraHeaders) {
  method = method || 'GET';
  return new Promise((resolve, reject) => {
    // [优化] P0-1: API_KEY 从 storage 动态读取
    const apiKey = getApiKey();
    const headers = {
      'Content-Type': 'application/json',
      'X-API-Key': apiKey
    };
    if (extraHeaders) {
      Object.assign(headers, extraHeaders);
    }
    wx.request({
      url: baseURL + path,
      data: data || {},
      method: method,
      header: headers,
      success(res) {
        const body = res.data || {};
        if (res.statusCode >= 200 && res.statusCode < 300 && body.code === 0) {
          // [优化] P0-2: 请求成功，写入缓存
          setCache(path, data, body.data);
          resolve(body.data);
        } else if (res.statusCode >= 500) {
          // [优化] P0-2: 后端故障，尝试读取缓存兜底（解包后返回）
          const cached = getCache(path, data);
          if (cached) {
            const payload = (cached.data && typeof cached.data === 'object')
              ? Object.assign({}, cached.data)
              : cached.data;
            if (payload && typeof payload === 'object') payload._fromCache = true;
            resolve(payload);
          } else {
            const msg = body.msg || body.message || ('请求失败(' + res.statusCode + ')');
            reject(new Error(msg));
          }
        } else {
          const msg = body.msg || body.message || ('请求失败(' + res.statusCode + ')');
          reject(new Error(msg));
        }
      },
      fail(err) {
        // [优化] P0-2: 请求失败，尝试读取缓存兜底（解包后返回）
        const cached = getCache(path, data);
        if (cached) {
          const payload = (cached.data && typeof cached.data === 'object')
            ? Object.assign({}, cached.data)
            : cached.data;
          if (payload && typeof payload === 'object') payload._fromCache = true;
          resolve(payload);
        } else {
          reject(new Error(err.errMsg || '网络连接失败'));
        }
      }
    });
  });
}

function getQuotes() {
  return request('/quotes');
}

function getWeather(location) {
  return request('/weather', { location: location });
}

function getGeo(lat, lon) {
  return request('/geo', { lat: lat, lon: lon });
}

function getHistory(type, days, name) {
  const params = { type: type, days: days };
  if (name) {
    params.name = name;
  }
  return request('/history', params);
}

function getAlerts() {
  return request('/alerts');
}

function getFestivals() {
  return request('/festivals');
}

// ─── 登录 + 云端关注 ───

function login() {
  return new Promise((resolve, reject) => {
    wx.login({
      success(loginRes) {
        if (loginRes.code) {
          request('/login', { code: loginRes.code }, 'POST')
            .then((data) => {
              resolve(data); // { openid, token }
            })
            .catch(reject);
        } else {
          reject(new Error('wx.login 获取 code 失败'));
        }
      },
      fail(err) {
        reject(new Error(err.errMsg || 'wx.login 失败'));
      }
    });
  });
}

// 登录态签名（后端 10-05 已上线·兼容模式）：/login 返回 token，写关注必须带上
function getToken() {
  try {
    return wx.getStorageSync('tms_token') || '';
  } catch (e) {
    return '';
  }
}

function saveLogin(data) {
  if (!data || !data.openid) return;
  try {
    wx.setStorageSync('openid', data.openid);
    wx.setStorageSync('openid_time', Date.now());
    if (data.token) wx.setStorageSync('tms_token', data.token);
    wx.removeStorageSync('login_fail_at');
  } catch (e) { /* ignore */ }
}

function clearLogin() {
  try {
    wx.removeStorageSync('openid');
    wx.removeStorageSync('openid_time');
    wx.removeStorageSync('tms_token');
  } catch (e) { /* ignore */ }
}

function getWatchList(openid) {
  return request('/watchlist', { openid: openid });
}

function addWatch(openid, key) {
  return request('/watchlist', { openid: openid, key: key, action: 'add', token: getToken() }, 'POST');
}

function removeWatch(openid, key) {
  return request('/watchlist', { openid: openid, key: key, action: 'remove', token: getToken() }, 'POST');
}

// [优化] P0-1: 导出 getApiKey 供外部配置使用
module.exports = {
  baseURL: baseURL,
  getApiKey: getApiKey,
  request: request,
  getQuotes: getQuotes,
  getWeather: getWeather,
  getGeo: getGeo,
  getHistory: getHistory,
  getAlerts: getAlerts,
  getFestivals: getFestivals,
  login: login,
  getToken: getToken,
  saveLogin: saveLogin,
  clearLogin: clearLogin,
  getWatchList: getWatchList,
  addWatch: addWatch,
  removeWatch: removeWatch
};
