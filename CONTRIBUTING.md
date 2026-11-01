# Contributing

Use Python 3.13+ and Node.js 22.12+ on Windows. Run `Install.cmd`, then `SelfTest.cmd` before sending a pull request. Keep dependency versions pinned in `requirements.lock.txt` and `frontend/package-lock.json`.

For UI changes, build the frontend and run `python scripts/ui_smoke.py` using the project virtual environment. Install test Chromium with `python -m playwright install chromium` first. Use the isolated `?demo=1` route for screenshots. Never include real seller information, account sessions or `.data/` contents in a pull request.

## Translations

UI strings use `t()` from `frontend/src/i18n.ts`. Chinese source strings are translation keys; English values live in `frontend/src/locales/en.ts`. Add matching placeholders such as `{0}` in both languages. Run `npm run check:i18n` in `frontend`. Application diagnostics use `message()`; seller text and source evidence must retain their original wording. Avoid translating API field names or identifiers.

## Behavior to preserve

- Review decisions survive re-import, re-estimation and restart.
- Sold status requires explicit evidence near the original listing title. Inaccessible or missing listings are not proof of a sale.
- Weak price evidence stays reviewable; do not silently treat it as a verified baseline.
- Do not automate messages, purchases, sign-in challenges or CAPTCHA solving.
- Tests use temporary databases and no live accounts. Keep the demo completely isolated from real API calls.
- Keep functional interfaces focused on controls, data and short actionable status.

Describe the problem, resulting behavior and checks in your pull request. Add meaningful regression coverage for changes to collection, pricing, persistence or location verification. Live Facebook behavior should be reported separately from fixture tests.

## Release

Update versions and `CHANGELOG.md`, run checks, refresh screenshots if necessary, then run `python scripts/package_release.py`. Review the resulting archive and publish it as a source release. Keep `LICENSE`, upstream attribution and GeoNames attribution. Runtime data and installed dependencies must never be included.
