# DAY 1 — start here

You're going to have real government data in your database tonight. Roughly
90 minutes of work. Nothing here costs money.

Tick the boxes as you go. **Do step 1 and step 2 today even if you do nothing
else** — both have waiting periods you can't shortcut later.

---

## ✅ Step 1 — Claim the GitHub Student Pack (5 minutes)

<https://education.github.com/pack>

Verify with your college email, then claim:

| Offer | Why you want it now |
|---|---|
| **Free domain** (Namecheap `.me` / Name.com / `.TECH`) | Your demo needs a URL. Costs ₹0 instead of ₹1,000. |
| **GitHub Pro + Copilot** | Copilot writes your tests and docstrings |
| **JetBrains IDEs** | Free PyCharm Professional for 12 months |

**Why today:** verification can take a day or two. You don't want to discover
that while trying to record your demo.

---

## ✅ Step 2 — Request the Oracle VM (10 minutes, *then it waits*)

Follow [docs/02-oracle-setup.md](docs/02-oracle-setup.md).

**The catch:** ARM instances regularly return **"Out of capacity."** It can take
**days or weeks** on the free tier. You are doing this on day 1 specifically so
it's ready in week 4.

If it fails, try in this order:

1. `availability_domain_index = 1`, then `2` (change in `terraform.tfvars`)
2. A different region — `ap-singapore-1` and `eu-frankfurt-1` are often freer
3. Upgrade to **Pay As You Go**. Always Free resources stay ₹0, but you draw from
   a much larger pool. Allocation reportedly drops to ~3 days.

> ⚠️ **If you choose option 3, set a billing alarm FIRST.**
> Cost Management → Budgets → create a budget of ₹100 with an alert at 1%.
> A NAT Gateway alone is ~₹3,100/month — more than your entire project budget.

---

## ✅ Step 3 — Get your free data.gov.in API key (5 minutes)

<https://data.gov.in/user/register>

**Do not skip this.** Without a personal key you fall back to the shared demo key,
which caps every response at **10 records**. A normal daily pull becomes ~1,700
requests instead of ~16. You will get throttled and your ingest will crawl.

Copy the key — you'll paste it in step 5.

---

## ✅ Step 4 — Get the project running locally (30 minutes)

```bash
git clone https://github.com/Amar1M/kisanmandi.git
cd kisanmandi

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

**First milestone — does it work with zero setup?**

```bash
make test
```

Expected: `125 passed in ~1.2 seconds`

If that's green, you have a working project with **no API key, no network, and
no database.** That's the point of the test suite — it must always be runnable.

```bash
make help          # see every available command
```

---

## ✅ Step 5 — Pull real government data (15 minutes)

```bash
make env
```

Now edit `.env` and paste your key:

```
DATA_GOV_API_KEY=paste-your-key-here
```

Then lock it down — this file holds a credential:

```bash
chmod 600 .env          # Linux/macOS
```

**Always dry-run first.** It fetches and validates but writes nothing:

```bash
make dry-run STATE=Karnataka
```

Look at the output: `requests`, `pages`, `records`. If `requests` is huge and
`records` is small, your key isn't being read.

**Now for real:**

```bash
make ingest STATE=Karnataka
make stats
```

**🎯 Milestone reached: real Government of India data is in your database.**

Check the raw data was archived too — this is the part that saves you later:

```bash
ls -R data/landing/ | head -20
cat data/landing/manifests/source=agmarknet/*/manifest.json | head -20
```

---

## ✅ Step 6 — Start your commit graph today (5 minutes)

A 12-week commit history is itself evidence of work. Don't lose week 1.

```bash
git checkout -b setup
git add .env.example .gitignore Makefile README.md COSTS.md LICENSE \
        src tests docs deploy pyproject.toml requirements.txt \
        Dockerfile docker-compose.yml .github
git commit -m "Initial KisanMandi scaffold

- Agmarknet ingest with pagination, throttling and jittered backoff
- Data-quality gate with quarantine + publishable report
- Walk-forward backtesting with skill vs naive baseline
- Advisory engine that refuses to guess below 21 observations
- 125 tests, 91% coverage, no network required to run them

Cost: Rs 0. See COSTS.md."
git push -u origin setup
```

Then open a pull request on GitHub. Even a self-reviewed PR with a checklist
reads as professional practice — and it means your CI runs on the PR, not just
on `main`.

**Confirm the green tick appears** on the PR. If CI fails, fix it today. A red
build left for a week is how pipelines get abandoned.

---

## ✅ Step 7 — Prove it costs nothing (5 minutes)

Before you leave it running:

- [ ] **Oracle**: Cost Management → Budgets → budget of ₹100, alert at 1%
- [ ] **Oracle**: Cost Analysis reads **₹0.00** — screenshot it
- [ ] **GitHub**: confirm the repo is **public** (private repos burn your free minutes)
- [ ] **Cloudflare**: R2 bucket created, 10 GB free, zero egress

**Screenshot the ₹0.00 billing page.** Put it in your report. "It cost ₹0, and
here's the proof" is a stronger claim than "it cost ₹0."

---

## Your first week after this

| Day | Task | Time |
|---|---|---|
| Day 2 | Run `make backfill DAYS=30 STATE=Karnataka` to build history | 20 min |
| Day 3 | `make quality` and read the report. Tune the thresholds. | 30 min |
| Day 4 | `make models COMMODITY=Tomato DISTRICT=Kolar` — paste the table in the README | 30 min |
| Day 5 | Talk to one farmer / FPO / transporter about transport cost | 20 min |
| Day 6 | Read `deploy/terraform/` and run `make tf-validate` | 30 min |
| Day 7 | Write your first `docs/decisions.md` entry | 20 min |

Full plan: [docs/01-week-plan.md](docs/01-week-plan.md)

---

## Common Day-1 problems

| Symptom | Cause | Fix |
|---|---|---|
| `make test` fails on import | venv not activated | `source .venv/bin/activate` |
| `records: 10` in every response | Using the demo key | Set `DATA_GOV_API_KEY` in `.env` |
| `records: 0` with `status: ok` | Filters too narrow | Drop `--state`, try nationwide |
| `requests` high, slow run | Demo key paginating 10 at a time | Your key isn't being read — check `.env` |
| `ModuleNotFoundError: kisanmandi` | Not installed | `pip install -e .` |
| Terraform `Out of capacity` | ARM free-tier demand | See step 2 |
| Ingest succeeds but `make advise` says `INSUFFICIENT_DATA` | Fewer than 21 days of history | Run `make backfill DAYS=30` |

---

## The one thing that matters most this week

**Step 5, run against real data, is the project becoming real.** Everything before
it is setup and everything after it is refinement.

If you only get one thing done: get real Agmarknet rows into your database tonight,
then tell a friend the number of records. It's a genuinely satisfying milestone —
that's your own country's agricultural economy, in your database, and you built
the thing that reads it.
