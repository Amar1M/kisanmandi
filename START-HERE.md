# START HERE — Day 1

**Goal for today: see `125 passed` in your terminal.**

That's it. One green line. Everything else follows from there.

> ## 🐧 Are you using Ubuntu / WSL2?
> **Use [LINUX-SETUP.md](LINUX-SETUP.md) instead of this file.** On Linux, every
> `make` command in the docs works as written, Docker runs natively, and systemd
> works — so there's no translation layer. This file is the Windows-native path.

Total time: **30–40 minutes.** Every command below is copy-paste ready.

---

# PART 0 — Check what you already have (2 minutes)

Open **PowerShell**. Press `Win + X`, then choose **Terminal** or **Windows PowerShell**.

Run these two commands:

```powershell
python --version
git --version
```

### What each result means

| Command | If you see a version number | If a version number is missing |
|---|---|---|
| `python --version` | ✅ Supported: 3.10 – 3.14 | Install it — step 0.1 |
| `git --version` | ✅ Any 2.x | Install it — step 0.2 |

> **Note:** if `python --version` opens the Microsoft Store, that's a Windows stub,
> not real Python. Install it properly below.

### ✅ Verified working configuration

This project has been tested on **Python 3.10, 3.11, 3.12, 3.13 and 3.14**.
CI runs all five versions on every push.

If your `python --version` says **3.14.x**, you are supported — no second Python
installation is needed.

### 0.1 — Install Python (only if missing)

```powershell
winget install Python.Python.3.12
```

**Then close PowerShell, open a new one, and check `python --version` again.**
A fresh terminal is required for the PATH change to take effect — this catches
almost everyone.

Manual alternative: <https://www.python.org/downloads/> → tick
**"Add python.exe to PATH"** on the first screen of the installer. Don't skip that tick.

### 0.2 — Install Git (only if missing)

```powershell
winget install Git.Git
```

Close and reopen PowerShell, then confirm `git --version`.

Git also gives you **Git Bash** — a Linux-style terminal you may prefer later.

---

# PART 1 — Get the project onto your laptop (3 minutes)

### 1.1 Download

Download **`kisanmandi.zip`** from the workspace (it's next to these files),
then extract it somewhere sensible — **not** the Downloads folder:

**Recommended location:** `C:\Users\Amarnath\projects\`

Avoid:
- ❌ Paths with spaces or non-English characters
- ❌ OneDrive-synced folders (they fight with git and slow down file watching)
- ❌ The Desktop (it's often OneDrive-synced)

### 1.2 Open a terminal in the project

```powershell
cd C:\Users\Amarnath\projects\kisanmandi
```

Confirm you're in the right place — this must list the project's files:

```powershell
dir
```

You should see `src`, `tests`, `docs`, `Makefile`, `README.md`, `COSTS.md`.

---

# PART 2 — Run it (10 minutes)

### 2.1 Create a virtual environment

A venv is a private Python for this project, so it can't break anything else on
your laptop.

```powershell
python -m venv .venv
```

Takes ~20 seconds. Nothing prints — that's normal and correct.

### 2.2 Activate it

```powershell
.\.venv\Scripts\Activate.ps1
```

Your prompt should now start with `(.venv)`.

**If you get a red error about "execution policies",** run this once and try again:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Say **Y** when prompted. This is a standard, safe setting — it allows scripts
*you* wrote or downloaded, and blocks unsigned remote scripts.

### 2.3 Install the project

```powershell
pip install -e ".[dev]"
```

Takes 1–3 minutes. Lots of output is normal.

**Including the quotes matters.** They're required in PowerShell.

### 2.4 🏆 The moment — run the tests

```powershell
python -m pytest -q
```

### Expected result:

```
125 passed in 1.24s
```

**That's it. You just ran a real project.** Those 125 tests check API pagination,
retry logic with jitter, data-quality gates, forecast backtesting, and
idempotency — all without touching the network or needing a database.

### 2.5 Look at what you built

```powershell
python -m kisanmandi.cli stats
```

You'll see the configuration, row counts (all zero for now), and a note about
the missing API key — which is exactly what we fix next.

---

# PART 3 — Start the things that have waiting periods (15 minutes)

Do these **today** because they take time to be approved or allocated. If you
leave them for week 4, they will block you.

### 3.1 Claim the GitHub Student Developer Pack ⏳ 1–2 days

<https://education.github.com/pack>

Sign in with GitHub, verify with your **college email address**.

Claim these four straight away:

| Offer | Why |
|---|---|
| **Free domain** (Namecheap `.me` / Name.com / `.TECH`) | Your demo needs a URL — ₹0 instead of ₹1,000 |
| **GitHub Pro + Copilot** | Free AI autocomplete while you code |
| **JetBrains IDEs** | Free PyCharm Professional |
| **Azure $100 credit** | Backup compute if Oracle is slow |

### 3.2 Request the Oracle Cloud free VM ⏳ days to weeks

Follow [docs/02-oracle-setup.md](docs/02-oracle-setup.md).

**The catch:** ARM instances frequently return **"Out of capacity."** Starting
now means it's ready when you need it in week 4.

If it fails: try `availability_domain_index = 1`, then `2`, then a different
region (`ap-singapore-1` or `eu-frankfurt-1`).

⚠️ **Before upgrading to Pay As You Go, set a billing alarm.** Cost Management →
Budgets → ₹100 budget with a 1% alert. A single NAT Gateway is ~₹3,100/month —
more than your entire project budget.

### 3.3 Get your free data.gov.in API key ⏳ instant

<https://data.gov.in/user/register>

**Do not skip this.** Without a personal key you're capped at **10 records per
request**, turning a normal daily pull into ~1,700 requests. You'll be throttled
and your ingest will crawl.

Copy the key somewhere safe — you'll paste it in Part 4.

---

# PART 4 — Pull real government data (10 minutes)

### 4.1 Create your config file

```powershell
copy .env.example .env
```

### 4.2 Open it and paste your key

```powershell
notepad .env
```

Find this line and paste your key after the `=`:

```
DATA_GOV_API_KEY=paste-your-key-here
```

Save and close Notepad.

### 4.3 Dry run first — always

This fetches and validates but **writes nothing**. Safe to run as many times as
you like.

```powershell
python -m kisanmandi.cli ingest --dry-run --state Karnataka
```

**Read the output.** Look at three numbers:
- `requests` — how many API calls it made
- `pages` — how many pages
- `records` — how many valid price rows it parsed

If `records` is small (like 10) and `requests` is large, your key isn't being
read. Check `.env` again.

### 4.4 Now for real

```powershell
python -m kisanmandi.cli ingest --state Karnataka
```

### 4.5 🎯 Check what you got

```powershell
python -m kisanmandi.cli stats
```

**`mandi_prices` should now be a real number.**

### 4.6 Look at the raw data you archived

```powershell
dir data\landing\raw\source=agmarknet\
```

You just did the thing that makes this a real data pipeline: **you saved the raw
government response before processing it.** If you find a bug in your validation
logic next week, you fix the code and re-run over stored history — you don't go
back and re-scrape a rate-limited public API for a month of data.

---

# PART 5 — Push to GitHub and start your commit graph (10 minutes)

A 12-week commit history is itself evidence of work. Start it today.

### 5.1 Create the repository

Go to <https://github.com/new>, name it **`kisanmandi`**, choose **Public**.

> **Public matters.** GitHub Actions gives unlimited free minutes on public repos.
> A private repo burns your 2,000 free minutes in about two weeks.

### 5.2 Push

```powershell
git remote set-url origin https://github.com/Amar1M/kisanmandi.git
git branch -M main
git push -u origin main
```

Replace `Amar1M` with your actual GitHub username.

If it asks for a password, use a **Personal Access Token** — not your account
password. Create one at: GitHub → Settings → Developer settings →
Personal access tokens → Tokens (classic) → scope `repo` + `workflow`.

### 5.3 Watch CI go green

Go to your repo on GitHub → **Actions** tab.

You should see the **CI** workflow running: tests on 4 Python versions, lint,
security scan, and a container image build.

**⏳ This is your first real CI/CD pipeline.** It takes 3–5 minutes the first
time. Wait for the green tick.

**If it's red, tell me the error and I'll fix it.** A red build left for a week is
how pipelines get abandoned.

---

# ✅ Day 1 checklist

Tick these off:

- [ ] `python -m pytest -q` → **125 passed**
- [ ] GitHub Student Pack submitted
- [ ] Oracle VM requested (even if it says "Out of capacity")
- [ ] `data.gov.in` API key obtained
- [ ] `python -m kisanmandi.cli ingest --state Karnataka` ran against real data
- [ ] `stats` shows real rows in `mandi_prices`
- [ ] Repo pushed to GitHub
- [ ] CI shows a green tick

---

# Windows notes

### You don't need `make`

All the docs use `make test`, but `make` isn't on Windows by default.
**Use the Python commands instead** — they do exactly the same thing:

| Docs say | On Windows, run |
|---|---|
| `make test` | `python -m pytest -q` |
| `make ingest` | `python -m kisanmandi.cli ingest` |
| `make stats` | `python -m kisanmandi.cli stats` |
| `make advise` | `python -m kisanmandi.cli advise --commodity Tomato` |
| `make quality` | `python -m kisanmandi.cli quality-report` |
| `make models` | `python -m kisanmandi.cli models --commodity Tomato` |

**Later (recommended, not today):** install **WSL2** — it gives you `make`, bash,
and Docker on Windows. You'll want it around week 6 when you containerise.

```powershell
wsl --install -d Ubuntu-24.04
```

Windows 11 **Home** supports WSL2 fine. It uses the Virtual Machine Platform
feature, not Hyper-V. Just reboot when it asks.

### Reopening the project tomorrow

The venv doesn't stay active between terminal sessions. Every new session:

```powershell
cd C:\Users\Amarnath\projects\kisanmandi
.\.venv\Scripts\Activate.ps1
```

You'll know it worked when your prompt starts with `(.venv)`.

---

# Common first-run errors

| Error | Cause | Fix |
|---|---|---|
| `python: command not found` / opens Store | Python not installed, or PATH not set | Reinstall with "Add to PATH" ticked, then **reopen terminal** |
| `...running scripts is disabled on this system` | PowerShell execution policy | `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| `No module named pytest` | venv not activated | `.\.venv\Scripts\Activate.ps1` |
| `No module named kisanmandi` | Package not installed | `pip install -e ".[dev]"` |
| `pip is not recognized` | venv not activated | Activate it (prompt should show `(.venv)`) |
| `records: 10` on every ingest | Using the demo API key | Set `DATA_GOV_API_KEY` in `.env` |
| `records: 0` but `status: ok` | Filters too narrow | Drop `--state`, try nationwide |
| Ingest is very slow | Demo key paginating 10 rows at a time | Your key isn't being read — check `.env` |
| `.\.venv\Scripts\Activate.ps1` not found | venv wasn't created | `python -m venv .venv` first |
| pip install fails on `psycopg` | Your Python is newer than the wheel exists for | Already fixed in the repo — `git pull` if you cloned before 15 Oct |
| `No module named fastapi` on first run | Dependencies not installed | `pip install -e ".[dev]"` |

---

# Tell me how it goes

**When `125 passed` appears on your screen, come back and say so.**

Then tell me which of these happened, and I'll help with whichever didn't:

1. Did `python -m pytest -q` pass?
2. Did CI go green on GitHub?
3. Did the ingest pull real Karnataka data — and roughly how many rows?

And if something broke, **paste the exact red error text.** I can usually fix it
in one reply.

---

# What happens next week

| Session | You'll do | Result |
|---|---|---|
| **Day 2** | Backfill 30 days of history | Enough data to forecast |
| **Day 3** | Read the data-quality report, tune thresholds | Your first real finding |
| **Day 5** | Talk to a farmer / transporter about transport cost | Your weakest assumption gets a real source |
| **Week 2** | Terraform the VM, install the systemd timer | It runs nightly without you |
| **Week 7** | k3s + Helm chart | Real orchestration |

Full plan: [docs/01-week-plan.md](docs/01-week-plan.md)

---

## Remember why you're doing this

The last line of `COSTS.md` says it best:

> **Total infrastructure cost: ₹0.** Not "cheap." Zero.

And by the end you'll be able to say, with a billing screenshot to prove it:

> *"I built a system that reads my country's public agricultural price data,
> tells farmers when to sell, runs unattended on free cloud infrastructure, and
> costs nothing to operate — and I can show you exactly how it works."*

That's a genuinely good thing to have built. Go get the 125.
