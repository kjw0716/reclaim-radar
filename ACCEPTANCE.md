# Release validation

Version: 0.2.0. Local Windows validation: 2026-10-31 (America/Los_Angeles).

- 176 backend tests passed using temporary databases. Coverage includes review persistence, valuation, location restoration, sold-listing handling, configurable ZIP centers, invalidation of stale location evidence and production static-asset routing.
- TypeScript checks and Vite production build passed.
- Translation coverage passed: 316 UI strings, 377 dictionary entries, with matching interpolation placeholders.
- Chromium UI checks passed: English/Chinese switching and persistence, filtering and empty results, save/reject decisions, settings save, detail focus and Escape handling, and 24 page/language/viewport combinations without horizontal overflow.
- Follow-up UI verification passed with a Chinese browser locale and a legacy Chinese preference: the new preference defaults to English. The top-right 34px circle opens its menu only on activation, supports arrows/Escape, closes on outside click and remembers explicit language choices. Mobile placement was checked, and language/location guide screenshots were refreshed.
- Demo mode issued no `/api/` network requests during browser checks.
- English, Chinese, price-library, detail, settings and mobile screenshots were captured from the actual frontend using fictional demo data. Desktop and mobile images were visually reviewed for clipping and legibility.
- npm audit reported zero known vulnerabilities after updating Vite to 7.3.7.
- Python dependency resolution passed with `pip install --dry-run --ignore-installed -r requirements.lock.txt`.
- The source ZIP was extracted into a separate directory with no virtual environment or node_modules. Its own Install.ps1 completed successfully, installing dependencies and building the frontend. A temporary-database API check served the production page and demo assets and confirmed that a fresh install has no listings.

These results do not verify live Facebook sign-in, collection on arbitrary accounts or ZIP codes, future price-source availability, startup after a Windows reboot, or GitHub-hosted CI. The workflow is supplied for execution when the repository is pushed. No live account activity or production database modification was needed for these checks.

The backend test run currently emits one upstream Starlette TestClient deprecation warning about httpx. Tests still pass; no runtime failure was observed.

Run `SelfTest.cmd` and `python scripts/ui_smoke.py` to repeat the checks. Install test Chromium first as described in README. The source package is produced by `scripts/package_release.py` and excludes private runtime data.
