<div align="center">

<img src="frontend/public/favicon.svg" alt="Reclaim Radar icon" width="88">

# Reclaim Radar

**Find underpriced used PCs, GPUs and parts on Facebook Marketplace, see resale estimates with evidence, and decide what to flip, all on your own Windows PC.**

[![Checks](https://img.shields.io/github/actions/workflow/status/kjw0716/reclaim-radar/ci.yml?style=flat-square&label=checks)](https://github.com/kjw0716/reclaim-radar/actions/workflows/ci.yml)
[![License: AGPL-3.0](https://img.shields.io/github/license/kjw0716/reclaim-radar?style=flat-square)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/Python-3.13%2B-3776AB?style=flat-square&logo=python&logoColor=white)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](radar)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)](frontend)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white)](frontend)
[![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?style=flat-square&logo=windows&logoColor=white)](#quick-start-windows)
[![Stars](https://img.shields.io/github/stars/kjw0716/reclaim-radar?style=flat-square&color=yellow)](https://github.com/kjw0716/reclaim-radar/stargazers)

**English** | [简体中文](README.zh-CN.md)

<img src="docs/screenshots/listings-en.png" alt="English listing workspace">

<sub>Screenshots show fictional demo listings and illustrative prices, not live offers or verified market evidence. The original hardware artwork is included in this repository.</sub>

</div>

Built with React, TypeScript, FastAPI and SQLite, with English and Simplified Chinese interfaces. Reclaim Radar runs on your Windows computer. You sign in through a dedicated browser profile, review the evidence, and make the decision. It does not message sellers, bid or buy automatically.

## Contents

- [Features](#what-it-does)
- [Install and start](#quick-start-windows)
- [Try the demo](#try-the-interface)
- [Change language](#change-the-interface-language)
- [Choose your search area](#choose-your-search-area)
- [Search and review](#search-and-review-listings)
- [Estimates and daily jobs](#how-estimates-work)
- [Data, backup and troubleshooting](#data-limits-and-recovery)
- [Development](#development)

## What it does

- **Review hardware:** desktops, GPUs, CPUs, motherboards, RAM, storage, power supplies, cooling, cases and parts bundles. Mac and unrelated items are excluded.
- **Compare resale economics:** asking price, resale baseline, estimated profit, costs, risk reserve and suggested maximum offer.
- **Inspect evidence:** model references, source links, dates, confidence and separate sold/asking-price records. Weak evidence stays in a price-review queue.
- **Keep decisions:** save, reject or reopen listings; decisions persist in local SQLite across refreshes and restarts.
- **Manage collection:** configurable US ZIP center, coordinates, radius, keywords and price limits; saved location restoration; activity records and daily checks.
- **Work in either language:** an English default and a compact top-right language menu with a remembered explicit choice, keyboard-accessible controls and responsive layouts.

## Quick start (Windows)

Requirements:

- Windows 10 or 11, with a normal signed-in desktop session.
- [Python 3.13+](https://www.python.org/downloads/windows/) on PATH (enable **Add Python to PATH** during installation).
- [Node.js 22.12+](https://nodejs.org/en/download), including npm.
- Google Chrome or Microsoft Edge installed for live collection.
- Internet access for installation and external data. A Facebook account with Marketplace access is required for live collection.

1. Download **Code → Download ZIP**, or clone the repository. Extract it into a writable folder.
2. Double-click **Install.cmd**. It creates a project virtual environment, installs locked dependencies and builds the frontend. Administrator rights, WSL and Docker are not required.
3. Double-click **Start.cmd**. Open **[http://127.0.0.1:8765](http://127.0.0.1:8765)** if the browser does not open automatically.
4. The first launch opens in English. To switch, click the small **EN** circle at the top-right and choose **中文**. In **Settings**, set your US ZIP, matching center latitude/longitude, target profit and actual costs. The default example is ZIP **92121**, radius **20 miles**. Changing ZIP requires updating coordinates. Supply verified coordinates yourself; there is no automatic geocoding.
5. Select **Connect Facebook** and sign in inside the project browser. Complete any verification on Facebook, then select **Restore** to apply and verify your location. Use **Location preferences** to change the radius or location name.
6. Run a keyword search and review the results. Automatic collection starts after login and location verification when enabled in Settings.

Use **Stop.cmd** to stop the service. **EnableStartup.cmd** optionally starts it at Windows sign-in; **DisableStartup.cmd** removes that scheduled task. Installation does not enable startup.

To upgrade an existing installation: stop it, back up and preserve `.data/`, replace the source files, run **Install.cmd**, then **Start.cmd**. Restarting loads backend changes; a browser refresh alone does not.

Blank cost fields mean “not configured” and are temporarily treated as zero. Enter `0` explicitly for a genuine zero cost. Prices are USD, distances are miles, and scheduled jobs use `America/Los_Angeles`, including daylight saving time.

### Installation walkthrough

**1. Check prerequisites.** Open PowerShell and run:

```powershell
python --version
node --version
npm --version
```

Python must report 3.13 or newer; Node must report 22.12 or newer. If a command is missing, install the corresponding tool and open a new terminal. Python must be on PATH.

**2. Extract the project.** Use a writable local folder such as `C:\Tools\reclaim-radar`. Do not run scripts from inside the ZIP viewer or move launchers away from the other files. Keep `radar`, `frontend` and `scripts` together.

**3. Run installation.** Double-click `Install.cmd`, or use PowerShell to keep its output visible:

```powershell
Set-Location 'C:\Tools\reclaim-radar'
.\Install.cmd
```

The installer creates `.venv`, installs `requirements.lock.txt`, runs `npm ci` and builds `frontend/dist`. Wait for **Installation complete**. First installation needs internet access. Dependencies stay in the project directory.

**4. Start the app.** Double-click `Start.cmd`. It launches the background service and opens the browser. If an instance is already running, it reuses that instance. Keep the computer awake for scheduled collection.

**5. Complete setup.** Set your location and costs, connect Facebook, restore the location, and run one search. A fresh database is empty; README screenshots are demo data and are not imported into your real workspace.

### Choose the run mode

| Mode | Launch | Address | Use |
| --- | --- | --- | --- |
| Normal application | Install.cmd, then Start.cmd | http://127.0.0.1:8765 | Real collection, persistent reviews and backups |
| Isolated demo | Demo.cmd | http://127.0.0.1:5173/?demo=1 | Explore without a Facebook account |
| Frontend development | Backend running, then npm run dev in frontend | http://127.0.0.1:5173 | Edit the UI with live reload |

The deployment target is a Windows desktop. No domain, reverse proxy or cloud server is needed. GitHub shares the source. A static host can show the frontend demo, but cannot provide live collection, SQLite persistence or a signed-in browser.

### Stop, restart and automatic startup

- Run **Stop.cmd** to stop the service. Closing the website tab alone does not stop it.
- To restart, wait for Stop.cmd to finish, then run **Start.cmd**.
- After successful manual setup, **EnableStartup.cmd** optionally starts the app at Windows sign-in in the current user's interactive session.
- **DisableStartup.cmd** removes the startup task; use Stop.cmd separately to stop an already running service.
- After code changes, rebuild with Install.cmd and restart. Preserve `.data` to retain settings and reviews.

## Try the interface

Double-click **Demo.cmd**. Only Node.js is needed; it installs frontend dependencies on first use and opens the local demo. Stop it with **Ctrl+C** in its terminal.

Or run:

```powershell
cd frontend
npm ci
npm run demo
```

The demo uses `?demo=1` and keeps fictional data in memory. Explore filters, review decisions, settings and languages without a Facebook account. Reloading resets demo records; language preference remains. Live collection, imports, backups and other external operations are unavailable in demo mode. Demo requests never reach the backend or your real database.

![Chinese listing workspace](docs/screenshots/listings-zh-CN.png)

<details>
<summary>More screenshots: price library, details, settings and mobile</summary>

![Price library](docs/screenshots/prices-en.png)
![Listing details](docs/screenshots/details-en.png)
![Settings](docs/screenshots/settings-en.png)

<img src="docs/screenshots/mobile-en.png" width="360" alt="Mobile English listing workspace" />

</details>

## Change the interface language

The first launch defaults to **English**, even with a Chinese system/browser locale. This upgrade also starts with the new English-default preference instead of reusing the old automatically detected language.

1. Click the small circular **EN** button at the top-right.
2. Choose **English** or **中文** from the menu.
3. The menu closes and the interface changes immediately. In Chinese, the circle shows **中**.
4. The explicit choice is remembered for this browser and address. Another browser or origin has its own preference.

Options stay hidden until the button is clicked. Keyboard users can open it with Enter or Arrow Down, select using arrow keys and Enter, and close with Escape. App language does not change Facebook's language or translate seller descriptions.

<img src="docs/screenshots/language-menu-en.png" width="220" alt="Small EN circle and expanded English/Chinese menu" />

## Choose your search area

Set both the **center used to calculate distance** and the **location/radius applied to Facebook** before collecting.

### 1. Set ZIP and center coordinates

Open **Settings → Search center**.

| Field | Input | Fresh-install example |
| --- | --- | --- |
| Center ZIP code | Five-digit US ZIP, preserving any leading zero | `92121` |
| Latitude | Approximate north/south coordinate in that ZIP | `32.899` |
| Longitude | East/west coordinate; usually negative in the US | `-117.202` |

Use a trusted map or coordinate source to find an approximate public point within your ZIP. Enter **latitude, longitude** in that order. Do not swap them or omit the minus sign on western longitude. Your exact home address is unnecessary.

Replace the defaults with your verified values, then click **Save settings** at the top of the panel. A ZIP change with unchanged coordinates is rejected. Changing the center clears old location verification, but preserves saved/rejected decisions.

<img src="docs/screenshots/settings-en.png" width="900" alt="Settings with ZIP, coordinates, resale mode and costs" />

*Screenshot uses demo data. Apply your own location in normal mode.*

### 2. Set the radius

Go to **Listings → Location preferences** in the connection controls.

- **Search radius (miles):** a whole number from 1 to 100. Choose a practical pickup area; Facebook may offer only some radius values.
- **Saved location name (optional):** normally leave blank for ZIP-based detection. If entering it manually, use the Facebook place name you verified for that ZIP. A seller's city is not evidence of the search center.
- **Restore and verify saved location…:** enable to restore the location after startup or resuming.

ZIP is read-only in this panel. Change it with coordinates in Settings.

![Location preferences: ZIP, radius, saved place and restore controls](docs/screenshots/location-en.png)

### 3. Sign in and apply

1. Select **Connect Facebook** and sign in using the project browser.
2. Complete any Facebook verification yourself and open Marketplace.
3. Select **Save and apply** in Location preferences, or **Restore** after saving.
4. The app attempts to select the ZIP suggestion and radius, applies them and checks the visible search controls again.
5. Start searching when the collector shows **Ready**. If it shows **Verify location**, check the actual Facebook location and radius, correct preferences and retry.

**Save only** stores preferences without applying them. **Forget location** removes the saved place match, disables auto-restore and pauses collection, while retaining center/radius configuration. **Reset sign-in** creates a fresh browser profile and requires signing in again; use it for a stuck login, not routine location changes.

### 4. Read distance labels

| Label | Meaning | Next step |
| --- | --- | --- |
| Coordinate-based distance | Straight-line distance from your center | Check travel feasibility; it is not driving distance |
| Approximate / Verify | City representative point used | Confirm the seller's actual area |
| Range unverified | No reliable coordinates or place match | Review manually if otherwise interesting |
| Outside range | Reliable coordinates exceed your radius | Inspect Excluded if necessary |

City-name estimates currently cover California, Nevada and Arizona. Other US ZIPs can be configured, but listings without coordinates may remain unverified. The app does not automatically download a nationwide ZIP-coordinate database.

## Search and review listings

### First search

1. Select **Local PC / component resale** or **Online part-out resale** in Settings.
2. Enter pickup, repairs, supplies and time costs. For online sales, check shipping and fees too. Set the target profit and save.
3. Confirm that Facebook is connected and the collector is Ready.
4. **Run search** uses the current keyword. On an empty workspace, enter a keyword in the empty-state field and select **Search this keyword →**.
5. Follow collector status and **Activity**. The page periodically refreshes results.

**Search listings** filters records already collected; typing there does not launch a new Facebook search. Change recurring keywords under **Settings → Advanced configuration**, editing `search_groups` and preserving other fields:

```json
{
"search_groups": [
  {
    "category": "gpu",
    "keywords": ["graphics card", "RTX GPU"],
    "max_price": 300
  },
  {
    "category": "pc",
    "keywords": ["gaming PC", "desktop computer"],
    "max_price": 700
  }
]
}
```

This is one field of the full configuration, not a replacement JSON document. The minimum collection interval is 10 minutes. Disable automatic searches for manual use. **Pause** suspends collection while retaining location preferences.

### Review queues and filters

| Tab | Contents |
| --- | --- |
| To review | Pending candidates after screening |
| Price review | Relevant items needing better price evidence |
| Saved | Items you explicitly saved |
| Rejected | Items you explicitly rejected |
| Excluded | System-screened records: irrelevant, outside range or verified below-target items |
| All | All retained records across those groups |

Filter by title/specs, distance, sort order, price, profit and category. Categories are single-select by default; **Multi-select** permits several. **Clear filters** resets filter values after an empty result; select another tab separately to change the review queue.

### Inspect and decide

1. Compare **Asking price**, **Estimated resale**, **Expected profit** and **Max offer**.
2. Open **Details** for description, recognized parts, risks, distance basis and evidence.
3. Use **Open original listing** to inspect the item before arranging anything. Fictional demo listings do not have working seller links.
4. **Save** or **Reject** persists a decision in live mode. **Move to review** reopens it.
5. Correct misidentified models or prices using the documented manual override fields and **Save overrides and recalculate**. Use `null` to remove an override.

A manual model baseline affects other listings of the same model. Enter only a baseline you intend to use; it is not automatically a verified market sale.

![Listing details and review actions](docs/screenshots/details-en.png)

### Price library

Search a model or category, then expand **View basis** for source notes. **Refresh prices** updates available evidence; **Import full catalog** is a larger catalog operation. Use Activity for failures and queued tasks.

For evidence and actual-sale imports, expand the import section and follow the local API's Evidence/Sale schema. Preserve source URLs, dates, market and price basis. An asking price must not be labeled as a completed sale.

## How estimates work

Estimates prefer a manual model baseline, then available model evidence, comparable models, category references and finally labeled rule estimates. Fallback rules are **not live market prices**. Memory and storage account for capacity. Complete-system and component values are not added twice.

```text
Expected profit = resale baseline × (1 − channel fee)
                  − pickup / repairs / supplies / time / applicable shipping
                  − risk reserve − asking price

Maximum offer = max(0, net recovery value − target profit)
```

Sources include Second Hand Silicon, PCPrice.watch, Get PC Parts, public eBay sold searches when accessible, and user-entered evidence. Sources can be incomplete or blocked. Asking prices, sold references and manual baselines retain their own basis. Websites drawing on the same upstream market are not independent confirmations. Evidence does not guarantee a resale price.

Prices refresh daily at **07:00 Los Angeles time** while the service runs. Availability checks default to **09:00** and can be disabled or rescheduled. Missed daily jobs are attempted after startup. **Confirmed sold listings are deleted unless you saved them.** Saved sold listings remain marked as sold. Inaccessible, missing or pending listings are not automatically treated as sold. Existing rotating backups remain.

The research queue at `/api/research` supports optional external workflows. This repository **does not install a Codex account, AI subscription, or an 08:00 AI automation**. The base application does not require an AI API key.

## Data, limits and recovery

Private data lives under `.data/`: database, browser session, logs, screenshots and backups. Git and release archives exclude that directory. Keep it when upgrading; never upload it to GitHub or attach it to an issue. Language selection lives in browser local storage.

- The service binds to `127.0.0.1:8765` and rejects cross-site writes. This is a **local Windows app**, not a public multi-user server. GitHub hosts the source; GitHub Pages cannot run the Python backend or your Facebook browser session.
- Collection depends on Facebook's layout, account access and location behavior. Complete login and challenges yourself. Results are not exhaustive. Live collection on another account or ZIP is not guaranteed by automated tests.
- Configurable US ZIPs require matching coordinates. Offline city-name estimates currently cover **California, Nevada and Arizona**. Elsewhere, listings without coordinates stay range-unverified. City-center estimates cannot establish exact seller distances.
- Controls and common diagnostics are bilingual. Seller text, source evidence, raw JSON fields and unrecognized external errors retain their original wording.
- Native launch and browser collection are supported on Windows. The Node.js frontend demo can run elsewhere; macOS/Linux live collection is not supported.

Daily SQLite backups are in `.data/backups/`; the most recent 14 are retained. Stop the app before restoring:

```powershell
.\Stop.cmd
.\scripts\Restore.ps1 -BackupPath 'C:\path\to\backup.sqlite3'
.\Start.cmd
```

Restore validates the backup and saves the current database before replacing it. Do not copy a database while it is being written. See [security and privacy](SECURITY.md).

| Problem | Next step |
| --- | --- |
| python / npm not found | Install prerequisites, reopen the terminal, run Install.cmd again. |
| Port 8765 or demo port 5173 occupied | Stop the conflicting app or previous instance. Launchers do not kill unrelated processes. |
| Facebook asks to sign in | Complete it in the project browser, then select Restore. |
| Verification remains stuck | Use Reset sign-in for a fresh project profile; sign in again. |
| Location mismatch | Verify ZIP, coordinates, saved name and radius; select Restore. |
| Price source blocked | Review Activity; older evidence and labeled estimates remain. |
| No matching listings | Clear filters or inspect Price review / Excluded / All. |
| Startup fails | Check .data/logs/server.stderr.log; run SelfTest.cmd. |

## Development

```powershell
.\Install.cmd
.\SelfTest.cmd

# Backend, in a terminal (stop an existing instance first)
.\.venv\Scripts\python.exe -m radar

# Frontend, in a second terminal
cd frontend
npm run dev
```

Vite runs on `127.0.0.1:5173`, proxying `/api` to 8765. FastAPI serves `frontend/dist` in production; normal use does not require Vite. API schemas: **[http://127.0.0.1:8765/docs](http://127.0.0.1:8765/docs)**. `config.example.json` documents the settings shape; active settings live in SQLite, edited through the UI or API.

```powershell
# Isolated browser checks and screenshots; no live account
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe scripts/ui_smoke.py

# Refresh documentation screenshots after a frontend build
.\.venv\Scripts\python.exe scripts/ui_smoke.py --screenshots docs/screenshots

# Create an allowlisted source ZIP
python scripts/package_release.py
```

The ZIP is `release/reclaim-radar-0.2.0-source.zip`. It contains source, lockfiles, launchers, documentation, screenshots and licenses. It excludes Python, Node, dependencies and personal runtime data; recipients follow Quick start. GitHub Actions runs backend tests, translation checks, the production build and isolated browser checks on Windows. See [validation](ACCEPTANCE.md), [contributing](CONTRIBUTING.md) and [changes](CHANGELOG.md).

```text
radar/                 API, collection, estimates, SQLite and schedules
frontend/src/          React UI, translations and demo fixtures
frontend/public/       Favicon and original demo illustrations
scripts/               Install, launch, backup, checks and packaging
tests/                 Regression tests using temporary databases
docs/screenshots/      Demo screenshots
third_party/aimm/      Upstream source and attribution
.github/workflows/     Windows CI
```

## License and acknowledgments

[AGPL-3.0](LICENSE). The Marketplace card parser credits [BoPeng/ai-marketplace-monitor](https://github.com/BoPeng/ai-marketplace-monitor); pinned upstream source and license are in [third_party/aimm](third_party/aimm/UPSTREAM.txt). GeoNames city data uses CC BY 4.0; see [data attribution](radar/data/README.md). This independent project is not affiliated with Facebook, Meta or the price-source websites.

---

<div align="center">

If Reclaim Radar helps you spot a good deal, a [star](https://github.com/kjw0716/reclaim-radar/stargazers) helps other flippers find it.

</div>
