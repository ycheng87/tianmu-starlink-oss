function pad(n) {
  return n < 10 ? '0' + n : '' + n;
}

function fmtDate(str) {
  if (!str) {
    return '';
  }
  const parts = String(str).split('-');
  if (parts.length === 3) {
    return parseInt(parts[1], 10) + '月' + parseInt(parts[2], 10) + '日';
  }
  return String(str);
}

function pctText(p) {
  if (p === null || p === undefined || p === '' || isNaN(Number(p))) {
    return '—';
  }
  const n = Number(p);
  if (n === 0) {
    return '±0.0%';
  }
  return (n > 0 ? '+' : '') + n.toFixed(1) + '%';
}

// [优化] P1-9: 支持颜色模式切换
// colorMode: 'redUp'（涨红跌绿，A股习惯）或 'greenUp'（涨绿跌红，国际习惯）
function pctClass(p, colorMode) {
  if (p === null || p === undefined || p === '' || isNaN(Number(p))) {
    return 'flat';
  }
  const n = Number(p);
  const mode = colorMode || 'redUp';
  if (n > 0) {
    return mode === 'greenUp' ? 'up-green' : 'up';
  }
  if (n < 0) {
    return mode === 'greenUp' ? 'down-green' : 'down';
  }
  return 'flat';
}

// [优化] P1-9: 获取当前颜色模式
function getColorMode() {
  try {
    const mode = wx.getStorageSync('color_mode');
    return mode === 'greenUp' ? 'greenUp' : 'redUp';
  } catch (e) {
    return 'redUp';
  }
}

function fmtPrice(p) {
  if (p === null || p === undefined || p === '' || isNaN(Number(p))) {
    return '—';
  }
  return Number(p).toFixed(2);
}

module.exports = {
  fmtDate: fmtDate,
  pctText: pctText,
  pctClass: pctClass,
  fmtPrice: fmtPrice,
  getColorMode: getColorMode
};
