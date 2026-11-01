"""Exercise the built, isolated demo and capture reproducible screenshots.

Usage: python scripts/ui_smoke.py [--screenshots docs/screenshots]
Requires: python -m playwright install chromium
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def choose_language(page, label):
    page.locator('.language-trigger').click()
    page.get_by_role('menuitemradio', name=label, exact=True).click()
    expect(page.locator('.language-trigger')).to_have_attribute('aria-expanded', 'false')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--screenshots', default='test-results')
    args = parser.parse_args()
    destination = ROOT / args.screenshots
    destination.mkdir(parents=True, exist_ok=True)
    if not (ROOT / 'frontend/dist/index.html').exists():
        raise SystemExit('Run npm run build in frontend first.')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend/dist')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}/?demo=1'
    errors, api_requests = [], []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            # Chinese system locale and the previous auto-detected preference
            # must still start in English until an explicit choice is made.
            context = browser.new_context(viewport={'width': 1440, 'height': 1050}, locale='zh-CN', reduced_motion='reduce')
            context.add_init_script("localStorage.setItem('reclaim-radar.language', 'zh-CN')")
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: api_requests.append(request.url) if '/api/' in request.url else None)
            page.goto(url)
            expect(page.locator('.listing')).to_have_count(6)
            expect(page.locator('h1')).to_have_text('Review listings')
            expect(page.locator('html')).to_have_attribute('lang', 'en-US')
            trigger = page.locator('.language-trigger')
            expect(trigger).to_have_text('EN')
            expect(page.get_by_role('menu')).to_have_count(0)
            trigger.hover()
            expect(page.get_by_role('menu')).to_have_count(0)
            trigger.click()
            expect(page.get_by_role('menu')).to_be_visible()
            page.screenshot(path=str(destination / 'language-menu-en.png'), clip={'x': 1220, 'y': 0, 'width': 220, 'height': 210})
            page.keyboard.press('ArrowDown')
            expect(page.get_by_role('menuitemradio', name='中文', exact=True)).to_be_focused()
            page.keyboard.press('Escape')
            expect(trigger).to_be_focused()
            expect(page.get_by_role('menu')).to_have_count(0)
            trigger.click()
            page.locator('h1').click()
            expect(page.get_by_role('menu')).to_have_count(0)
            # Await local artwork before taking documentation screenshots.
            page.locator('.photo img').evaluate_all('(images) => Promise.all(images.map(image => image.decode()))')
            page.screenshot(path=str(destination / 'listings-en.png'), full_page=True)

            page.get_by_role('button', name='Location preferences', exact=True).click()
            expect(page.locator('.location-preferences')).to_be_visible()
            page.locator('.location-preferences').screenshot(path=str(destination / 'location-en.png'))
            page.locator('.location-preferences').get_by_role('button', name='Close', exact=True).click()

            page.get_by_role('button', name='Details ↗').first.click()
            expect(page.get_by_role('dialog')).to_be_visible()
            page.keyboard.press('Shift+Tab')
            assert page.locator('.drawer').evaluate('(el) => el.contains(document.activeElement)')
            page.screenshot(path=str(destination / 'details-en.png'), full_page=True)
            page.keyboard.press('Escape')
            expect(page.get_by_role('dialog')).to_have_count(0)
            expect(page.get_by_role('button', name='Details ↗').first).to_be_focused()

            page.get_by_role('textbox', name='Search listings').fill('RTX 3070')
            expect(page.locator('.listing')).to_have_count(1)
            page.get_by_role('textbox', name='Search listings').fill('no-matching-model')
            expect(page.get_by_role('heading', name='No matching listings')).to_be_visible()
            page.get_by_role('button', name='Clear filters', exact=True).click()
            expect(page.locator('.listing')).to_have_count(6)
            page.get_by_role('button', name='✓ Save', exact=True).first.click()
            expect(page.locator('.listing')).to_have_count(5)
            page.locator('.tabs button').filter(has_text='Saved').click()
            expect(page.locator('.listing')).to_have_count(1)
            page.get_by_role('button', name='Reject', exact=True).click()
            expect(page.locator('.listing')).to_have_count(0)
            page.locator('.tabs button').filter(has_text='Rejected').click()
            expect(page.locator('.listing')).to_have_count(1)

            page.get_by_role('button', name='Price library', exact=False).click()
            expect(page.locator('tbody tr')).to_have_count(6)
            page.screenshot(path=str(destination / 'prices-en.png'), full_page=True)
            page.get_by_role('textbox', name='Search price models').fill('5800X')
            expect(page.locator('tbody tr')).to_have_count(1)
            page.get_by_role('button', name='Settings', exact=False).click()
            expect(page.get_by_role('heading', name='Search and valuation settings')).to_be_visible()
            page.get_by_label('Target profit $', exact=True).fill('35')
            page.get_by_role('button', name='Save settings', exact=True).click()
            expect(page.locator('.alert[role=status]')).to_have_text(re.compile('Saved'))
            page.screenshot(path=str(destination / 'settings-en.png'), full_page=True)

            choose_language(page, '中文')
            expect(page.locator('h1')).to_have_text('设置')
            expect(page.locator('html')).to_have_attribute('lang', 'zh-CN')
            expect(trigger).to_have_text('中')
            page.screenshot(path=str(destination / 'settings-zh-CN.png'), full_page=True)
            page.reload()
            expect(page.locator('h1')).to_have_text('商品审核')
            expect(page.locator('.listing')).to_have_count(6)
            page.locator('.photo img').evaluate_all('(images) => Promise.all(images.map(image => image.decode()))')
            page.screenshot(path=str(destination / 'listings-zh-CN.png'), full_page=True)
            page.get_by_role('button', name='位置偏好 · 修改 / 删除', exact=True).click()
            page.locator('.location-preferences').screenshot(path=str(destination / 'location-zh-CN.png'))
            page.locator('.location-preferences').get_by_role('button', name='收起', exact=True).click()

            # Every working page must fit common narrow viewports in both languages.
            for language, label in [('en-US', 'English'), ('zh-CN', '中文')]:
                choose_language(page, label)
                for width in [390, 768, 1280]:
                    page.set_viewport_size({'width': width, 'height': 900})
                    for index in range(4):
                        page.locator('.sidebar nav button').nth(index).click()
                        expect(page.locator('h1')).to_be_visible()
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow: {language}, {width}, page {index}'
            page.set_viewport_size({'width': 390, 'height': 844})
            choose_language(page, 'English')
            page.locator('.sidebar nav button').first.click()
            expect(page.locator('.listing')).to_have_count(6)
            page.screenshot(path=str(destination / 'mobile-en.png'), full_page=True)
            # The round control remains small and sits at the top-right on mobile.
            page.evaluate('window.scrollTo(0, 0)')
            bounds = trigger.bounding_box()
            assert bounds and 30 <= bounds['width'] <= 36 and bounds['x'] > 330 and bounds['y'] < 30
            trigger.click()
            expect(page.get_by_role('menu')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.keyboard.press('Escape')
            assert not errors, errors
            assert not api_requests, f'Demo leaked API requests: {api_requests}'
            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(f'UI smoke passed: language persistence, filters, review decisions, settings, drawer focus, 24 responsive views, no API requests.\nScreenshots: {destination}')


if __name__ == '__main__':
    main()
