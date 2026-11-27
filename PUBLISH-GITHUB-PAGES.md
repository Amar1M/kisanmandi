# Public release and WSL daily refresh

This setup uses GitHub Pages for the public site and the existing WSL laptop for data.gov.in ingestion. It avoids an always-on cloud account, a new cloud account, card verification, and a custom domain. The live URL is:

`https://amar1m.github.io/kisanmandi/`

GitHub Actions **only deploys committed static files** from `public/`; it does not call data.gov.in. WSL runs the existing bounded ingest and quality gate, updates the local SQLite database and raw landing zone, exports the static site, then commits/pushes only `public/index.html` and `public/prices.json`. A push of those files triggers the Pages deployment; data-only snapshot commits are excluded from the full CI matrix to avoid rebuilding the application every day.

## One-time setup

1. Keep GitHub Pages **Settings → Pages → Source** set to **GitHub Actions**.
2. Confirm your personal `DATA_GOV_API_KEY` is still in the ignored local `.env`. The script will fail before network access if it is absent. Never put the key in a tracked file or share it in chat.
3. Replace `.github/workflows/publish-pages.yml` with the static-only workflow in this bundle and add `scripts/update_public_site.sh`.
4. Publish the data already in your local database without making a new API request:

   ```bash
   cd /home/amarnavya/projects/kisanmandi
   source .venv/bin/activate
   python scripts/export_static_site.py --output-dir public
   python -m json.tool public/prices.json | head -30
   git add .github/workflows/publish-pages.yml scripts/update_public_site.sh PUBLISH-GITHUB-PAGES.md public/index.html public/prices.json
   git commit -m "Publish static Karnataka price guide"
   git push origin main
   ```

   This initial commit triggers Pages. Confirm the deployment is green and open the Pages URL. The JSON contains public mandi price observations only; it does not contain credentials or host diagnostics.

5. After confirming the local `.env` contains the key and the static-only workflow is pushed, remove the now-unused `DATA_GOV_API_KEY` repository secret from GitHub Settings. The daily workflow reads the key only from the local ignored `.env`.

## Schedule daily refresh from Windows Task Scheduler

The WSL machine must have internet access and be awake at the scheduled time. The local database and raw landing files persist in WSL, so history accumulates locally. If the machine is off, no cloud ingest happens; you can configure Task Scheduler to run the missed task when the machine next starts.

1. Open **Task Scheduler** in Windows and choose **Create Basic Task**.
2. Name it `KisanMandi daily refresh`; choose a **Daily** trigger at **18:30** local time.
3. For the action, choose **Start a program**:
   - Program: `C:\Windows\System32\wsl.exe`
   - Arguments: `--user amarnavya --exec bash -lc "/home/amarnavya/projects/kisanmandi/scripts/update_public_site.sh"`
4. In task properties, select **Run only when user is logged on** so the existing WSL Git/SSH authentication can be used. Enable **Run task as soon as possible after a scheduled start is missed**. If available and appropriate, enable waking the computer to run the task.
5. Test the Git remote from WSL before relying on the schedule:

   ```bash
   cd /home/amarnavya/projects/kisanmandi
   GIT_SSH_COMMAND='ssh -o BatchMode=yes' git ls-remote origin HEAD >/dev/null && echo 'GitHub SSH access works non-interactively'
   ```

   If that fails, do not put a private SSH key or password into the script or Task Scheduler. Resolve WSL Git authentication interactively first.

The script uses a lock to prevent overlaps and refuses to run if the working tree is dirty or the branch is not `main`. It runs the bounded Karnataka ingest, applies the existing quality checks, exports the current database, commits only the generated public files, and pushes them. A failed ingest or push does not trigger a new Pages deployment. The static page keeps the observation date and freshness warning visible.

## Scope and limits

- Pages exposes only a **static, read-only Karnataka price guide**, not the FastAPI dashboard/API, metrics, host diagnostics, or quarantined-row details.
- The scheduled ingest is **local to WSL**, not cloud-hosted or guaranteed when the laptop is asleep/offline.
- If the data.gov.in service cannot be reached from the laptop at the scheduled time, the script stops and the last published page remains online.
- Data.gov.in observations are not guaranteed offers. The site includes a freshness warning and advisory disclaimer.
