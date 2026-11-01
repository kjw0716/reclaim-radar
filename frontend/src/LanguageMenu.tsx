import { useEffect, useRef, useState } from 'react'
import { t, useLanguage, type Language } from './i18n'

/** A compact, click-to-open language menu with keyboard navigation. */
export function LanguageMenu() {
  const [language, setLanguage] = useLanguage()
  const [open, setOpen] = useState(false)
  const container = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const options = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    options.current?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus()
    const outside = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])

  function choose(value: Language) {
    setLanguage(value)
    setOpen(false)
    trigger.current?.focus()
  }

  return <div className="language-control" ref={container}
    onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false) }}
    onKeyDown={event => {
      if (event.key === 'Escape' && open) {
        event.preventDefault(); setOpen(false); trigger.current?.focus()
      }
    }}>
    <button className="language-trigger" ref={trigger} aria-label={t('Language / 语言')}
      title={t('Language / 语言')} aria-haspopup="menu" aria-expanded={open}
      aria-controls={open ? 'language-options' : undefined} onClick={() => setOpen(!open)}
      onKeyDown={event => { if (event.key === 'ArrowDown') { event.preventDefault(); setOpen(true) } }}>
      {language === 'en-US' ? 'EN' : '中'}
    </button>
    {open && <div id="language-options" className="language-options" role="menu"
      ref={options} aria-label={t('Language / 语言')}
      onKeyDown={event => {
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
        event.preventDefault()
        const buttons = Array.from(options.current?.querySelectorAll<HTMLButtonElement>('button') || [])
        const current = buttons.indexOf(document.activeElement as HTMLButtonElement)
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
          : (current + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length
        buttons[next]?.focus()
      }}>
      <button role="menuitemradio" aria-checked={language === 'en-US'} lang="en"
        onClick={() => choose('en-US')}>English <span aria-hidden="true">{language === 'en-US' ? '✓' : ''}</span></button>
      <button role="menuitemradio" aria-checked={language === 'zh-CN'} lang="zh-CN"
        onClick={() => choose('zh-CN')}>{t('中文')} <span aria-hidden="true">{language === 'zh-CN' ? '✓' : ''}</span></button>
    </div>}
  </div>
}
