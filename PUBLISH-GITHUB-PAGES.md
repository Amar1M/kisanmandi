# Public release and daily Karnataka ingest

This release uses GitHub Pages plus GitHub Actions, avoiding a new cloud account, a custom domain, and card verification. It publishes a **static, read-only farmer price guide** at:

`https://amar1m.github.io/kisanmandi/`

It does not publish the FastAPI dashboard, interactive API, Prometheus metrics, host diagnostics, quarantined-row details, or any credentials. The Actions runner performs a bounded Karnataka ingest, applies the existing quality gate, and only then exports the public price snapshot. If the ingest is empty, truncated, or fails its checks, the workflow fails before replacing the last published site.

## One-time GitHub setup

1. In the repository, open **Settings → Pages** and set **Build and deployment → Source** to **GitHub Actions**.
2. Open **Settings → Secrets and variables → Actions → New repository secret**.
   - Name: `DATA_GOV_API_KEY`
   - Value: your personal data.gov.in API key
   - Enter it directly in GitHub. Never paste it into chat, a commit, or workflow logs.
3. Add the workflow and scripts from this release to the repository's default branch (`main`). Do not add the key to `.env.example`, YAML, or any tracked file.
4. In **Actions**, select **Publish Karnataka price guide → Run workflow** for the first run. Confirm the job completes and open its Pages URL.

The workflow refuses to run with an empty key rather than silently using the shared demo key. It does not run on pull requests. Permissions are limited to reading repository contents and publishing Pages.

## Daily schedule and limits

- Scheduled for **13:00 UTC / 18:30 IST** each day. GitHub may start scheduled jobs late; a daily workflow is not a guaranteed-to-the-minute service.
- Ingest scope: **Karnataka only**, consistent with the verified local demo.
- Maximum 10 pages × 1,000 records, with at least one second between API requests and at most two retries per request.
- If the feed reports more data than the run fetched, or no trustworthy total is available at the page cap, publication is blocked rather than silently showing a partial snapshot.
- No other ingestion schedule is enabled. The existing systemd timer remains off.

## Important scope and persistence limits

GitHub Pages serves a **static snapshot**, not an always-on Python server. The farmer guide updates only after a successful scheduled run. If a run fails, the previous published snapshot remains. The run's SQLite database and raw landing files live only on that temporary Actions runner; they are not a durable cloud database and do not accumulate an online SQL history. Keep local raw data and your local database backed up separately. Long-term backend persistence would need an approved persistent storage service or VM.

Price rows are public Agmarknet observations. Every result shows its report date and a stale-data warning; values are not guaranteed offers or personal financial advice. The site intentionally exposes no private system metadata or unauthenticated API endpoints.
