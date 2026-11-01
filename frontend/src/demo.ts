import { t } from './i18n'

/** Isolated, in-memory fixtures. No demo request is forwarded to the backend. */
export const isDemo = new URLSearchParams(location.search).get('demo') === '1'
type Row = Record<string, any>
const date = '2026-10-20T17:30:00Z'
let config: Row = {
  collection_scope: 'hardware', postal_code: '92121', radius_miles: 20,
  timezone: 'America/Los_Angeles', center_lat: 32.899, center_lon: -117.202,
  center_method: 'ZIP area center', interval_minutes: 30, max_cards: 60,
  max_details: 10, term_timeout_seconds: 180, auto_monitor: false,
  mode: 'local', target_profit: 20,
  costs: { pickup: 10, repair: 0, consumables: 5, time: 15, shipping: 20,
    local_fee_percent: 0, online_fee_percent: 13.25, risk_normal: 15, risk_medium: 30, risk_high: 55 },
  search_groups: [{ category: 'gpu', keywords: ['graphics card', 'RTX GPU'], max_price: 1500 }],
}
const fixtures = [
  ['gpu', 'RTX 3070', 'GeForce RTX 3070 · 8GB', 160, 260, 'San Diego, CA', 6.2, 'gpu'],
  ['pc', 'Ryzen 5600X / RTX 3060', 'Gaming desktop · Ryzen 5 + RTX 3060', 320, 520, 'La Jolla, CA', 8.4, 'pc'],
  ['cpu', 'Ryzen 7 5800X', 'AMD Ryzen 7 5800X · 8 cores', 85, 170, 'Mira Mesa, CA', 4.1, 'cpu'],
  ['ram', 'DDR4 32GB', '32GB DDR4 kit · 2 × 16GB', 30, 90, 'San Diego, CA', 10.3, 'ram'],
  ['gpu', 'RX 6700 XT', 'Radeon RX 6700 XT · 12GB', 135, 245, 'Poway, CA', 12.6, 'gpu'],
  ['storage', 'NVMe 2TB', '2TB NVMe SSD · PCIe 4.0', 65, 130, 'Del Mar, CA', 9.2, 'ram'],
]
let listings: Row[] = fixtures.map(([category, model, title, price, resale, city, miles, art], index) => ({
  id: `demo-${index + 1}`, category, model, title, price, location: city,
  url: '#', image: `/demo/${art}.svg`, currency: 'USD', first_seen: date, last_seen: date,
  details_at: date, review_decision: 'pending', screening_result: 'recommended',
  availability_status: 'available', overrides: {}, keywords: ['sample hardware'],
  description: 'Fictional listing for the interactive demo. No seller or live marketplace listing is represented.',
  valuation: {
    reference: { low: Number(resale) * .9, mid: resale, high: Number(resale) * 1.1,
      method: 'manual', confidence: 'manual', notes: 'Illustrative baseline, not market evidence.', evidence: [] },
    distance: { miles, confidence: 'coordinate', method: 'Illustrative distance' },
    point_based: true, resale_estimate: resale, expected_profit: Number(resale) - Number(price) - 45,
    max_offer: Number(resale) - 65, missing_costs: [], risks: [], reasons: [], components: [],
    specs: { model: [model] }, parts: [], price_type: 'fixed', costs: config.costs,
    price_verification: { status: 'manual', verified: true, notes: 'Demo baseline.' },
    calculation: { resale, purchase: price, deductions: 45, profit: Number(resale) - Number(price) - 45 },
    mode: 'local', target_profit: 20, rule_version: 'demo',
  },
}))
let preferences: Row = { postal_code: '92121', radius_miles: 20, selected_label: 'San Diego, California', auto_restore: false }
let schedule: Row = { enabled: false, time: '09:00', timezone: 'America/Los_Angeles' }
const references = listings.map((item, index) => ({ id: index + 1, category: item.category, model: item.model,
  low: item.valuation.reference.low, mid: item.valuation.reference.mid, high: item.valuation.reference.high,
  source: 'Demo baseline', source_url: '#', market: 'local', price_kind: 'manual', currency: 'USD',
  data_date: '2026-10-20', observed_at: date, sample_count: null, notes: 'Fictional values for UI preview only.' }))

export async function demoApi(path: string, method = 'GET', body?: unknown): Promise<any> {
  const url = new URL(path, location.origin), p = url.searchParams, data = body as Row
  const route = url.pathname
  if (route === '/config') {
    if (method === 'PUT') { config = structuredClone(data); return { saved: true } }
    return { config: structuredClone(config) }
  }
  if (route === '/status') return {
    collector: { status: 'paused', message: t('演示模式不连接 Facebook 或外部价格来源。') },
    prices: { status: 'idle', message: 'Demo baselines' },
    totals: ['pending', 'keep', 'reject'].map(review_decision => ({ review_decision,
      screening_result: 'recommended', count: listings.filter(x => x.review_decision === review_decision).length })),
    coverage: [{ method: 'manual', count: listings.length }], reference_count: references.length,
    priced_model_count: references.length, location_preferences: preferences, last_ingest: date,
    availability: { schedule, paused: true, scan: { status: 'idle' } },
    price_category_coverage: references.map(x => ({ category: x.category, models: 1 })),
  }
  if (route === '/listings') {
    const view = p.get('view'), categories = p.get('category')?.split(',').filter(Boolean) || []
    let rows = listings.filter(x => (!view || view === 'all' || x.review_decision === view)
      && (!categories.length || categories.includes(x.category))
      && `${x.title} ${x.model} ${x.description}`.toLowerCase().includes((p.get('q') || '').toLowerCase())
      && (!p.has('min_price') || x.price >= Number(p.get('min_price')))
      && (!p.has('max_price') || x.price <= Number(p.get('max_price')))
      && (!p.has('min_profit') || x.valuation.expected_profit >= Number(p.get('min_profit')))
      && !['unknown', 'outside'].includes(p.get('distance_filter') || ''))
    const sort = p.get('sort'), direction = p.get('order') === 'asc' ? 1 : -1
    const value = (x: Row) => sort === 'price' ? x.price : sort === 'profit' ? x.valuation.expected_profit : sort === 'distance' ? x.valuation.distance.miles : Date.parse(x.first_seen)
    rows = rows.sort((a, b) => direction * (value(a) - value(b)))
    const offset = Number(p.get('offset') || 0), limit = Number(p.get('limit') || 36)
    return structuredClone({ total: rows.length, items: rows.slice(offset, offset + limit) })
  }
  if (route.startsWith('/listings/')) {
    const [, , id, operation] = route.split('/'), item = listings.find(x => x.id === id)
    if (!item) throw new Error('Demo listing not found')
    if (operation === 'decision' && method === 'POST') item.review_decision = data.decision
    else if (operation === 'history') return { audit: [], snapshots: [] }
    else if (method !== 'GET') throw new Error(t('演示模式不连接 Facebook 或外部价格来源。'))
    return structuredClone(item)
  }
  if (route === '/prices' && method === 'GET') {
    const rows = references.filter(x => (!p.get('category') || x.category === p.get('category')) && String(x.model).toLowerCase().includes((p.get('q') || '').toLowerCase()))
    return { total: rows.length, items: rows, bootstrap_rules: { gpu: [60, 150, 300], cpu: [30, 90, 200], ram: [10, 30, 70] } }
  }
  if (route === '/runs') return []
  if (route === '/collector/location-preferences') {
    preferences = method === 'DELETE' ? { ...preferences, auto_restore: false, selected_label: '' } : { ...preferences, ...data }
    return { saved: true }
  }
  if (route === '/collector/availability-schedule') { schedule = { ...data }; return { saved: true } }
  throw new Error(t('演示模式不连接 Facebook 或外部价格来源。'))
}
