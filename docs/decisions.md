# Architecture decision records

One short entry each time you make a decision you'd have to defend. Written as
"we chose X over Y because Z" — not as a description of what you built.

**Why this file matters more than it looks.** An examiner will ask "why did you
do it this way?" A README tells them what; this tells them you thought about it.
Fill it in as you go — reconstructing it in week 12 is painful and reads as
retrofit.

Format: Context → Decision → Consequences (including the bad ones).

---

## ADR-001: SQLite locally, PostgreSQL in production

**Date:** 2026-10-15 · **Status:** Accepted

**Context.** The project needs a database. Two candidates: SQLite (a file, zero
setup) or PostgreSQL (a server, needs installing).

**Decision.** SQLite by default via `DATABASE_URL`, PostgreSQL on the VM. One
`DATABASE_URL` env var switches between them because SQLAlchemy abstracts the
dialect.

**Consequences.**
- ✅ A grader can clone the repo and run the full test suite with no database install
- ✅ Local iteration is instant
- ⚠️ Divergence risk: SQLite and Postgres differ on types and concurrency. Tested
  against both in CI to catch this early.
- ⚠️ The `ON CONFLICT DO NOTHING` clause needed dialect-specific imports
  (`sqlalchemy.dialects.postgresql` vs `.sqlite`) — a real portability cost, found
  by tests.

---

## ADR-002: Land raw data before validating it

**Date:** 2026-10-15 · **Status:** Accepted

**Context.** The API returns messy rows. Two orders are possible: validate then
store the clean rows, or store everything raw then validate on read.

**Decision.** Write the untouched payload to a dated, Hive-partitioned landing zone
with a SHA-256 manifest **first**. Validate afterwards.

**Consequences.**
- ✅ **Replay.** Found a bug in validation? Fix the code, re-run over history. No
  re-fetching a rate-limited public API.
- ✅ Tamper evidence: the manifest proves the raw bytes are unchanged
  (`make verify-landing`).
- ✅ The `source=/ingest_date=` layout is exactly what Athena/Glue expect, so
  adding a query engine later is a config change, not a rewrite.
- ⚠️ Storage grows forever. Mitigated by R2's 10 GB free tier and lifecycle rules.
- ⚠️ Slightly more code than "parse and insert."

---

## ADR-003: Quarantine bad rows instead of dropping or fixing them

**Date:** 2026-10-15 · **Status:** Accepted

**Context.** Real Agmarknet data contains prices of zero, `max` below `min`, future
dates, and duplicates. Three options: drop silently, repair heuristically, or
isolate.

**Decision.** **Blockers** (structurally impossible) are written to a
`quarantined_prices` table and never reach the table that forecasts read.
**Warnings** (suspicious but usable) load with a flag. Both are counted in a
published report.

**Consequences.**
- ✅ A forecast can never be built on an impossible price.
- ✅ The quarantine table is *evidence* — it's what makes the published
  data-quality report a finding rather than an opinion.
- ✅ Repairing silently was rejected: guessing what a wrong price "should" have
  been is inventing data.
- ⚠️ Extra table and extra code path.
- ⚠️ Threshold choices are judgement calls. They're configurable, and the report
  states they're ours.

---

## ADR-004: Report skill against a naive baseline, including when it's negative

**Date:** 2026-10-15 · **Status:** Accepted

**Context.** Forecasting results are easy to dress up. A model can look impressive
while being worse than "tomorrow will be like today."

**Decision.** Every model is scored by walk-forward backtest against
`naive`, reported as a **skill score** (`1 - model_mape/baseline_mape`). A negative
skill is printed, not hidden.

**Consequences.**
- ✅ Impossible to accidentally mislead — and hard to mislead deliberately.
- ✅ Negative results become reportable findings rather than failures
  ("we measured it and it didn't help on this series").
- ⚠️ Less impressive-looking output than a bare RMSE number.
- ⚠️ Backtesting costs time on every `advise` call.

---

## ADR-005: Refuse to advise below 21 observations

**Date:** 2026-10-15 · **Status:** Accepted

**Context.** With 4 days of data, any model will produce a number. That number
would be noise, and a farmer might act on it.

**Decision.** Return `INSUFFICIENT_DATA` below `MIN_HISTORY_POINTS`. Still report
the current price; decline to give advice.

**Consequences.**
- ✅ The tool cannot give confident advice from insufficient evidence.
- ✅ "Refusing to guess is a feature" is a defensible design position.
- ⚠️ Early in the project it returns `INSUFFICIENT_DATA` constantly, which looks
  broken until backfill is done. Documented in DAY-1.md.

---

## ADR-006: Oracle Cloud Always Free over a paid VPS

**Date:** 2026-10-15 · **Status:** Accepted

**Context.** Budget is ₹2,000 **for the entire project**. A ₹500/month VPS would
consume 75% of it over 12 weeks.

**Decision.** Oracle Cloud Always Free: 4 ARM cores, 24 GB RAM, 200 GB storage,
10 TB/month egress, **no expiry**.

**Consequences.**
- ✅ ₹0, permanently. More RAM than the development laptop.
- ✅ Enough headroom for k3s + Postgres + Grafana in ~3.2 GB of 24 GB.
- ⚠️ **ARM (aarch64), not x86.** All container images must be multi-arch. Learned
  `docker buildx` as a result — a genuine skill bonus.
- ⚠️ "Out of capacity" is common; allocation can take weeks.
- ⚠️ Oracle may reclaim long-idle instances; the nightly timer keeps it active.

---

## ADR-007: Cloudflare R2 over AWS S3

**Date:** 2026-10-15 · **Status:** Accepted

**Context.** The landing zone grows forever. At 50 GB stored / 200 GB downloaded
per month: R2 is ₹72, S3 is ₹1,838 — because S3 charges ₹8.64/GB egress and R2
charges ₹0.

**Decision.** Cloudflare R2. Same S3-compatible API, so it's a one-line config change.

**Consequences.**
- ✅ A 25× cost reduction on a read-heavy workload. This decision alone is the
  difference between within-budget and 92% of budget gone.
- ✅ 10 GB free tier, zero egress.
- ⚠️ Vendor-specific: migrating away later means re-uploading. Acceptable — the
  API is S3-compatible, so the code doesn't change.

---

## ADR-008: No GPU, no deep learning

**Date:** 2026-10-15 · **Status:** Accepted

**Context.** "AI project" optics suggest adding an LSTM. The dataset is ~45 daily
observations per commodity per market.

**Decision.** Four simple models (`naive`, `seasonal_naive`, `moving_average`,
`drift`) with rigorous backtesting. No neural network.

**Consequences.**
- ✅ Runs on any CPU, including a laptop with no GPU — cost stays ₹0.
- ✅ 45 points cannot train a neural network without fitting noise, and the
  backtest would expose that anyway.
- ✅ **Honest and defensible in a viva:** "the data doesn't support a complex
  model, and we can prove it with the backtest."
- ⚠️ Less flashy to a non-technical audience. Mitigated by explaining the reasoning.
- 📌 Revisit in week 5: add Prophet, **backtest it, and remove it if it doesn't help.**

---

## Template for new entries

```markdown
## ADR-00N: <short title>

**Date:** YYYY-MM-DD · **Status:** Proposed | Accepted | Superseded by ADR-00M

**Context.** What problem forced a decision? What were the real constraints
(budget, time, skills, the free tiers available to you)?

**Decision.** What did you choose? One sentence, active voice.

**Consequences.**
- ✅ what got better
- ⚠️ what got worse, and how you mitigate it
```
