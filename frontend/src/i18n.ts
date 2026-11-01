import { useSyncExternalStore } from 'react'
import { en } from './locales/en'

export type Language = 'en-US' | 'zh-CN'
// Earlier releases saved the browser's auto-detected locale without a user choice.
// Start the new explicit-choice preference in English, including on upgrade.
const storageKey = 'reclaim-radar.language.v2'
function detectLanguage(): Language {
  try {
    const saved = localStorage.getItem(storageKey)
    if (saved === 'en-US' || saved === 'zh-CN') return saved
  } catch { /* Storage can be unavailable in private browser sessions. */ }
  return 'en-US'
}
let language = detectLanguage()
const listeners = new Set<() => void>()
export const getLanguage = () => language
export function setLanguage(value: Language) {
  language = value
  try { localStorage.setItem(storageKey, value) } catch { /* Keep in memory. */ }
  document.documentElement.lang = value
  document.title = value === 'zh-CN' ? '回收雷达' : 'Reclaim Radar'
  listeners.forEach(listener => listener())
}
export function useLanguage(): [Language, typeof setLanguage] {
  return [useSyncExternalStore(listener => { listeners.add(listener); return () => { listeners.delete(listener) } }, getLanguage), setLanguage]
}
export function t(source: string, values: unknown[] = []): string {
  const text = language === 'zh-CN' ? source : en[source] ?? source
  return text.replace(/\{(\d+)\}/g, (match, index) => values[Number(index)] === undefined ? match : String(values[Number(index)]))
}
/** Translate known application diagnostics only; never rewrite seller evidence. */
export function message(value: unknown): string {
  const text = value == null ? '' : String(value)
  if (text.startsWith('Error: ')) return 'Error: ' + message(text.slice(7))
  if (language === 'zh-CN') return Object.entries(en).find(([, english]) => english === text)?.[0] ?? text
  const patterns: [RegExp, (...values: string[]) => string][] = [
    [/^正在自动恢复已保存的位置：(.*) · (.*) miles$/, (zip, radius) => `Restoring location: ${zip} · ${radius} miles`],
    [/^当前页面尚未确认 (.*) \/ (.*) miles；已保存的偏好可随时修改或删除。$/, (zip, radius) => `Verify ${zip} / ${radius} miles. Saved preferences can be edited or forgotten.`],
    [/^搜索 (.*)$/, keyword => `Searching ${keyword}`],
    [/^查询 (.*)（(\d+)\/(\d+)，已导入 (\d+) 条）$/, (model, index, total, count) => `Checking ${model} (${index}/${total}, ${count} imported)`],
    [/^导入 (\d+) 条参考；(\d+) 个来源\/型号问题$/, (count, errors) => `Imported ${count} references; ${errors} source/model issues`],
    [/^检查售出状态 (\d+)\/(\d+) · 已删除 (\d+)$/, (checked, total, deleted) => `Availability: ${checked}/${total} · Deleted ${deleted}`],
    [/^售出检查完成：检查 (\d+)，删除 (\d+)，保留已售 (\d+)，未确认 (\d+)$/, (checked, deleted, kept, unknown) => `Checked ${checked} · Deleted ${deleted} · Saved and sold ${kept} · Unverified ${unknown}`],
    [/^(.*): 新增 (\d+)，重复命中 (\d+)，候选 (\d+)，待核价 (\d+)，系统排除 (\d+)(.*)$/, (keyword, fresh, existing, candidates, review, excluded, warning) => `${keyword}: New ${fresh} · Existing ${existing} · Candidates ${candidates} · Price review ${review} · Excluded ${excluded}${warning ? ' · Check unexpected count drop' : ''}`],
    [/^按(型号基准预计|粗估保守)利润 \$(.*)，低于目标 \$(.*?)(，不划算|；价格依据未充分交叉核对，先待核价，不判定不划算)$/, (basis, profit, target, result) => `${basis === '型号基准预计' ? 'Expected' : 'Conservative'} profit $${profit} is below target $${target}. ${result.startsWith('；') ? 'Price evidence requires cross-checking before exclusion.' : 'Below target.'}`],
    [/^浏览器操作失败: (.*)$/, detail => `Browser operation failed: ${detail}`],
    [/^(.*) 必须为整数$/, field => `${field} must be a whole number.`],
    [/^(.*) 范围 (.*)$/, (field, range) => `${field} must be in range ${range}.`],
  ]
  for (const [pattern, format] of patterns) {
    const match = text.match(pattern)
    if (match) return format(...match.slice(1))
  }
  return t(text)
}
document.documentElement.lang = language
document.title = language === 'zh-CN' ? '回收雷达' : 'Reclaim Radar'
