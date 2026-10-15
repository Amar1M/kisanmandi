# 12-week build plan

Assumes ~10–12 hours per week alongside coursework. Weeks 1–7 are mostly coding;
weeks 8–12 are mostly operations, measurement and writing.

**The rule for every week: finish with something that runs, not something that
is nearly finished.** A working half-feature beats a broken whole one.

---

| Week | Goal | Definition of done | Cost |
|---|---|---|---|
| **0** | Setup | Repo public, oracle VM requested, CI green, Student Pack claimed | ₹0 |
| **1** | Real data flowing | `make ingest STATE=Karnataka` writes real rows to SQLite | ₹0 |
| **2** | Talk to a farmer | `TRANSPORT_COST_PER_QUINTAL` replaced with a sourced number | ₹0 |
| **3** | Quality gate | Report generated from real data; ≥3 checks firing on real rows | ₹0 |
| **4** | Deploy | Ingest running nightly on Oracle VM via systemd timer | ₹0 |
| **5** | Real forecasting | Prophet/ARIMA added *and* backtested against the baselines | ₹0 |
| **6** | Containerise | `docker compose up` starts the full stack; image < 200 MB | ₹0 |
| **7** | Kubernetes | k3s on Oracle; Helm chart; CronJob replacing the systemd timer | ₹0 |
| **8** | Observability | Grafana dashboard + 3 alerts + SLOs defined | ₹0 |
| **9** | Deliberate failure | One outage caused on purpose, one blameless postmortem written | ₹0 |
| **10** | Farmer-facing | Kannada/English PWA + SMS alert path (Twilio free trial) | ₹0 |
| **11** | Hardening | Load tested at 50 concurrent; security scan clean; backups tested | ₹0 |
| **12** | Publication | Data-quality report published; README results table filled in | ₹0 |
| | | | **₹0 total** |

---

## Week 0 — Setup (do this in one evening)

```bash
# 1. Claim the Student Pack FIRST — free domain, Azure credit, Copilot, JetBrains
#    https://education.github.com/pack

# 2. Request the Oracle Always Free ARM instance NOW.
#    It often takes days to allocate. Start the clock early. See 02-oracle-setup.md

# 3. Create the public repo and push a green CI run on day one
gh repo create kisanmandi --public --source=. --push
```

**Done when:** `.github/workflows/ci.yml` shows a green check on `main`.
Starting your commit graph in week 0 matters — a 12-week history is itself evidence.

---

## Week 1 — Real data

```bash
make env                          # then add your free data.gov.in key
make dry-run STATE=Karnataka      # safe: fetches and validates, writes nothing
make ingest  STATE=Karnataka
make stats
```

**Done when:** `make stats` shows a non-zero `mandi_prices` count and the landing
zone contains dated `page-*.json` files with a manifest.

**Watch for:** the demo key caps you at 10 records. If `requests` is huge and
`records` small, your key isn't set — `make stats` warns about this.

---

## Week 2 — Talk to a human (the week most students skip)

You have a working pipeline and a number in your config that is a **guess**:
`TRANSPORT_COST_PER_QUANTUEL=150`.

Go get a real one. Options, in order of ease:

1. Your college's agriculture department or an NSS/NGO contact.
2. A local FPO (farmer producer organisation) or Raitha Samparka Kendra.
3. A transporter's rate card (₹/quintal/50 km, or ₹/km for a tempo).
4. A farmer's own estimate, clearly labelled as an estimate.

Then write it into `.env`, update the default in `config.py`, and add a line to
the README: *"Transport cost: ₹X/quintal, sourced from Y on Z date."*

**Done when:** your README cites a source for its weakest assumption. This is a
20-minute conversation that improves the project more than a week of coding.

---

## Week 3 — Data quality

Run against real data and inspect what breaks:

```bash
make quality        # writes docs/data-quality-report.md
```

You should expect real hits. Likely findings:

- `stale_arrival_date` warnings (many mandis report late)
- `implausible_price` blockers on unusual commodities (saffron? areca nut?)
- `outlier_price` warnings during genuine price spikes

**Tune the thresholds based on the real distribution** — don't leave the defaults
unexamined. If `MAX_PLAUSIBLE_PRICE=100000` never fires, either lower it or say
in the report that it never fired.

**Done when:** `docs/data-quality-report.md` is regenerated from real data and
committed. That file is one of your two publishable artifacts.

---

## Week 4 — Deploy to the free VM

Follow `docs/02-oracle-setup.md`. Use **systemd timers** this week, not
Kubernetes — get it running before you get it elegant.

```bash
sudo systemctl status kisanmandi-ingest.timer
journalctl -u kisanmandi-ingest -n 50
```

**Done when:** the nightly timer has fired once on its own, unattended, and you
have the log line to prove it.

---

## Week 5 — Real forecasting

Uncomment `prophet` or `statsmodels` in `requirements.txt`, add the model, and
**re-run the comparison table**:

```bash
make models COMMODITY=Tomato DISTRICT=Kolar
```

**Done when:** you can state, with numbers, whether the heavier model earned its
keep. Be ready for the answer to be "no." That is a legitimate, reportable finding —
and it's more interesting than a suspiciously perfect result.

---

## Week 6 — Containerise

```bash
docker compose up -d
docker images kisanmandi:local      # check the size
```

Reduce the image: multi-stage build, `python:3.12-slim`, no build tools in the
final layer, non-root user. Record before/after sizes.

**Done when:** `docker compose up` brings up Postgres + API from a clean clone, and
`docker run --rm kisanmandi:local kisanmandi --version` works.

---

## Week 7 — Kubernetes on the free VM

```bash
curl -sfL https://get.k3s.io | sh -
helm install kisanmandi ./deploy/helm
kubectl create job --from=cronjob/kisanmandi-ingest manual-run-1
```

Replace the systemd timer with a k8s `CronJob`. Write a short
`docs/decisions.md` entry: *why k3s, why not Docker Compose, what the CronJob
gives you that a timer didn't.*

**Done when:** a CronJob has completed successfully and `kubectl get cronjob` shows
the schedule.

---

## Week 8 — Observability and SLOs

Define three SLIs and be honest about the targets:

| SLI | Target | Why |
|---|---|---|
| Nightly ingest success rate | ≥ 98% over 30 days | Feeds everything else |
| Ingest p95 duration | < 120 s | Detects upstream slowdowns |
| Data freshness | < 26 hours since last observation | A stale price is a wrong price |

Add Prometheus + Grafana on the VM (or Grafana Cloud free tier), and set alerts
for: run failed, quarantine ratio > 10%, freshness breach.

**Done when:** you can answer "is it healthy?" from a dashboard rather than by
reading logs.

---

## Week 9 — Break it on purpose

This is the strongest maturity signal in the whole project. Pick one:

- Stop Postgres mid-ingest.
- Set the API key to garbage and watch it fail fast (not retry 5 times).
- Fill the disk to 100% and see what happens to the landing zone.
- Corrupt a landed page and run `make verify-landing`.

Then write `docs/postmortems/001-<what-happened>.md`:

```
# Postmortem: ingest failed for 3 nights
## Impact
## Timeline (UTC)
## Root cause
## What went well / badly
## Action items (with owners and dates)
```

**Done when:** the postmortem exists, is blameless, and names a fix you actually made.

---

## Week 10 — Farmer-facing

Keep it minimal — the point is that the last mile exists, not that it is beautiful.

- A one-page PWA showing: today's price, the advice headline, and a 7-day trend.
- Works offline-first (service worker), readable on a small screen.
- Kannada + English.
- Optional SMS path via Twilio's free trial or an SMS gateway sandbox.

**Done when:** someone who has never seen the project can read the advice on a
phone in under 10 seconds.

---

## Week 11 — Hardening

- `pip-audit` and `gitleaks` clean; remove any `continue-on-error` from CI.
- Load test the API (50 concurrent, `k6` or `locust`) — record p50/p95/p99.
- **Actually restore a database backup** and time it. Write the RTO down.
- Run the weekly resource audit; confirm nothing is accruing cost.

**Done when:** you have a restore time in minutes, measured, not estimated.

---

## Week 12 — Publication

1. Fill the results table in the README with real numbers.
2. Commit `docs/data-quality-report.md` regenerated from a full month of data.
3. Write the one-page summary for a non-engineer: problem → approach → result → impact.
4. Record a 3-minute demo video.
5. Post the summary to a local agri-tech or DevOps community for feedback.

**Done when:** a stranger can clone the repo, run `make test`, and understand the
project in ten minutes.

---

## Weekly habits (every single week)

| Habit | Time | Why |
|---|---|---|
| Run `make check` before every push | 1 min | Green CI on `main` is non-negotiable |
| Update the README results table | 5 min | Numbers, not adjectives |
| Log spend in `COSTS.md` | 2 min | Should stay ₹0 |
| Resource audit on Oracle | 3 min | Catch an accidental charge early |
| Commit daily | — | A 12-week graph tells a story |

---

## What "done" looks like at the end

- [ ] Nightly ingest has run ≥ 30 consecutive times, unattended
- [ ] ≥ 90 days of clean price history collected
- [ ] Data-quality report published and regenerated from real data
- [ ] Forecast skill vs naive baseline measured and reported honestly
- [ ] One postmortem, from a failure you caused deliberately
- [ ] Backup restore tested, with a measured RTO
- [ ] `make test` green, coverage ≥ 85%
- [ ] Security scans clean, no `continue-on-error` left in CI
- [ ] **Total spend: ₹0, with a billing screenshot to prove it**
