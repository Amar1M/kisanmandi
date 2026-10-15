# Publishing the Mandi Price Data Quality Report

**This is the part of the project that gives something back.**

Everything else here — the pipeline, the forecasting, the API — is engineering
practice. Valuable to you, invisible to everyone else. This is the piece that is
useful to people who are not you.

---

## Why it matters

Nobody publishes data-quality measurements for Indian agricultural price data.
Not the aggregators, not the researchers, not the newsrooms that report on
mandi prices every day.

The questions this report answers are ones people genuinely have:

- **How often does a state's price feed go stale?** If Karnataka reports within a
  day but another state lags four days behind, that changes how much you should
  trust cross-state comparisons.
- **Which commodities have price ranges that don't make sense?** `min > modal > max`
  is structurally impossible, and it happens.
- **How do outlier rates vary by season?** Genuine price spikes and data errors
  look identical in a single day's snapshot. Over months, they separate.
- **Are duplicate rows inflating reported volumes?** If the same mandi publishes
  the same row three times, any count-based analysis is wrong.

A journalist writing "tomato prices doubled this week" would be better off knowing
the pass rate for tomato rows that week. A researcher building a price index needs
to know what they're excluding. **You will be the only person with this data.**

---

## Generating it

```bash
# From your production database, over the full history
make quality

# Or scoped, for a specific question
python -m kisanmandi.cli quality-report --commodity Tomato --out docs/tomato-quality.md
python -m kisanmandi.cli quality-report --district Kolar --out docs/kolar-quality.md
```

The command writes two files, and both matter:

| File | Audience | Purpose |
|---|---|---|
| `quality-<date>.json` | machines | Feed it into Grafana, alert on the trend |
| `quality-<date>.md` | humans | Commit it, link it, send it to people |

A rolling `quality-latest.json` / `.md` pair is also written so the API and your
README always have a stable path to current state.

---

## What to publish, and where

### 1. In your repo
Commit `docs/data-quality-report.md` and regenerate it monthly (or on every
release). The commit history showing the pass rate *changing* over time is more
interesting than any single snapshot.

### 2. As a scheduled artifact
The nightly workflow already uploads the report as a 90-day artifact. Extend that:
publish the trend, not just the latest number.

### 3. As a post
Write it up with the narrative structure below and post it somewhere it will be
read — a data-journalism forum, an agri-tech community, a college symposium, a
substack. The measurement is the contribution; the writing is how it travels.

---

## Narrative structure for the write-up

Structure it as a finding, not as a feature announcement.

```markdown
# What 6 months of Agmarknet price data actually looks like

## The headline
Across N observations from M mandis over D days, X% passed every structural
check. The remaining Y% were not random — they clustered in specific states and
commodities.

## Method
- Source, resource id, date range, observation count
- The exact checks run, with thresholds (link to quality/checks.py)
- What "blocker" vs "warning" means
- How to reproduce: one command

## What we found
1. Staleness is uneven: <state> has a median reporting lag of N days vs M elsewhere
2. N% of rows had impossible price orderings (min > modal > max)
3. Duplicates cluster around <commodity> around <festival/harvest>
4. Outlier rate peaks in <month> — genuine spikes or errors?

## What we're not claiming
- Not claiming any specific figure is wrong; only that it failed a structural check
- Thresholds are our choices; changing them changes the numbers. Here they are.
- Coverage is limited to <scope>

## Why this matters
<the practical implication for anyone analysing this data>

## Reproduce it
<commands, commit hash, date>
```

**The "what we're not claiming" section is what makes it credible.** Without it,
the report reads as criticism of the data source. With it, it reads as measurement.

---

## Rules for publishing this

1. **Never say the government's data is "wrong."** Say a row *failed a structural
   check you defined*. Those are different claims, and the second is defensible.
2. **State your thresholds and their basis.** If `STALENESS_DAYS=7` is an arbitrary
   choice, say it's arbitrary and show what happens at 3 and 14.
3. **Publish the method before the numbers.** Anyone should be able to disagree
   with your conclusion and reproduce your measurement.
4. **Include the reproduce command and the commit hash.** If the numbers can't be
   traced to a specific version of the code, they're not evidence.
5. **Attribute the source properly.** Agmarknet / data.gov.in, Government Open
   Data Licence — India. They publish this data for public use; saying so is the
   price of using it.
6. **Don't overclaim impact.** "X% of rows failed a structural check" is a fact.
   "This means farmers are being defrauded" is not — you haven't shown that.

---

## Metrics to track over time

Put these in Grafana and watch the trend. A single number is an anecdote; a trend
is a signal.

| Metric | Why it matters | Alert on |
|---|---|---|
| Pass rate % | Overall health | < 90% for 3 consecutive days |
| Rows quarantined | Volume of bad data | > 10% of a batch |
| Staleness (median days) | Freshness of the source | > 7 days |
| Duplicate rate | Feed reliability | Sudden doubling |
| Outlier rate | Spikes vs errors | Sudden tripling |
| Mandis reporting | Coverage | A district dropping to zero |

**The change in these numbers over time is your most publishable result.**
"Pass rate improved from 91.2% to 96.8% over the semester" is a real finding,
and reporting it honestly — including any regression you caused — is what
distinguishes measurement from marketing.

---

## Current report

[docs/data-quality-report.md](data-quality-report.md) is the latest generated
report. It is regenerated by `make quality` and should be committed on every
release. The version in this repo was generated from a development dataset — run
the command against your production database to replace it with real numbers.
