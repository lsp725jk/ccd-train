/** 主题工具：全局深/浅切换与事件 */

/** 当前是否深色模式 */
export function isDark() {
  return typeof document !== 'undefined' &&
    document.documentElement.classList.contains('dark')
}

/** 订阅主题切换；返回取消函数。回调参数为布尔 dark。 */
export function onThemeChange(cb) {
  const handler = (e) => cb(!!(e && e.detail))
  window.addEventListener('ccd-theme', handler)
  return () => window.removeEventListener('ccd-theme', handler)
}
