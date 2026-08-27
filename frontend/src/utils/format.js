/** 通用显示格式化工具 */

/**
 * 折叠任务模型名中连续重复的「(重试)」后缀。
 * 「102 (重试) (重试) (重试) (重试) (重试)」 → 「102 (重试×5)」
 */
export function friendlyName(name) {
  if (!name) return name
  return String(name).replace(/( \(重试\))+/g, (m) => {
    const n = (m.match(/\(重试\)/g) || []).length
    return n > 1 ? ` (重试×${n})` : m
  })
}

/** 状态中文标签 */
export const STATUS_LABEL = {
  running: '运行中', queued: '排队中', success: '成功', failed: '失败', stopped: '已停止',
}
export const STATUS_TYPE = {
  running: 'primary', queued: 'info', success: 'success', failed: 'danger', stopped: 'warning',
}

/** 任务类型中文 */
export const TASK_LABEL = {
  detect: '检测', segment: '分割', classify: '分类',
  us_classify: '非监督分类', us_segment: '异常检测',
}
