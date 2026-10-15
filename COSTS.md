# Cost ledger — KisanMandi

**Total infrastructure cost to build and run this project: ₹0.**

Budget ceiling: ₹2,000 **for the entire project** (one-time, not per month).
Actual spend: ₹0. Amount remaining: ₹2,000.

Every line below is a free tier that **does not expire**. That distinction matters:
time-limited credits (AWS's 6-month Free Plan, Azure's $100) look free and then
stop, which is how student budgets die mid-semester.

---

## Where each resource runs

| Resource | Provider | What we get | Cost | Expires? |
|---|---|---|---|---|
| App VM (24 GB RAM, 4 cores) | **Oracle Cloud Always Free** (Ampere A1) | 4 OCPU + 24 GB RAM + 200 GB block storage + 10 TB/mo egress | **₹0** | Never |
| CI/CD compute | **GitHub Actions** | Unlimited minutes on a public repo, 4-core runners | **₹0** | Never |
| Container registry | **GHCR** | Free storage for public images | **₹0** | Never |
| Raw landing zone | **Cloudflare R2** | 10 GB storage + 1M writes + 10M reads/month | **₹0** | Never |
| **Egress** | Cloudflare R2 | **Zero egress fees** — the single most important line in this file | **₹0** | Never |
| Database | **Postgres on the Oracle VM** | Runs in the 24 GB we already have | **₹0** | Never |
| Domain + TLS | **GitHub Student Pack** + Let's Encrypt | Free `.me` / Name.com / `.TECH` domain + SSL | **₹0** | 1 year, renewable |
| Metrics & dashboards | **Grafana Cloud** free tier | 10k series, 50 GB logs | **₹0** | Never |
| Secrets | **SOPS + age** | Encrypted in-repo, no service needed | **₹0** | Never |
| Backup | **GitHub Releases / R2** | Postgres dump pushed nightly | **₹0** | Never |
| **TOTAL** | | | **₹0/month** | |

---

## The three decisions that keep this at zero

### 1. Cloudflare R2 instead of AWS S3 — because storage is cheap and egress is not

The landing zone grows forever (one JSON file per page per day). At 50 GB stored
with 200 GB downloaded per month:

| | Storage | Egress | **Monthly total** |
|---|---|---|---|
| **Cloudflare R2** | ₹72 | **₹0** | **₹72** |
| AWS S3 Standard | ₹110 | ₹1,728 | **₹1,838** |

Identical workload, **25× the cost** — and one of those options is 92% of the
project budget for a resource that is not even the product. R2 is S3-compatible,
so this costs exactly one config line: `LANDING_BACKEND=s3`.

### 2. Oracle Always Free instead of a paid VPS

| Option | Spec | Cost/month | Over 12 weeks |
|---|---|---|---|
| **Oracle Always Free** | 4 ARM cores, **24 GB RAM**, 200 GB | **₹0** | **₹0** |
| DigitalOcean basic droplet | 1 vCPU, 1 GB RAM | ~₹500 | ~₹1,500 (75% of budget) |
| Any ₹500/month VPS | — | ₹500 | ₹1,500 |

The Oracle free tier is *larger than the laptop being used to develop this*.
24 GB of RAM runs k3s + Postgres + Grafana with room to spare.

### 3. No subscriptions — ever

| Plan | Cost | Over 12 weeks | % of ₹2,000 budget |
|---|---|---|---|
| Colab Pro | ₹959/month | **₹2,877** | **144%** ❌ |
| Anything monthly | — | — | Fatal |

**A ₹2,000 one-time budget dies the moment you sign up for anything recurring.**
This project needs no GPU and no managed services, so there is nothing to subscribe to.

---

## What we would spend ₹2,000 on (we didn't)

If you *choose* to spend, spend in this order and stop early:

| Priority | Item | Cost | Verdict |
|---|---|---|---|
| 1 | **Reserve as insurance** — for an accidental charge | ₹0 | ✅ **Keep ₹2,000 unspent.** This is the correct answer. |
| 2 | Nothing else is required. | ₹0 | ✅ |
| — | A domain, if you insist | ₹499–679/yr | Free via Student Pack |
| — | GPU hours, if you add ML | ₹49–189/hr | Not needed — CPU is sufficient |
| — | A paid VPS | ₹500/month | Never, with Oracle free available |

---

## Safeguards in place

1. **Billing alarms** set at ₹100 and ₹500 on the Oracle account — configured
   *before* the first resource was created.
2. **Every cloud account is on a free tier or a prepaid balance**, so overspend
   is physically limited.
3. **No API keys in the repo.** `gitleaks` runs in CI on every push.
4. **No 24/7 GPU anything.** There is no GPU in this architecture.
5. **Weekly resource audit** (see the week plan): running VMs, unattached volumes,
   idle load balancers, unattached IPs.

---

## The one number that could have broken this

**AWS NAT Gateway: ~₹3,100/month just for existing.**

Your entire budget, gone, on a network component you never intended to create.
This is why this project does not use AWS for anything with a clock or a NAT.

---

## Verifying this claim

You don't have to take the ₹0 on trust:

```bash
# Oracle: Billing → Cost Analysis should show ₹0.00 for Always Free resources
# Cloudflare: R2 dashboard shows usage against the free tier
# GitHub: Settings → Billing shows Actions minutes used on a public repo = 0 billed
```

Write the verification date and screenshots into your report. **"₹0, and here is
the billing screenshot proving it"** is a stronger claim than "₹0."

---

_Last verified: 2026-10-15 · Exchange rate used: ₹96 = $1_
