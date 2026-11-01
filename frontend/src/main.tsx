import React, { useEffect, useState, useRef } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'
import { t, useLanguage, getLanguage, message } from './i18n'
import { demoApi, isDemo } from './demo'
import { LanguageMenu } from './LanguageMenu'

type Obj = Record<string, any>
type Listing = Obj & { id: string; title: string; valuation: Obj; overrides: Obj }
const categories = (): Record<string,string> => ({pc:t("PC 主机"),gpu:t("显卡"),cpu:'CPU',motherboard:t("主板"),ram:t("内存"),storage:'SSD / HDD',psu:t("电源"),cooler:t("散热"),case:t("机箱"),bundle:t("零件包"),unknown:t("待识别"),mac:t("Mac 排除")})
const methodNames = (): Record<string,string> => ({exact:t("型号参考"),peer:t("同代粗估"),category:t("类别参考"),heuristic:t("规则粗估"),components:t("零件汇总"),manual:t("人工估价")})
const stateNames = (): Record<string,string> => ({needs_login:t("等待登录"),marketplace:t("已登录"),needs_location:t("待核验位置"),restoring_location:t("正在恢复位置"),verification:t("需要验证"),ready:t("监控就绪"),searching:t("正在搜索"),checking_sold:t("检查售出状态"),paused:t("已暂停"),parse_failed:t("解析异常"),error:t("运行异常"),unavailable:t("Marketplace 不可用")})
const money = (x: number | null | undefined) => x == null ? '—' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(x)
const stamp = (x: string | null | undefined) => x ? new Date(x).toLocaleString(getLanguage(),{timeZone:'America/Los_Angeles',hour12:false}) : t("尚无记录")
function listingSpecs(item: Listing): string[] {
  const v = item.valuation
  const components = (v.components || [])
    .filter((part: Obj) => ['pc', 'bundle'].includes(item.category) || part.category === item.category)
    .map((part: Obj) => `${categories()[part.category] || part.category} ${part.model}`)
  const specs = Object.values(v.specs || {}).flat().filter((value): value is string => typeof value === 'string')
  const normalize = (value: string) => value.replace(/\s+/g, '').toLowerCase()
  const values = [...components, ...specs]
  return values.filter((value, index) => !values.some((other, otherIndex) =>
    otherIndex !== index && normalize(other).includes(normalize(value)) &&
    (normalize(other).length > normalize(value).length || otherIndex < index)))
}
async function api(path: string, method='GET', body?: unknown) {
  if (isDemo) return demoApi(path, method, body)
  const res = await fetch('/api'+path,{method,headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)})
  if (!res.headers.get('content-type')?.includes('application/json')) throw new Error(t('本地服务不可用，请运行 Start.cmd。'))
  const data = await res.json()
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail))
  return data
}

function App() {
  useLanguage()
  const [page,setPage] = useState('listings')
  const [view,setView] = useState('pending')
  const [status,setStatus] = useState<Obj>({})
  const [items,setItems] = useState<Listing[]>([])
  const [total,setTotal] = useState(0)
  const [offset,setOffset] = useState(0)
  const [cats,setCats] = useState<string[]>([])
  const [multiCategory,setMultiCategory] = useState(false)
  const [query,setQuery] = useState('')
  const [sort,setSort] = useState('newest')
  const [order,setOrder] = useState('desc')
  const [distance,setDistance] = useState('all')
  const [minPrice,setMinPrice] = useState('')
  const [maxPrice,setMaxPrice] = useState('')
  const [minProfit,setMinProfit] = useState('')
  const [selected,setSelected] = useState<Listing|null>(null)
  const [error,setError] = useState('')
  const [notice,setNotice] = useState('')
  const [config,setConfig] = useState<Obj|null>(null)
  const [runs,setRuns] = useState<Obj[]>([])
  const [priceData,setPriceData] = useState<Obj>({items:[]})
  const [priceQuery,setPriceQuery] = useState('')
  const [priceCategory,setPriceCategory] = useState('')
  const [priceOffset,setPriceOffset] = useState(0)
  const [busy,setBusy] = useState(false)
  const [showLocation,setShowLocation] = useState(false)
  const [lastRefresh,setLastRefresh] = useState('')
  const [settingsText,setSettingsText] = useState('')
  const [importText,setImportText] = useState('')
  const [saleText,setSaleText] = useState('')
  const [keyword,setKeyword] = useState('gaming PC')
  const requestId = useRef(0)

  async function refresh() {
    const id = ++requestId.current
    try {
      const s = await api('/status')
      let result: any
      if (page==='listings') {
        const p = new URLSearchParams({view,category:cats.join(','),q:query,sort,order,distance_filter:distance,offset:String(offset),limit:'36'})
        if(minPrice)p.set('min_price',minPrice);if(maxPrice)p.set('max_price',maxPrice);if(minProfit)p.set('min_profit',minProfit)
        result = await api('/listings?'+p)
      }
      if(page==='prices') result = await api('/prices?q='+encodeURIComponent(priceQuery)+'&category='+priceCategory+'&offset='+priceOffset+'&limit=100')
      if(page==='runs') result = await api('/runs')
      if (id !== requestId.current) return
      setStatus(s)
      if(page==='listings'){setItems(result.items);setTotal(result.total)}
      if(page==='prices')setPriceData(result)
      if(page==='runs')setRuns(result)
      setLastRefresh(new Date().toISOString())
    } catch(e){if(id===requestId.current)setError(message(String(e)))}
  }
  useEffect(()=>{void api('/config').then(d=>{setConfig(d.config);setSettingsText(JSON.stringify(d.config,null,2))}).catch(e=>setError(String(e)))},[])
  useEffect(()=>{const first=setTimeout(()=>void refresh(),200);const id=setInterval(()=>void refresh(),30000);return()=>{clearTimeout(first);clearInterval(id);requestId.current++}},[page,view,cats.join(','),query,sort,order,distance,minPrice,maxPrice,minProfit,offset,priceQuery,priceCategory,priceOffset])
  useEffect(()=>setOffset(0),[view,cats.join(','),query,sort,order,distance,minPrice,maxPrice,minProfit])
  useEffect(()=>setPriceOffset(0),[priceQuery,priceCategory])
  async function action(path:string,body?:unknown,method='POST') {
    setBusy(true);setError('');setNotice('')
    try {const d=await api(path,method,body);setNotice(d.queued?t("操作已排队，请查看运行状态。"):t("已保存"));await refresh();return d}
    catch(e){setError(String(e));return null}
    finally{setBusy(false)}
  }
  async function decision(item:Listing,value:string) {
    const d=await action('/listings/'+item.id+'/decision',{decision:value})
    if(d && selected?.id===item.id)setSelected(d)
  }
  const count = (v:string) => (status.totals||[]).reduce((n:number,x:Obj)=>n+(v==='excluded'?x.review_decision==='pending'&&x.screening_result==='excluded'?x.count:0:v==='pending'?x.review_decision==='pending'&&!['excluded','price_review'].includes(x.screening_result)?x.count:0:v==='price_review'?x.review_decision==='pending'&&x.screening_result==='price_review'?x.count:0:x.review_decision===v?x.count:0),0)
  const coverage=(status.coverage||[]) as Obj[]
  const exact=coverage.filter(x=>x.method==='exact').reduce((n,x)=>n+x.count,0)
  const rough=coverage.filter(x=>x.method && x.method!=='exact').reduce((n,x)=>n+x.count,0)
  const uncertain=coverage.filter(x=>!x.method).reduce((n,x)=>n+x.count,0)
  const storedTotal=(status.totals||[]).reduce((n:number,x:Obj)=>n+x.count,0)
  const lastRun=status.last_completed_search?.[0]
  const lastRunStats=lastRun?JSON.parse(lastRun.metadata||'{}'):{}
  return <div className="shell"><a className="skip-link" href="#main-content">{t("跳到主要内容")}</a>
    <LanguageMenu/>
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e=>{e.preventDefault();setPage('listings')}}><span className="radar-icon">◉</span><span>{t("回收雷达")}<small>RECLAIM RADAR</small></span></a>
      <div className="site-label">{t("本地工作站 ")}<span>WINDOWS</span></div>
      <nav>{[['listings','⌕',t("找货台")],['prices','▥',t("价格参考库")],['runs','≋',t("运行记录")],['settings','⚙',t("设置")]].map(([id,icon,label])=><button key={id} className={page===id?'nav active':'nav'} aria-current={page===id?'page':undefined} onClick={()=>setPage(id)}><span>{icon}</span>{label}</button>)}</nav>
      <div className="sidebar-foot"><span className="dot"/>{t("仅本机访问")}<small>{config?.postal_code||'92121'} · {config?.radius_miles||20} miles<br/>{t("每天更新价格 · 洛杉矶时间")}</small><a href="/docs" target="_blank" rel="noreferrer">{t("接口文档 ↗")}</a></div>
    </aside>
    <main id="main-content">{isDemo&&<div className="demo-banner" role="status">{t("演示模式 · 示例数据仅保存在本次页面会话中")}</div>}
      <header><div className="eyebrow">{t("PC 主机与内部零件")}</div><div className="title-row"><div><h1>{page==='listings'?t("商品审核"):page==='prices'?t("价格参考"):page==='runs'?t("运行记录"):t("设置")}</h1><p>{config?.postal_code||'92121'} · {config?.radius_miles||20} miles <span className="sep">/</span>{t(" 不含 Mac ")}<span className="sep">/</span> {config?.mode==='online'?t("线上拆件"):t("本地转售")}</p></div><button className="primary" disabled={busy} onClick={()=>void action('/collector/search',{keyword,max_price:1500})}>{t("＋ 搜索一次")}</button></div></header>
      {error && <div role="alert" className="alert error">{error}<button aria-label={t('关闭提示')} onClick={()=>setError('')}>×</button></div>}
      {notice && <div role="status" className="alert">{notice}<button aria-label={t('关闭提示')} onClick={()=>setNotice('')}>×</button></div>}
      <section className="metrics"><div><small>{t("待审核")}</small><strong>{count('pending')}</strong><span>{t("等待人工决定")}</span></div><div><small>{t("已保留")}</small><strong>{count('keep')}</strong><span>{t("已保存到本机")}</span></div><div><small>{t("价格参考")}</small><strong>{status.priced_model_count||0}</strong><span>{t("有来源的型号 · ")}{status.reference_count||0}{t(" 条历史证据")}</span></div><div><small>{t("采集状态")}</small><strong className="status-value">{stateNames()[status.collector?.status]||t("连接中")}</strong><span>{status.collector?.current_keyword||t("单一浏览器 · 单一队列")}</span></div></section>
      <section className="connection"><div><span className={'dot '+(status.collector?.status==='ready'?'':'amber')}/><strong>{message(status.collector?.message)||t("正在连接本地服务…")}</strong><p>{status.location_preferences?.auto_restore ? t("已保存：{0} · {1} miles{2}。下次启动自动恢复。", [status.location_preferences.postal_code,status.location_preferences.radius_miles,status.location_preferences.selected_label ? " · "+status.location_preferences.selected_label : ""]) : t("自动恢复已关闭，可在位置偏好中重新保存。")}</p></div><div className="button-row"><button disabled={busy} onClick={()=>void action('/collector/connect')}>{t("连接 Facebook ↗")}</button><button disabled={busy} onClick={()=>{if(window.confirm(t("这会创建新的登录配置，需要重新登录。当前已经登录成功时，请用“检查并恢复”，不要重置。旧配置仍会保留。")))void action('/collector/recover-login')}}>{t("验证卡住？重新登录")}</button><button onClick={()=>setShowLocation(!showLocation)}>{t("位置偏好 · 修改 / 删除")}</button><button disabled={busy} onClick={()=>void action('/collector/verify')}>{t("自动恢复")}</button><button onClick={()=>void action('/collector/pause')}>{t("暂停")}</button></div></section>
      {showLocation && status.location_preferences && <LocationSettings initial={status.location_preferences} busy={busy} action={action} close={()=>setShowLocation(false)} changed={async()=>{const d=await api('/config');setConfig(d.config);setSettingsText(JSON.stringify(d.config,null,2))}}/>}
      <div className="timestamps"><span>{t("搜索成功：")}{stamp(status.collector?.last_search_success || status.last_search?.find((x:Obj)=>x.status==='success')?.finished_at)}</span><span>{t("商品入库：")}{stamp(status.last_ingest)}</span><span>{t("网页刷新：")}{stamp(lastRefresh)}</span></div>
      {lastRun&&<p className="muted">{t("最近完成「")}{lastRun.keyword}」：{lastRunStats.new_count!=null?<>{t("新增 ")}{lastRunStats.new_count}{t(" · 重复命中 ")}{lastRunStats.existing_count}{t(" · 本轮候选 ")}{lastRunStats.candidate_count}{t(" · 本轮排除 ")}{lastRunStats.excluded_count}{t(" · 待核价 ")}{lastRunStats.price_review_count||0}{t(" · 无关卡片 ")}{lastRunStats.scope_rejected}</>:<>{t("命中 ")}{lastRun.count}{t(" 条（旧记录未区分新增与重复）")}</>}{t("。待审核仅展示筛选后的候选，估价未充分核对的见“待核价”，其余见“系统排除”或“全部记录”。")}</p>}
      {page==='listings' && <>
        <div className="tabs">{[['pending',t("待审核")],['price_review',t("待核价")],['keep',t("已保留")],['reject',t("已拒绝")],['excluded',t("系统排除")],['all',t("全部记录")]].map(([v,l])=><button key={v} className={view===v?'selected':''} aria-pressed={view===v} onClick={()=>setView(v)}>{l}<span>{v==='all'?storedTotal:count(v)}</span></button>)}<div className="coverage">{t("型号参考 ")}{exact}{t(" · 粗估 ")}{rough}{t(" · 待确认 ")}{uncertain}</div></div>
        <div className="filters"><div className="search-input"><span>⌕</span><input aria-label={t("搜索商品")} placeholder={t("搜索标题、配置或描述")} value={query} onChange={e=>setQuery(e.target.value)}/></div><select aria-label={t("距离")} value={distance} onChange={e=>setDistance(e.target.value)}><option value="all">{t("全部距离")}</option><option value="known">{t("确认范围内")}</option><option value="unknown">{t("范围待确认")}</option><option value="outside">{t("确认范围外")}</option></select><select aria-label={t("排序")} value={sort} onChange={e=>setSort(e.target.value)}><option value="newest">{t("发现时间")}</option><option value="profit">{t("保守利润")}</option><option value="price">{t("商品价格")}</option><option value="distance">{t("距离")}</option></select><select aria-label={t("顺序")} value={order} onChange={e=>setOrder(e.target.value)}><option value="desc">{t("从高到低 / 最新")}</option><option value="asc">{t("从低到高 / 最早")}</option></select><input className="number-filter" aria-label={t("最低价 $")} placeholder={t("最低价 $")} type="number" value={minPrice} onChange={e=>setMinPrice(e.target.value)}/><input className="number-filter" aria-label={t("最高价 $")} placeholder={t("最高价 $")} type="number" value={maxPrice} onChange={e=>setMaxPrice(e.target.value)}/><input className="number-filter" aria-label={t("最低利润 $")} placeholder={t("最低利润 $")} type="number" value={minProfit} onChange={e=>setMinProfit(e.target.value)}/></div>
        <div className="category-chips" role="group" aria-label={t("种类筛选")}>{Object.entries(categories()).filter(([k])=>k!=='mac'&&(config?.collection_scope!=='pc_only'||view==='excluded'||view==='all'||k==='pc')).map(([k,label])=><button key={k} className={cats.includes(k)?'chip selected':'chip'} aria-pressed={cats.includes(k)} onClick={()=>setCats(current=>current.includes(k)?current.filter(x=>x!==k):multiCategory?[...current,k]:[k])}>{label}</button>)}<button className={multiCategory?'chip category-mode selected':'chip category-mode'} aria-pressed={multiCategory} title={t("开启后可同时筛选多个种类；关闭时保留最后选中的种类")} onClick={()=>{setMultiCategory(!multiCategory);if(multiCategory)setCats(current=>current.slice(-1))}}>{multiCategory?t("✓ 多选已开启"):t("多选")}</button>{cats.length>0&&<button className="text-button" onClick={()=>setCats([])}>{t("清除")}</button>}</div>
        <div className="result-heading"><strong>{total}{t(" 件")}{view==='pending'?t("待审核候选"):t("当前筛选商品")}</strong><span>{t("已入库共 ")}{storedTotal}{t(" 件 · 待核价 ")}{count("price_review")}{t(" 件 · 系统排除 ")}{count('excluded')}{t(" 件 · 型号商品按基准价算利润")}</span></div>
        {items.length===0 ? <div className="empty"><span className="empty-radar">◎</span><h2>{storedTotal?t("没有符合筛选条件的商品"):t("等待第一批真实商品")}</h2><p>{t("完成 Facebook 登录和位置核验后，雷达搜索 PC 主机和独立电脑零件。")}<br/>{t("先设置成本和位置，再运行一个搜索关键词。")}</p><div className="button-row">{storedTotal>0&&<button onClick={()=>{setCats([]);setQuery('');setDistance('all');setMinPrice('');setMaxPrice('');setMinProfit('');setOffset(0)}}>{t("清除筛选")}</button>}<input aria-label={t("搜索关键词")} value={keyword} onChange={e=>setKeyword(e.target.value)}/><button disabled={busy} onClick={()=>void action('/collector/search',{keyword,max_price:1500})}>{t("运行这个关键词 →")}</button></div></div>:
        <div className="listing-grid">{items.map(item=>{const v=item.valuation,r=v.reference;return <article className="listing" key={item.id}>
          <div className="listing-heading"><h2><button onClick={()=>setSelected(item)}>{item.overrides.title??item.title}</button></h2></div>
          <div className="photo">{item.image?<img src={item.image} alt="" loading="lazy" referrerPolicy="no-referrer" onError={e=>{e.currentTarget.style.display='none'}}/>:<span>▧</span>}<span className="category-tag">{categories()[item.category]}</span><span className="discovery">{new Date(item.first_seen).toLocaleDateString(getLanguage(),{timeZone:'America/Los_Angeles',month:'short',day:'numeric'})}</span></div>
          <div className="listing-body"><div className="listing-top"><span className={'quality '+(r?.method==='exact'?'':'rough')}>{methodNames()[r?.method]||t("待确认")}</span><span>{v.distance?.miles!=null?(v.distance.confidence==='city'?t("约 "):'')+v.distance.miles+' mi'+(v.distance.confidence==='city'?t(" · 待核实"):''):t("范围待确认")}</span></div><p className="location">{item.availability_status==='sold'&&<span className="sold-badge">{t("已售出")}{item.review_decision==='keep'?t(" · 已保留"):''}</span>}{item.location||t("地点未知")} · {item.model||t("型号未明确")}</p><div className="listing-specs" aria-label={t("已识别配置")}>{listingSpecs(item).length?listingSpecs(item).map(spec=><span key={spec}>{spec}</span>):<span className="specs-unknown">{t("配置待确认")}</span>}</div><div className="listing-numbers"><div><small>{t("卖家标价")}</small><strong>{money(item.overrides.price??item.price)}</strong></div><div><small>{t("估计转售价")}</small><strong>{r?(v.point_based?money(v.resale_estimate):money(r.low)+'–'+money(r.high)):t("待确认")}</strong></div></div><div className="profit-line"><span>{v.point_based?t("预计利润"):t("保守利润")}</span><strong className={(v.expected_profit??-1)>=0?'positive':''}>{money(v.expected_profit)}</strong><small>{t("最高出价 ")}{money(v.max_offer)}</small></div>{v.missing_costs?.length>0&&<p className="warning">{t("取货等成本尚未完整设置，利润为临时估算")}</p>}{v.risks?.length>0&&<p className="warning">{message(v.risks[0])}</p>}<div className="listing-actions"><button disabled={busy} className="keep" onClick={()=>void decision(item,'keep')}>{t("✓ 保留")}</button><button disabled={busy} onClick={()=>void decision(item,'reject')}>{t("拒绝")}</button><button onClick={()=>setSelected(item)}>{t("详情 ↗")}</button></div></div>
        </article>})}</div>}
        <div className="pagination"><button disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-36))}>{t("上一页")}</button><span>{Math.floor(offset/36)+1} / {Math.max(1,Math.ceil(total/36))}</span><button disabled={offset+36>=total} onClick={()=>setOffset(offset+36)}>{t("下一页")}</button></div>
      </>}
      {page==='prices' && <section className="panel"><div className="panel-title"><div><h2>{t("价格参考与每日更新")}</h2><p>{message(status.prices?.message)}{t(" · 最近成功 ")}{stamp(status.price_last_success)}{t(" · GPU/CPU目录 ")}{status.shs_catalog_count||0}{t(" · 综合目录 ")}{status.pcwatch_catalog_count||0}</p></div><div className="button-row"><button disabled={busy||status.prices?.status==='running'} onClick={()=>void action('/prices/refresh?full_catalog=true')}>{t("全目录建库 / 补抓")}</button><button className="primary" disabled={busy||status.prices?.status==='running'} onClick={()=>void action('/prices/refresh')}>{t("更新价格库")}</button></div></div><p className="muted">{t("成交参考与在售价分别保存。来源没有公布日期时显示“未公布”，每天读取不等于每天都有新成交。欧元参考会注明原价格及汇率日期。")}</p>{status.prices?.status==='running'&&<div className="price-progress"><progress value={status.prices.processed||0} max={status.prices.total||1}/><span>{message(status.prices.message)}</span></div>}<div className="price-coverage">{Object.entries(categories()).filter(([k])=>!['unknown','mac'].includes(k)).map(([k,label])=>{const n=(status.price_category_coverage||[]).find((x:Obj)=>x.category===k)?.models||0;return <button key={k} className={priceCategory===k?'selected':''} onClick={()=>setPriceCategory(priceCategory===k?'':k)}><strong>{label}</strong><span>{n}{t(" 个参考型号")}</span><small>{n?t("来源已接入"):t("市场数据待补 · 粗估可用")}</small></button>})}</div><div className="result-heading"><strong>{priceData.total||0}{t(" 条最新参考")}</strong><span>{t("同型号、同来源仅显示最新值；历史证据仍保留")}</span></div><input aria-label={t("查询价格型号")} className="wide" placeholder={t("查找型号，如 RTX 3070、Ryzen 5600X")} value={priceQuery} onChange={e=>setPriceQuery(e.target.value)}/><div className="table-wrap"><table><thead><tr><th>{t("型号 / 品类")}</th><th>{t("低 / 中 / 高估值")}</th><th>{t("来源与口径")}</th><th>{t("数据日期 / 读取时间")}</th><th>{t("依据")}</th></tr></thead><tbody>{priceData.items.map((r:Obj)=><tr key={r.id} className={r.quarantined?'quarantine':''}><td><strong>{r.model}</strong><small>{categories()[r.category]} · {r.market} · {r.sample_count??t("未知")}{t(" 样本 ")}{r.quarantined?t("· 已隔离"):''}</small></td><td>{money(r.low)} / {money(r.mid)} / {money(r.high)}</td><td><a href={r.source_url} target="_blank" rel="noreferrer">{r.source} ↗</a><small>{r.price_kind==='sold'?t("成交参考"):r.price_kind==='asking'?t("在售参考"):t("人工 / 规则")} · {r.currency}</small></td><td>{r.data_date||t("来源未公布")}<small>{stamp(r.observed_at)}</small></td><td><details><summary>{t("查看口径")}</summary><p>{message(r.notes)}</p></details></td></tr>)}</tbody></table></div>{!priceData.items.length&&<p className="muted">{t("尚无匹配的来源记录。")}</p>}<div className="pagination"><button disabled={priceOffset===0} onClick={()=>setPriceOffset(Math.max(0,priceOffset-100))}>{t("上一页")}</button><span>{Math.floor(priceOffset/100)+1} / {Math.max(1,Math.ceil((priceData.total||0)/100))}</span><button disabled={priceOffset+100>=(priceData.total||0)} onClick={()=>setPriceOffset(priceOffset+100)}>{t("下一页")}</button></div><h3>{t("全部品类的补缺规则")}</h3><p className="muted">{t("下表为可解释的初始粗估规则，非今日市场价格。已识别型号优先查询真实参考；内存与存储按容量调整，故障件另行折价。")}</p><div className="rule-grid">{Object.entries(priceData.bootstrap_rules||{}).map(([cat,values])=><div key={cat}><strong>{categories()[cat]}</strong><span>{(values as number[]).map(x=>money(x)).join(' / ')}</span><small>{t("低 / 中 / 高 · 极低置信度")}</small></div>)}</div><details className="import-box"><summary>{t("导入价格证据 / 本地成交")}</summary><p>{t("价格证据必须有链接、类别、型号和价格口径。使用接口文档中的 Evidence 格式；多条记录放在 references 数组。")}</p><textarea aria-label={t("价格证据 JSON")} value={importText} onChange={e=>setImportText(e.target.value)} placeholder={t("{\"references\": [{\"category\": \"gpu\", \"model\": \"RTX 3070\", \"low\": 180, \"mid\": 220, \"high\": 260, \"source\": \"实际来源名称\", \"source_url\": \"https://实际来源\", \"price_kind\": \"sold\", \"market\": \"US\", \"notes\": \"样本和口径\"}]}")} rows={6}/><button disabled={busy} onClick={()=>{try{void action('/prices/import',JSON.parse(importText))}catch(e){setError(String(e))}}}>{t("导入证据")}</button><p>{t("本地成交记录填写 category、model、purchase、repair、resale、mode、sold_at、notes，可附 listing_id。")}</p><textarea aria-label={t("成交记录 JSON")} rows={4} value={saleText} onChange={e=>setSaleText(e.target.value)} placeholder={t("粘贴实际成交 JSON，日期使用 ISO 格式")}/><button disabled={busy} onClick={()=>{try{void action('/sales',JSON.parse(saleText))}catch(e){setError(String(e))}}}>{t("保存实际成交")}</button></details></section>}
      {page==='runs' && <section className="panel"><div className="panel-title"><h2>{t("搜索与来源更新记录")}</h2><button onClick={()=>void refresh()}>{t("刷新记录")}</button></div><p className="muted">{t("card_limit 达到数量上限 · no_new_ids 连续滚动无新商品 · true_zero_results 明确零结果 · attention 需要人工处理。")}</p><div className="table-wrap"><table><thead><tr><th>{t("任务")}</th><th>{t("状态")}</th><th>{t("数量")}</th><th>{t("开始 / 结束")}</th><th>{t("原因与诊断")}</th></tr></thead><tbody>{runs.map(r=><tr key={r.id}><td>{r.kind==='search'?t("商品搜索"):r.kind==='availability'?t("售出检查"):t("价格更新")}<small>{r.keyword}</small></td><td><span className={'quality '+(r.status==='success'?'':'rough')}>{r.status}</span></td><td>{r.count}</td><td>{stamp(r.started_at)}<small>{stamp(r.finished_at)}</small></td><td><details><summary>{message(r.reason||t("运行中")).slice(0,90)}</summary><pre>{message(r.reason)}</pre><pre>{JSON.stringify(JSON.parse(r.metadata||'{}'),null,2)}</pre></details></td></tr>)}</tbody></table></div></section>}
      {page==='settings' && status.availability && <AvailabilitySettings data={status.availability} busy={busy} action={action}/>}
      {page==='settings' && config && <section className="panel"><div className="panel-title"><div><h2>{t("搜索、估价与运行设置")}</h2><p>{t("保存后重新估价，但不会改变保留 / 拒绝决定。")}</p></div><button disabled={busy} className="primary" onClick={async()=>{try{const c=JSON.parse(settingsText);const d=await action('/config',c,'PUT');if(d)setConfig(c)}catch(e){setError(String(e))}}}>{t("保存设置")}</button></div><div className="settings-grid"><div><h3>{t("搜索中心")}</h3><p className="muted">{t('使用已核实的美国邮编及其中心坐标；修改后需重新核验 Facebook 位置。')}</p>
{(['postal_code','center_lat','center_lon'] as const).map((key)=><label key={key}>{t(key==='postal_code'?'中心邮编':key==='center_lat'?'纬度':'经度')}<input type={key==='postal_code'?'text':'number'} inputMode={key==='postal_code'?'numeric':'decimal'} step="any" value={config[key]} onChange={e=>{const c={...config,[key]:key==='postal_code'?e.target.value:Number(e.target.value),center_method:'User-provided ZIP area center'};setConfig(c);setSettingsText(JSON.stringify(c,null,2))}}/></label>)}<h3>{t("常用设置")}</h3><label>{t("转售方式")}<select value={config.mode} onChange={e=>{const c={...config,mode:e.target.value};setConfig(c);setSettingsText(JSON.stringify(c,null,2))}}><option value="local">{t("本地整机 / 零件转售")}</option><option value="online">{t("线上拆件转售")}</option></select></label><label>{t("目标利润 $")}<input type="number" value={config.target_profit} onChange={e=>{const c={...config,target_profit:Number(e.target.value)};setConfig(c);setSettingsText(JSON.stringify(c,null,2))}}/></label><label className="checkbox"><input type="checkbox" checked={config.auto_monitor} onChange={e=>{const c={...config,auto_monitor:e.target.checked};setConfig(c);setSettingsText(JSON.stringify(c,null,2))}}/>{t("登录与位置确认后自动搜索")}</label><h3>{t("成本参数")}</h3><p className="muted">{t("留空代表未配置；若确实无此成本，明确输入 0。风险预留按商品状况另行计入。")}</p>{Object.entries({pickup:t("每次取货"),repair:t("维修"),consumables:t("耗材"),time:t("时间成本"),shipping:t("线上运费"),local_fee_percent:t("本地平台费 %"),online_fee_percent:t("线上平台费 %"),risk_normal:t("普通风险预留"),risk_medium:t("中风险预留"),risk_high:t("高风险预留")}).map(([k,label])=><label key={k}>{label}<input type="number" min="0" value={config.costs[k]??''} onChange={e=>{const c={...config,costs:{...config.costs,[k]:e.target.value===''?null:Number(e.target.value)}};setConfig(c);setSettingsText(JSON.stringify(c,null,2))}}/></label>)}</div><div><h3>{t("完整配置与搜索组")}</h3><p className="muted">{t("可编辑关键词、价格上限和采集间隔。最短间隔为 10 分钟。")}</p><textarea aria-label={t("完整配置 JSON")} className="config-editor" rows={36} value={settingsText} onChange={e=>{setSettingsText(e.target.value);try{const c=JSON.parse(e.target.value);if(c&&typeof c.costs==='object'&&c.costs)setConfig(c)}catch{/* Keep incomplete JSON editable. */}}}/></div></div><div className="button-row"><button disabled={busy} onClick={()=>void action('/backup')}>{t("立即备份数据库")}</button><a href="/api/research" target="_blank" rel="noreferrer">{t("查看 AI 补缺任务 ↗")}</a></div><p className="muted">{t("每天 07:00（洛杉矶时间）更新价格。服务需保持运行。")}</p></section>}
      <footer>RECLAIM RADAR <span>{t("本地保存 · 人工决策 · 每日价格参考")}</span></footer>
    </main>
    {selected && <Detail item={selected} close={()=>setSelected(null)} action={action} decision={decision} setItem={setSelected}/>}
  </div>
}

function AvailabilitySettings({data,busy,action}:{data:Obj;busy:boolean;action:(p:string,b?:unknown,m?:string)=>Promise<any>}) {
  const [time,setTime]=useState(data.schedule.time)
  const [enabled,setEnabled]=useState(data.schedule.enabled)
  const scan=data.scan
  const scanNames:Record<string,string>={idle:t("尚未运行"),running:t("检查中"),attention:t("等待处理"),completed:t("已完成")}
  return <section className="panel" aria-label={t("每日售出检查")}><div className="panel-title"><h2>{t("每日售出检查")}</h2><span className="muted">{!data.schedule.enabled?t("已停用"):data.paused?t("已暂停"):scanNames[scan.status]||scan.status}</span></div>
    <div className="button-row"><label className="checkbox"><input type="checkbox" checked={enabled} onChange={e=>setEnabled(e.target.checked)}/>{t("启用")}</label><label className="schedule-time">{t("每天")}<input aria-label={t("售出检查时间")} type="time" value={time} onChange={e=>setTime(e.target.value)}/></label><span className="muted">{t("洛杉矶时间")}</span><button disabled={busy||!time} onClick={()=>void action('/collector/availability-schedule',{enabled,time,timezone:'America/Los_Angeles'},'PUT')}>{t("保存时间")}</button><button disabled={busy||!data.schedule.enabled||scan.status==='running'} onClick={()=>void action('/collector/check-sold')}>{scan.status==='attention'?t("继续检查"):t("立即检查全部")}</button></div>
    <p className="muted">{t("已售出即删除；已保留商品除外。")}</p>
    {scan.total!=null&&<p className="muted">{t("进度 ")}{scan.checked} / {scan.total}{t(" · 已删除 ")}{scan.deleted}{t(" · 保留已售 ")}{scan.kept_sold}{t(" · 未确认 ")}{scan.unknown}<br/>{t("最近检查：")}{stamp(scan.finished_at||scan.updated_at||scan.started_at)}</p>}
    {scan.message&&<p role="status" className="warning">{message(scan.message)}</p>}
  </section>
}

function LocationSettings({initial,busy,action,close,changed}:{initial:Obj;busy:boolean;action:(p:string,b?:unknown,m?:string)=>Promise<any>;close:()=>void;changed:()=>Promise<void>}) {
  const [label,setLabel]=useState(initial.selected_label||'')
  const [radius,setRadius]=useState(String(initial.radius_miles))
  const [enabled,setEnabled]=useState(Boolean(initial.auto_restore))
  const [error,setError]=useState('')
  async function save(apply:boolean) {
    const value=Number(radius)
    if(!Number.isInteger(value)||value<1||value>100){setError(t("半径请输入 1–100 的整数"));return}
    setError('')
    const saved=await action('/collector/location-preferences',{selected_label:label.trim(),radius_miles:value,auto_restore:enabled},'PUT')
    if(saved){await changed();if(apply)await action('/collector/location');close()}
  }
  return <section className="panel location-preferences" aria-label={t("位置偏好")}><div className="panel-title"><div><h2>{t("位置偏好")}</h2><p>{t("偏好保存在本机，暂停或重启不会丢失。Facebook 登录失效时，需要先完成登录。")}</p></div><button onClick={close}>{t("收起")}</button></div>
    <div className="location-fields"><label>{t("中心邮编")}<input value={initial.postal_code} readOnly/><small>{t("中心邮编与坐标在设置中修改")}</small></label><label>{t("搜索半径（miles）")}<input type="number" min="1" max="100" step="1" value={radius} onChange={e=>setRadius(e.target.value)}/></label><label>{t("已记住的地区名（可选）")}<input value={label} maxLength={150} onChange={e=>setLabel(e.target.value)} placeholder={t("留空时按邮编自动识别")}/></label></div>
    <label className="checkbox"><input type="checkbox" checked={enabled} onChange={e=>setEnabled(e.target.checked)}/>{t("启动或恢复时，自动填写并核对保存的位置与半径")}</label>
    <p className="muted">{t("地区名用于匹配 Facebook 显示的位置；只有自己核对过邮编时才手动修改。删除记忆会清除地点匹配记录并关闭自动恢复，搜索配置仍保留。")}</p>
    {error&&<p role="alert" className="warning">{error}</p>}
    <div className="button-row"><button disabled={busy} className="primary" onClick={()=>void save(true)}>{t("保存并应用")}</button><button disabled={busy} onClick={()=>void save(false)}>{t("仅保存")}</button><button disabled={busy} onClick={async()=>{const d=await action('/collector/location-preferences',undefined,'DELETE');if(d)close()}}>{t("删除位置记忆")}</button></div>
  </section>
}

function Detail({item,close,action,decision,setItem}:{item:Listing;close:()=>void;action:(p:string,b?:unknown,m?:string)=>Promise<any>;decision:(i:Listing,v:string)=>Promise<void>;setItem:(i:Listing)=>void}) {
  const [form,setForm]=useState(JSON.stringify(item.overrides,null,2))
  const [history,setHistory]=useState<Obj|null>(null)
  const [formError,setFormError]=useState('')
  const [baseline,setBaseline]=useState('')
  const drawerRef = useRef<HTMLElement>(null)
  const [partPrices,setPartPrices]=useState<Record<string,string>>({})
  async function savePartPrice(part:Obj){
    const value=Number(partPrices[part.category+':'+part.model])
    if(!Number.isFinite(value)||value<=0){setFormError(t("请输入大于 0 的二手基准价"));return}
    const saved=await action('/prices/import',{references:[{category:part.category,model:part.model,low:value,mid:value,high:value,currency:'USD',source:t("用户本地二手价格基准"),source_url:'http://127.0.0.1:8765/api/prices',price_kind:'manual',market:'local',confidence:'manual',notes:t("用户设定的单个零件二手基准，并非核实成交；自动采集不覆盖。")}]})
    if(saved){setFormError('');setItem(await api('/listings/'+item.id))}
  }
  const v=item.valuation,r=v.reference
  useEffect(()=>{
    let active=true
    const timer=setInterval(()=>{void api('/listings/'+item.id).then(updated=>{if(active)setItem(updated)}).catch(()=>{})},3000)
    return()=>{active=false;clearInterval(timer)}
  },[item.id,setItem])
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null
    const overflow=document.body.style.overflow
    document.body.style.overflow='hidden'
    const focusable=()=>Array.from(drawerRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input,select,textarea,summary')||[])
    focusable()[0]?.focus()
    const key=(e:KeyboardEvent)=>{
      if(e.key==='Escape')close()
      if(e.key==='Tab'){
        const nodes=focusable(),first=nodes[0],last=nodes[nodes.length-1]
        if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}
        else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}
      }
    }
    document.addEventListener('keydown',key)
    return()=>{document.removeEventListener('keydown',key);document.body.style.overflow=overflow;previous?.focus()}
  },[])
  return <div className="overlay" onClick={close}><section ref={drawerRef} className="drawer" role="dialog" aria-modal="true" aria-label={t("商品详情")} onClick={e=>e.stopPropagation()}><div className="drawer-header"><span>{categories()[item.category]}{t(" · 商品 ")}{item.id}</span><button onClick={close} aria-label={t("关闭详情")}>×</button></div><h2>{item.title}</h2>{item.availability_status==='sold'&&<p className="sold-badge">{t("已售出")}{item.review_decision==='keep'?t(" · 已保留"):''}</p>}<p>{item.location||t("地点未知")} · {message(v.distance?.method)}</p><div className="button-row"><a aria-disabled={isDemo} onClick={e=>{if(isDemo)e.preventDefault()}} className="primary link-button" href={item.url} target="_blank" rel="noreferrer">{t("打开原商品 ↗")}</a><button onClick={()=>void decision(item,'keep')}>{t("✓ 保留")}</button><button onClick={()=>void decision(item,'reject')}>{t("拒绝")}</button><button onClick={()=>void decision(item,'pending')}>{t("恢复待审核")}</button></div><dl className="details-numbers"><div><dt>{t("标价")}</dt><dd>{money(item.overrides.price??item.price)} <small>{v.price_type}</small></dd></div><div><dt>{r?.method==='components'?t("拆件基准合计"):v.point_based?t("基准转售价"):t("转售价粗估区间")}</dt><dd>{r?(v.point_based?money(v.resale_estimate):money(r.low)+' / '+money(r.mid)+' / '+money(r.high)):t("物品类别待确认")}</dd></div><div><dt>{v.point_based?t("预计利润"):t("保守利润")}</dt><dd>{money(v.expected_profit)}</dd></div><div><dt>{t("建议最高出价")}</dt><dd>{money(v.max_offer)}</dd></div></dl>{v.calculation&&<p className="muted">{t("利润计算：")}{money(v.calculation.resale)}{t(" − 买价 ")}{money(v.calculation.purchase)}{t(" − 费用与预留 ")}{money(v.calculation.deductions)} = {money(v.calculation.profit)}</p>}<h3>{t("卖家描述与风险")}</h3><button onClick={()=>void action('/collector/detail/'+item.id)}>{t("重新读取原商品描述")}</button><p className="description">{item.overrides.description||item.description||t("尚未可靠取得描述；目前仅按卡片信息评估。")}</p>{v.reasons?.map((x:string,i:number)=><p key={i} className="warning">• {message(x)}</p>)}{v.missing_costs?.length>0&&<p className="warning">{t("未配置成本：")}{v.missing_costs.join(', ')}{t("，当前暂按 0 计算，请在设置中补全。")}</p>}<h3>{t("价格交叉核对")}</h3><p>{v.price_verification?.status==="manual"?t("使用人工基准"):v.price_verification?.verified?t("已交叉核对"):t("价格仍待交叉核对")} · {message(v.price_verification?.notes)}</p><h3>{t("估价依据")}</h3><p>{methodNames()[r?.method]||t("待确认")}{t(" · 置信度 ")}{r?.confidence||t("未知")}<br/>{message(r?.notes)}</p>{r?.evidence?.map((e:Obj)=><div key={e.id} className="evidence"><a href={e.source_url} target="_blank" rel="noreferrer">{e.source} ↗</a><p>{e.model} · {money(e.mid)} · {e.price_kind} · {e.market}<br/>{t("数据日期 ")}{e.data_date||t("未公布")}{t(" · 读取 ")}{stamp(e.observed_at)}<br/>{message(e.notes)}</p></div>)}{v.parts?.length>0&&<><h3>{t("拆件基准价（按下列单价计算）")}</h3>{v.parts.map((p:Obj,i:number)=><div key={i}><p>{p.model} · {money(p.estimate.mid)} · {methodNames()[p.estimate.method]}</p><div className="button-row"><input aria-label={p.model+t(" 二手基准价")} type="number" min="1" value={partPrices[p.category+":"+p.model]||""} placeholder={String(Math.round(p.estimate.mid))} onChange={e=>setPartPrices({...partPrices,[p.category+":"+p.model]:e.target.value})}/><button onClick={()=>void savePartPrice(p)}>{t("保存此零件基准价")}</button></div></div>)}</>}<details><summary>{t("计算参数")}</summary><pre>{JSON.stringify({rule:v.rule_version,costs:v.costs,target_profit:v.target_profit,mode:v.mode},null,2)}</pre></details>{item.model&&<section className="panel"><h3>{item.model}{t(" 的二手基准价")}</h3><p>{t("按这个金额计算同型号商品的预计利润，人工基准优先于自动价格。")}</p><div className="button-row"><input aria-label={t("型号二手基准价")} type="number" min="1" step="1" value={baseline} onChange={e=>setBaseline(e.target.value)} placeholder={t("例如 1100")}/><button onClick={async()=>{const value=Number(baseline);if(!Number.isFinite(value)||value<=0){setFormError(t("请输入大于 0 的二手基准价"));return}const saved=await action('/prices/import',{references:[{category:item.category,model:item.model,low:value,mid:value,high:value,currency:'USD',source:t("用户本地二手价格基准"),source_url:'http://127.0.0.1:8765/api/prices',price_kind:'manual',market:'local',confidence:'manual',notes:t("用户在审核网页设置的型号二手基准，并非已核实成交记录；自动采集不会覆盖。")}]});if(saved){setFormError('');setBaseline('');setItem(await api('/listings/'+item.id))}}}>{t("保存基准价")}</button></div></section>}<h3>{t("人工修正")}</h3><p className="muted">{t("可设置 category、model、price、estimate_mid、latitude、longitude、title、description；填 null 可取消该项修正。")}</p><textarea aria-label={t("人工修正 JSON")} rows={7} value={form} onChange={e=>setForm(e.target.value)}/>{formError&&<p className="warning">{formError}</p>}<button onClick={async()=>{try{setFormError('');const d=await action('/listings/'+item.id+'/overrides',JSON.parse(form),'PUT');if(d)setItem(d)}catch(e){setFormError(String(e))}}}>{t("保存修正并重新估价")}</button><h3>{t("变化记录")}</h3><p>{t("首次发现 ")}{stamp(item.first_seen)}<br/>{t("最近发现 ")}{stamp(item.last_seen)}<br/>{t("详情更新 ")}{stamp(item.details_at)}<br/>{t("命中关键词 ")}{item.keywords?.join('、')||t("无")}</p><button onClick={()=>void api('/listings/'+item.id+'/history').then(setHistory)}>{t("加载审核与价格历史")}</button>{history&&<pre>{JSON.stringify(history,null,2)}</pre>}</section></div>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>)



