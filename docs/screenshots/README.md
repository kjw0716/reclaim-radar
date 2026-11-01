# Screenshots

These PNGs were captured from the actual production frontend with `?demo=1`, using fictional listings and illustrative prices. They contain no real sellers, account data or browser sessions. SVG hardware illustrations are original assets in `frontend/public/demo/`.

Rebuild and reproduce from the repository root:

```powershell
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe scripts/ui_smoke.py --screenshots docs/screenshots
```

The script serves only the built frontend on an ephemeral loopback port, runs browser checks, captures desktop and mobile pages, then shuts down the server. It asserts that demo mode makes no `/api/` network requests.

`language-menu-en.png` shows the expanded top-right language control. `location-en.png` and `location-zh-CN.png` show the actual location-preferences panel. `settings-en.png` and `settings-zh-CN.png` support the ZIP/coordinate and cost setup instructions. All documentation screenshots are regenerated together so they match the current interface.
