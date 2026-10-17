# KisanMandi

**Mandi price intelligence for Indian farmers — ingest, validate, forecast, advise.**

[![CI](https://github.com/YOUR-USERNAME/kisanmandi/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)
![Tests](https://img.shields.io/badge/tests-125%20passing-brightgreen)
![Coverage](https://img.shields.io/badge/coverage-91%25-brightgreen)
![Cost](https://img.shields.io/badge/infrastructure%20cost-%E2%82%B90%2Fmonth-success)
![License](https://img.shields.io/badge/license-MIT-blue)

---

## The problem

Every day, the Government of India publishes wholesale prices from thousands of
APMC mandis through [Agmarknet](https://agmarknet.gov.in) / [data.gov.in](https://data.gov.in).
The data is free and public. In practice, a farmer with a ₹6,000 phone cannot use
any of it.

The result is a real and measurable loss: crops get sold at the wrong mandi on the
wrong day, purely from lack of price visibility.

Meanwhile, the data itself is messy. Prices of zero, modal prices below the
minimum, dates in the future, duplicate rows, inconsistent place names. Load it
into a dashboard unchecked and you will confidently tell a farmer to sell at a
price that never existed. **Bad advice is worse than no advice.**

## What this project does

```
data.gov.in / Agmarknet  ──►  ingest (paginated, throttled, retrying)
                                  │
                                  ▼
                     immutable raw landing zone (dated, checksummed)
                                  │
                                  ▼
                        data-quality gate  ──►  quarantine + published report
                                  │
                                  ▼
                       PostgreSQL / SQLite (idempotent upserts)
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
          walk-forward backtest        advisory engine
          + baseline forecasting       (SELL / HOLD / TRANSPORT)
                    │                           │
                    └─────────────┬─────────────┘
                                  ▼
                     one sentence a farmer can act on
```

**The deliverable is a decision, not a chart:**

```
$ kisanmandi advise --commodity Tomato --district Kolar

========================================================================
Tomato at Kolar: HOLD 7 days. Expected about Rs 1872/quintal (+Rs 56).
Selling is always an option.
========================================================================

action            : HOLD
confidence        : high
model             : drift
backtest          : MAPE 0.0% vs naive 3.4% over 18 folds (skill +100.0%)

reasoning:
  1. Home mandi: Kolar with 45 daily observations.
  2. Backtest over 18 walk-forward folds picked 'drift' (MAPE 0.0% vs naive 3.4%, skill +100.0%).
  3. Forecast for Kolar in 7 days: Rs 1872 (now Rs 1816, change +56 / +3.1%).
  4. Best alternative mandi: Binny Mill (F&V), Bangalore at Rs 1764 — net -202/quintal
     after Rs 150 transport.
  5. DECISION: expected gain +3.1% clears the 3.0% hold threshold.
```

Every number in that reasoning is reproducible from the stored data. A farmer,
or a reviewer, can disagree with the *conclusion* while checking the *arithmetic* —
which is the only kind of advice worth giving.

---

## What makes this more than a CSV reader

| Concern | How it's handled |
|---|---|
| **Pagination** | The shared demo key caps responses at 10 records, so a full daily pull is ~1,700 requests. Correct paging with a stop condition on `total`. |
| **Rate limiting** | Self-imposed minimum interval between requests. Getting throttled is slower than being polite. |
| **Retries** | Exponential backoff with **full jitter**, honouring `Retry-After`. Retries 429/5xx; fails fast on 401/404 because a bad key is not transient. |
| **Idempotency** | Every observation carries a SHA-256 natural key with a unique constraint. Re-running today's ingest five times inserts zero duplicates. |
| **Replayability** | Raw payloads are landed, dated and checksummed *before* any transformation, so a validation bug can be fixed without re-hitting a rate-limited API. |
| **Data quality** | Blockers quarantine rows; warnings flag them. The report is a published artifact, not a debug log. |
| **Honest forecasting** | Walk-forward backtesting against a naive baseline, reporting **skill** — including when it's negative. |
| **Refusal** | Below 21 observations the engine returns `INSUFFICIENT_DATA` instead of guessing. |
| **Observability** | Every run is a row in `ingest_runs`; `/metrics` exposes row counts in Prometheus format. |

---

## Quickstart

Five commands. No API key needed to run the tests.

```bash
git clone https://github.com/YOUR-USERNAME/kisanmandi.git
cd kisanmandi
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

make test          # 125 tests, 91% coverage, no network calls
```

**New to this? Start with the setup guide for your platform:**

| Platform | Guide | Notes |
|---|---|---|
| **Ubuntu / WSL2** ⭐ | [LINUX-SETUP.md](LINUX-SETUP.md) | Recommended — `make` works, native Docker, systemd |
| **Windows** | [START-HERE.md](START-HERE.md) | Works, but you translate `make` into `python -m` commands |

To pull real data:

```bash
make env           # creates .env from the template
# edit .env and set DATA_GOV_API_KEY (free: https://data.gov.in/user/register)

make dry-run STATE=Karnataka     # fetch + validate, write nothing — safe first run
make ingest  STATE=Karnataka     # for real
make stats                       # row counts
make quality                     # regenerate docs/data-quality-report.md
make advise  COMMODITY=Tomato DISTRICT=Kolar
make serve                       # API docs at http://localhost:8000/docs
```

`make help` lists everything.

---

## Results

> **Fill this table in with your own numbers before submitting.** A README with
> real measured results is worth more than any amount of architecture diagrams.
> Placeholder values below are from a synthetic demo dataset, not from production.

| Metric | Value |
|---|---|
| Days of price history collected | _e.g. 180_ |
| Mandis covered | _e.g. 34_ |
| Observations stored | _e.g. 412,880_ |
| **Data-quality pass rate** | _e.g. 96.4%_ |
| Rows quarantined | _e.g. 14,873_ |
| Ingest p95 duration | _e.g. 41 s_ |
| Scheduled-run success rate | _e.g. 178/180 (98.9%)_ |
| Forecast skill vs naive baseline | _see `make models` — report it even if negative_ |
| **Infrastructure cost for the whole project** | **₹0** (see [COSTS.md](COSTS.md)) |

Run `make models` and paste the table here. **If no model beats the naive
baseline, say so.** "We measured it and it didn't help on this series" is a
finding. Quietly dropping the comparison is not.

---

## Project structure

```
kisanmandi/
├── src/kisanmandi/
│   ├── config.py              # every tunable, including cost-relevant ones
│   ├── pipeline.py            # fetch → land → validate → gate → store → report
│   ├── cli.py                 # the same code paths cron and CI call
│   ├── ingest/
│   │   ├── client.py          # pagination, throttling, backoff, Retry-After
│   │   ├── schema.py          # messy feed in, clean objects out
│   │   └── landing.py         # immutable dated raw zone + checksum manifests
│   ├── quality/checks.py      # blockers, warnings, and the published report
│   ├── forecast/baseline.py   # walk-forward backtest, skill vs naive
│   ├── advise/engine.py       # SELL / HOLD / TRANSPORT / refuse to guess
│   ├── storage/db.py          # idempotent upserts, quarantine, run history
│   └── api/main.py            # read-only HTTP API + /metrics
├── tests/                     # 125 tests, no network, 91% coverage
├── docs/
│   ├── 01-week-plan.md        # the 12-week plan
│   ├── 02-oracle-setup.md     # ₹0 deployment, step by step
│   └── data-quality-report.md # the published report
├── .github/workflows/
│   ├── ci.yml                 # test matrix, lint, security scan, image build
│   └── ingest.yml             # nightly scheduled ingest at 18:00 IST
├── Dockerfile                 # multi-stage, non-root, healthcheck
├── docker-compose.yml         # Postgres + API locally
└── Makefile                   # make help
```

---

## Forecasting honesty

The models are deliberately simple: `naive`, `seasonal_naive`, `moving_average`,
`drift`. There is no deep learning here, and that is a design decision, not a gap —
on a 45-point daily price series, an LSTM would fit noise and you could not prove
it hadn't.

What matters is the **backtesting discipline**: at each fold, the model only ever
sees data from before that fold. Then it is scored against the naive baseline.

```bash
$ make models COMMODITY=Tomato

Walk-forward backtest — Tomato (45 observations, horizon 7 days)

model                    MAE      RMSE     MAPE%    naive%     skill
--------------------------------------------------------------------
drift                   0.00      0.00      0.00      2.38    100.0%  <-- best
naive                  40.00     44.72      2.38      2.38      0.0%
moving_average         70.00     72.80      4.17      2.38    -75.5%
seasonal_naive         70.00     70.00      4.18      2.38    -76.0%
```

Note the honest result: on a smooth synthetic series, drift wins by a mile.
**On real mandi prices it will not look like this** — real prices are noisy and
often the best model barely beats naive. Report whichever happens.

`prophet` and `statsmodels` are commented out in `requirements.txt`. Add one in
week 5 **and re-run this table**. If it doesn't earn its keep, remove it and say why.

---

## Data source, ethics and rate limits

- Data: **Agmarknet** daily mandi prices via the
  [data.gov.in API](https://data.gov.in/catalog/current-daily-price-various-commodities-various-markets-mandi),
  resource id `9ef84268-d588-465a-a308-a864a43d0070`. Government of India, Government Open Data Licence — India.
- **Register your own free API key.** The shared demo key is not for production use.
- Be a polite client: keep the default 1-second minimum interval. You are sharing
  a public resource with every other developer in the country.
- This is **advisory only**. It does not replace a farmer's own judgement, a
  mandi's own rate board, or an agriculture extension officer. The advice text
  says so explicitly, and it should stay that way.
- No personal data is collected or stored. Farmer phone numbers, if you ever add
  SMS alerts, must **never** be committed to this repository.

---

## Limitations (read before trusting any number)

1. `TRANSPORT_COST_PER_QUANTUEL` defaults to **₹150/quintal**, which is a guess.
   Replace it with a real figure from a farmer or transporter and cite the source.
2. The series averages varieties and grades within a mandi on a given day. If
   `Tomato/Local` and `Tomato/Hybrid` diverge sharply, that averaging hides it.
3. `seasonal_naive` assumes a 7-day market cycle. Real mandi cycles differ by
   commodity and season.
4. The forecast horizon is 7 days. Over a longer horizon, confidence drops fast
   and the API does not currently widen its uncertainty — a known gap.
5. The API is read-only and unauthenticated. Fine for a demo; it would need
   auth and rate limiting before any public deployment.

---

## Week-by-week plan

See [docs/01-week-plan.md](docs/01-week-plan.md) for the 12-week build plan, and
[docs/02-oracle-setup.md](docs/02-oracle-setup.md) to deploy this on a
**permanently free** Oracle Cloud VM with 24 GB RAM.

## Cost

**₹0.** Every component runs on a free tier that does not expire.
Full ledger and the reasoning: [COSTS.md](COSTS.md).

## License

MIT — see [LICENSE](LICENSE). If you reuse this, keep the Agmarknet attribution
and keep the "advisory only" disclaimer.
