# Deploying on ₹0 — Oracle Cloud Always Free, step by step

**What you get, permanently free:** 4 ARM cores, **24 GB RAM**, 200 GB block
storage, 10 TB/month egress. That is more RAM than the laptop you're developing on.

No expiry. No credit card charge for Always Free resources. Read that twice,
because almost every other "free" cloud tier has a clock.

---

## Step 0 — Do this today, not in week 4

**"Out of capacity" is common on the Always Free ARM tier**, and it can take days
or weeks to get an instance. Start the request in week 0 so it's ready when you
need it.

Two ways to improve your odds:

1. **Retry across regions.** Capacity varies per region; Frankfurt and Singapore
   are often easier than US regions. If one fails, try another.
2. **Upgrade to Pay As You Go.** You keep every Always Free resource at ₹0, but
   you draw from a much larger capacity pool. Reported allocation: ~3 days on
   PAYG vs weeks on pure free tier.

   **Before you upgrade, set a billing alarm.** If you exceed Always Free limits
   on a PAYG account, you *will* be charged. The Always Free resources themselves
   stay free — it's the accidental extra that costs money.

> ⚠️ Weigh this carefully against a ₹2,000 total budget. PAYG with a hard alarm
> and no resources outside the free tier is safe. PAYG without an alarm is how
> people wake up to a ₹3,100 NAT Gateway bill.

---

## Step 1 — Create the instance

In the Oracle Cloud console: **Compute → Instances → Create Instance**

| Field | Value |
|---|---|
| Image | Ubuntu 24.04 (aarch64 / ARM) |
| Shape | **Ampere → VM.Standard.A1.Flex** |
| OCPUs | **4** |
| Memory | **24 GB** |
| Boot volume | **200 GB** (Always Free allows up to 200 GB total) |
| SSH keys | Upload your public key (`~/.ssh/id_ed25519.pub`) |

**Never select a GPU shape.** GPUs are not part of Always Free and would bill
immediately.

One VM using all 4 OCPUs / 24 GB is the recommended split for this project. If you
prefer, you can spread the same totals across up to 4 VMs (2×2 OCPU/12 GB, or
4×1 OCPU/6 GB).

---

## Step 2 — First login and hardening

```bash
ssh ubuntu@<public-ip>
```

```bash
# Update everything
sudo apt update && sudo apt upgrade -y

# Firewall: only SSH, HTTP, HTTPS. Ubuntu images ship with iptables rules that
# must be updated as well as the Oracle security list (see Step 3).
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
sudo ufw status

# Automatic security updates
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades

# Fail2ban: you are on the public internet now, and bots will find you
sudo apt install -y fail2ban
sudo systemctl enable --now fail2ban
```

Check the timezone — your ingest schedule depends on it:

```bash
timedatectl                                    # usually UTC, which is fine
# Optional: sudo timedatectl set-timezone Asia/Kolkata
```

---

## Step 3 — Open ports in Oracle's security list

`ufw` alone is not enough. Oracle has a separate network layer:

**Networking → Virtual Cloud Networks → your VCN → Security Lists → Default Security List**

Add ingress rules for TCP 80 and TCP 443 from `0.0.0.0/0`.
Leave 5432 (Postgres) **closed** — it must never be exposed to the internet.

---

## Step 4 — Install Docker (native, not Docker Desktop)

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
docker run --rm hello-world
```

---

## Step 5 — Postgres, then the app

```bash
sudo apt install -y postgresql
sudo systemctl enable --now postgresql

sudo -u postgres psql <<'SQL'
CREATE USER kisanmandi WITH PASSWORD 'CHANGE-ME-STRONG';
CREATE DATABASE kisanmandi OWNER kisanmandi;
GRANT ALL PRIVILEGES ON DATABASE kisanmandi TO kisanmandi;
SQL
```

```bash
git clone https://github.com/YOUR-USERNAME/kisanmandi.git
cd kisanmandi
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

cat > .env <<'EOF'
DATA_GOV_API_KEY=your-real-key
DATABASE_URL=postgresql+psycopg://kisanmandi:CHANGE-ME-STRONG@localhost:5432/kisanmandi
DATA_DIR=/home/ubuntu/kisanmandi-data
LANDING_BACKEND=local
LANDING_LOCAL_DIR=/home/ubuntu/kisanmandi-data/landing
EOF

chmod 600 .env          # the API key lives here — lock it down immediately
kisanmandi stats        # creates the schema and shows the connection
kisanmandi ingest --state Karnataka
```

---

## Step 6 — Run it on a schedule (week 4)

Start with systemd. It is simpler than Kubernetes and it will not surprise you.

`/etc/systemd/system/kisanmandi-ingest.service`:

```ini
[Unit]
Description=KisanMandi daily price ingest
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/kisanmandi
EnvironmentFile=/home/ubuntu/kisanmandi/.env
ExecStart=/home/ubuntu/kisanmandi/.venv/bin/kisanmandi ingest
StandardOutput=journal
StandardError=journal
# Survive a slow API without hanging forever
TimeoutStartSec=3600
```

`/etc/systemd/system/kisanmandi-ingest.timer`:

```ini
[Unit]
Description=Run the KisanMandi ingest nightly

[Timer]
# 18:30 IST = 13:00 UTC. The Agmarknet feed fills through the IST day.
OnCalendar=*-*-* 13:00:00 UTC
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kisanmandi-ingest.timer

# Prove it works before you trust it
sudo systemctl start kisanmandi-ingest.service
journalctl -u kisanmandi-ingest -n 50 --no-pager
systemctl list-timers | grep kisanmandi
```

`Persistent=true` means a missed run (because the VM rebooted) fires on the next
boot. Without it, a reboot at 12:59 UTC silently costs you a day of data.

---

## Step 7 — Upgrade to Kubernetes (week 7)

Only after the systemd timer has run successfully for several nights.

```bash
curl -sfL https://get.k3s.io | sh -
mkdir -p ~/.kube && sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER ~/.kube/config
export KUBECONFIG=~/.kube/config

kubectl get nodes
kubectl create namespace kisanmandi
```

Then move the ingest into a `CronJob` (see `deploy/helm/`) and disable the systemd
timer so you don't run it twice.

**RAM budget on 24 GB** — this is where the free tier really pays off:

| Component | Approx RAM |
|---|---|
| k3s (server + agent) | ~1.0 GB |
| Postgres | ~0.5 GB |
| API pod | ~0.2 GB |
| Prometheus + Grafana (if self-hosted) | ~1.5 GB |
| **Total** | **~3.2 GB of 24 GB** |

You have room to spare. (On a 1 GB droplet, none of this would fit — which is the
whole argument for choosing this free tier.)

---

## Step 8 — Ingress and a free domain

```bash
# Cloudflare Tunnel: gives you HTTPS and a public hostname with no open ports,
# no static IP, and no load balancer.
cloudflared tunnel login
cloudflared tunnel create kisanmandi
cloudflared tunnel route dns kisanmandi api.yourdomain.me
```

Get the domain free from the **GitHub Student Developer Pack** (Namecheap `.me`,
Name.com from 25+ extensions, or `.TECH`).

Alternatively, run Traefik (bundled with k3s) with a Let's Encrypt certificate.

---

## Step 9 — Backups you have actually tested

```bash
# Nightly dump to a rotating file
cat > /home/ubuntu/backup.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
pg_dump -U kisanmandi kisanmandi | gzip > /home/ubuntu/backups/kisanmandi-$STAMP.sql.gz
find /home/ubuntu/backups -name 'kisanmandi-*.sql.gz' -mtime +14 -delete
EOF
chmod +x /home/ubuntu/backup.sh
```

**Then restore one.** A backup you have never restored is a hope, not a backup:

```bash
createdb -U kisanmandi kisanmandi_restore_test
gunzip -c /home/ubuntu/backups/kisanmandi-<stamp>.sql.gz | psql -U kisanmandi kisanmandi_restore_test
psql -U kisanmandi kisanmandi_restore_test -c "SELECT count(*) FROM mandi_prices;"
dropdb -U kisanmandi kisanmandi_restore_test
```

Record the wall-clock time it took. That number is your RTO, and putting it in
your README is worth more than any architecture diagram.

---

## Step 10 — The weekly 5-minute audit

```bash
df -h                                    # disk: Always Free is 200 GB
free -h                                  # RAM
docker system prune -a --volumes         # reclaim space (careful: removes unused volumes)
sudo du -sh /home/ubuntu/kisanmandi-data/landing
systemctl list-timers | grep kisanmandi  # is the schedule still alive?
```

**And on Oracle:** Billing → Cost Analysis. It must read **₹0.00**. Screenshot it
monthly — that screenshot is your proof of the ₹0 claim.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Out of capacity` when creating the VM | ARM free tier demand | Retry another region, or move to PAYG (keep the alarm on) |
| Ingest works locally, fails on the VM | `docker build` on ARM needs arm64 images | Use multi-arch bases (`python:3.12-slim` is multi-arch) |
| VM feels slow | ARM CPU + emulated x86 containers | Build for `linux/arm64`: `docker buildx build --platform linux/arm64` |
| Instance reclaimed for inactivity | Oracle reclaims idle Always Free instances | Keep light periodic activity (your nightly timer does this) |
| Can't reach port 80 | Oracle security list, not just `ufw` | Open the port in both (Step 3) |
| Postgres connection refused from Docker | `localhost` inside a container ≠ the host | Use the host's private IP or run Postgres as a container |
| Timer never fires | Wrong timezone in `OnCalendar` | `timedatectl`; use an explicit `UTC` suffix |

---

## Why this setup and not something fancier

Write this reasoning into `docs/decisions.md`. An architecture decision with a
stated reason is worth ten diagrams.

| Decision | Alternative | Why |
|---|---|---|
| Oracle Always Free | ₹500/month VPS | 24 GB RAM vs 1 GB, at ₹0, with no expiry |
| k3s | Full Kubernetes | 1 GB vs ~4 GB; one binary; you learn the same API |
| systemd timer (week 4) → CronJob (week 7) | Start with K8s | Get it *running* before you get it elegant |
| Cloudflare R2 | AWS S3 | Zero egress vs ₹8.64/GB — a 25× difference |
| SQLite locally, Postgres in production | Same everywhere | Local iteration speed matters more than parity here |
| Cloudflare Tunnel | Load balancer + static IP | Free, no open ports, no certificate management |
