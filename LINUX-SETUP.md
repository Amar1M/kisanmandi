# LINUX SETUP — Ubuntu on your laptop

You've chosen the right path. On Linux, every command in this project's docs works
**exactly as written** — `make test`, `make ingest`, `sudo systemctl enable`, all of it.
No translation layer, no PowerShell execution-policy errors, and Docker runs
natively instead of through a VM.

It also matches Oracle Cloud, where your VM runs Ubuntu 24.04.

---

# 1. Which kind of Linux? (read this first)

You have Windows 11 Home on an Acer Aspire A324-53. Three options:

| Option | What it means | Risk | Recommended? |
|---|---|---|---|
| **WSL2 + Ubuntu 24.04** | Real Ubuntu kernel running inside Windows. Both systems at once. | **Very low.** Uninstall in one command if you dislike it. | ⭐ **Yes** |
| **Dual boot** | Full Ubuntu on a separate partition; choose at startup | **Medium.** Partitioning can lose data. Acer Wi-Fi/sound sometimes need driver fixes. | Only if you want a full desktop GUI |
| **Replace Windows** | Ubuntu only | **High** for a first Linux install, and you lose Windows | No — not yet |

**Recommendation: WSL2.** You get 95% of the Linux benefits with almost none of
the risk. Your Windows install, OneDrive, and college software all keep working.
And you can start in the next 20 minutes rather than next weekend.

> **Honest caveat:** WSL2 is not identical to a real server. Two differences matter
> for this project, and both are handled below: systemd needs enabling, and
> there's a filesystem performance trap that costs people hours.

---

# 2. Install WSL2 and Ubuntu 24.04 (~15 min + one reboot)

## 2.1 Open PowerShell **as Administrator**

Press `Win + X` → **Terminal (Admin)** or **Windows PowerShell (Admin)**.
Click **Yes** when Windows asks for permission.

> Administrator matters here. Without it, the install fails partway with a
> permissions error that's confusing to diagnose.

## 2.2 One command

```powershell
wsl --install -d Ubuntu-24.04
```

This single command:
- Enables the **Virtual Machine Platform** and **WSL** Windows features
- Downloads the WSL2 kernel
- Installs **Ubuntu 24.04 LTS**
- Sets WSL2 as the default

**Windows 11 Home is fine** for this. WSL2 uses the Virtual Machine Platform
component, not the Hyper-V management role. You do not need Windows Pro.

## 2.3 Reboot

```powershell
Restart-Computer
```

You must reboot before Ubuntu becomes usable.

## 2.4 First launch — create your Linux user

After the reboot, Ubuntu opens automatically (or search **Ubuntu** in the Start menu).

It asks for:
- **Username** — lowercase, e.g. `amar` (not `Amar Reddy` — spaces cause trouble)
- **Password** — you won't see characters as you type. That's normal.

This user is separate from your Windows account. Remember the password; you'll
type it for `sudo`.

## 2.5 Verify it worked

In the Ubuntu terminal:

```bash
lsb_release -a          # should say Ubuntu 24.04.x LTS
uname -r                # should contain "microsoft-standard-WSL2"
```

If `uname -r` mentions WSL2, you're running a real Linux kernel.

---

# 3. Tune WSL2 so it doesn't eat your laptop (~5 min)

Your laptop has 16 GB RAM. By default WSL2 can grab most of it and hold it even
when idle. This is the single most common reason people conclude "16 GB isn't
enough for cloud work." It is — WSL just needs telling.

## 3.1 Create the config file

In **PowerShell** (not Ubuntu):

```powershell
notepad "$env:USERPROFILE\.wslconfig"
```

Click **Yes** to create the file. Paste this in:

```ini
[wsl2]
# Leave ~6 GB for Windows. This project needs ~4 GB at most.
memory=9GB
processors=8
swap=8GB

# Network: keep the DEFAULT (NAT). Do NOT set networkingMode=mirrored.
# Mirrored mode is known to break Docker port binding, container networking and
# Kubernetes startup -- and this project uses Docker Compose and k3s.

[experimental]
# Give unused RAM back to Windows when WSL is idle.
autoMemoryReclaim=gradual

# Shrink the virtual disk automatically instead of letting it grow forever.
sparseVhd=true
```

Save and close.

> ⚠️ **Do not add `networkingMode=mirrored`.** It's widely recommended for VPN
> users, and it genuinely breaks container tooling: port-binding failures,
> container connectivity problems, and Kubernetes refusing to start. You will hit
> all three in this project. Leave it at the default.

## 3.2 Restart WSL

```powershell
wsl --shutdown
```

Wait ~10 seconds, then open Ubuntu again. The settings now apply.

## 3.3 Confirm

In Ubuntu:

```bash
nproc                   # should print 8
free -h                 # "total" in the Mem row should be about 9Gi
```

---

# 4. Enable systemd (~5 min) — **important for this project**

systemd is what runs background services. **You will need it in week 4** to install
the nightly ingest timer from `docs/02-oracle-setup.md`.

Recent versions of WSL default to systemd on Ubuntu 24.04, so it may already be on.

## 4.1 Check

```bash
ps -p 1 -o comm=
```

- Prints **`systemd`** → ✅ already enabled, skip to section 5
- Prints **`init`** → 🔧 enable it below

## 4.2 Enable it

```bash
sudo tee /etc/wsl.conf > /dev/null <<'EOF'
[boot]
systemd=true

[network]
generateResolvConf=true
generateHosts=true

[interop]
enabled=true
EOF
```

Then, back in **PowerShell**:

```powershell
wsl --shutdown
```

Reopen Ubuntu and check again:

```bash
ps -p 1 -o comm=          # should now print: systemd
systemctl is-system-running  # "running" or "degraded" are both fine
```

Note: `appendWindowsPath=false` is a popular tweak that stops Windows folders
polluting your Linux `$PATH`. It's a genuine speedup for tab-completion, but it
breaks the `code .` command until you've installed the VS Code WSL extension
(section 9). Leave it out for now; add it later if you want.

---

# 5. Install the essentials (~5 min)

```bash
sudo apt update && sudo apt upgrade -y
```

```bash
sudo apt install -y \
  build-essential git curl wget unzip jq \
  python3 python3-venv python3-pip \
  ca-certificates gnupg make
```

## Why each one

| Package | Needed for |
|---|---|
| `build-essential` | Compiling any Python package without a prebuilt wheel |
| `git` | Version control (Ubuntu's git is newer than Windows') |
| `make` | **Every `make test` / `make ingest` command in the docs now works** |
| `python3-venv` | `python -m venv` — not installed by default on Ubuntu |
| `jq` | Pretty-printing the JSON your CLI and API produce |
| `unzip` | Extracting the project zip |

## Tell git who you are

```bash
git config --global user.name "Amarnath Reddy"
git config --global user.email "your-email@example.com"
git config --global init.defaultBranch main
```

## Verify

```bash
python3 --version    # Ubuntu 24.04 ships Python 3.12
make --version
git --version
```

---

# 6. Install Docker Engine (~5 min)

**Install Docker Engine inside Ubuntu — not Docker Desktop for Windows.**

Docker Desktop runs an extra VM layer. Native Docker Engine inside WSL is lighter,
faster, and matches your Oracle VM exactly — which means what you test locally
behaves the same when you deploy.

## 6.1 Install

```bash
curl -fsSL https://get.docker.com | sh
```

## 6.2 Run it without sudo

```bash
sudo usermod -aG docker $USER
```

**Then close the Ubuntu window completely and reopen it.** Group membership only
applies to new sessions — this trips up nearly everyone.

## 6.3 Verify

```bash
docker --version
docker run --rm hello-world
```

If you see "Hello from Docker!", it works. No Docker Desktop, no licensing prompt,
no extra VM.

## 6.4 Start Docker automatically (only if systemd is enabled)

```bash
sudo systemctl enable --now docker
```

Without systemd, start it manually with `sudo service docker start` after each reboot.

---

# 7. ⚠️ The `/mnt/c` performance trap — read this

**This is the mistake that costs WSL users hours and makes them think Linux is slow.**

Your Windows drive appears inside Ubuntu at `/mnt/c/`. It works, but every file
operation crosses the VM boundary — file reads can be **5–10× slower**, and
`git status` on a large repo can take 30 seconds instead of 0.2.

## The rule

> **Keep your code in `~/` (Linux), never in `/mnt/c/` (Windows).**

## Set up your project directory

```bash
mkdir -p ~/projects
cd ~/projects
```

Your project lives at `/home/amar/projects/kisanmandi` — a real Linux filesystem.

## Getting the project in

**Option A — copy the zip from Windows (fastest, use this today)**

If you downloaded `kisanmandi.zip` to your Windows Downloads folder:

```bash
cp "/mnt/c/Users/Amar Reddy/Downloads/kisanmandi.zip" ~/projects/
cd ~/projects
unzip -q kisanmandi.zip
cd kisanmandi
```

> The quotes around the path matter — `Amar Reddy` contains a space.

**Option B — clone from GitHub (once you've pushed it)**

```bash
cd ~/projects
git clone https://github.com/YOUR-USERNAME/kisanmandi.git
cd kisanmandi
```

## Confirming you're in the right place

```bash
pwd
```

Must print something starting with `/home/`, **not** `/mnt/c/`. This one check
saves a lot of frustration.

---

# 8. Run the project 🏆

Everything from the docs now works verbatim.

```bash
cd ~/projects/kisanmandi

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

make test
```

### Expected:

```
125 passed in 1.20s
```

**Note: `source .venv/bin/activate`** (Linux), not `.\.venv\Scripts\Activate.ps1`
(PowerShell). Your prompt should now start with `(.venv)`.

### Then look at what you have

```bash
make help          # every available command
make stats         # config + row counts
```

**`make` works now.** No translation table, no alternatives — the docs and reality
have finally converged.

---

# 9. VS Code with the Linux filesystem (~5 min)

Editing Linux files with Windows VS Code over the network share is slow. The
**Remote-WSL** extension runs the VS Code *server inside Linux*, so it's fast and
the integrated terminal is Linux.

1. Install **VS Code** on Windows: <https://code.visualstudio.com/>
2. In VS Code, install the extension **WSL** (by Microsoft)
3. From your **Ubuntu** terminal:

```bash
cd ~/projects/kisanmandi
code .
```

The first launch installs the server inside WSL (takes ~30 seconds). Look at the
bottom-left corner — it should say **WSL: Ubuntu-24.04**.

Recommended extensions (VS Code will offer them once you open the project):

| Extension | Why |
|---|---|
| **Python** + **Pylance** | Autocomplete and type checking |
| **Ruff** | Live linting — same tool CI runs |
| **Even Better TOML** | Editing `pyproject.toml` |
| **Docker** | Inspect images and containers |
| **Kubernetes** | Browse the cluster in week 7 |
| **YAML** | Editing the GitHub Actions workflows |

---

# 10. Make the terminal pleasant (optional, 2 min)

Install **Windows Terminal** if you don't have it:

```powershell
winget install Microsoft.WindowsTerminal
```

It supports tabs, panes (`Alt+Shift+D`), and proper fonts. Ubuntu appears as a
profile automatically.

Then in Ubuntu, install a few quality-of-life tools:

```bash
sudo apt install -y htop tree ncdu
```

```bash
# A friendlier shell prompt, with git branch shown
sudo apt install -y zsh
sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
```

`htop` (process viewer), `tree` (directory structure — great for your report
screenshots), and `ncdu` (find what's eating your disk).

---

# 11. Daily workflow

Once set up, starting work is three commands. From PowerShell:

```powershell
wsl
```

Then in Ubuntu:

```bash
cd ~/projects/kisanmandi
source .venv/bin/activate
```

Every session needs those two lines — the venv doesn't persist between terminal
windows.

## Keep WSL tidy

Run occasionally:

```bash
sudo apt autoremove -y
docker system prune -a --volumes     # ⚠️ removes unused volumes — check first
```

From **PowerShell** (reclaim disk space from the growing virtual disk):

```powershell
wsl --shutdown
wsl --manage Ubuntu-24.04 --set-sparse true
```

The WSL disk file grows but never shrinks on its own. `sparseVhd=true` (section 3)
handles this automatically going forward, but running it once after a heavy build
phase can recover several GB.

## Useful WSL commands (from PowerShell)

| Command | Does |
|---|---|
| `wsl` | Open Ubuntu |
| `wsl --shutdown` | Restart WSL (apply config changes) |
| `wsl --list --verbose` | Show distros and WSL versions |
| `wsl --update` | Update the WSL kernel |
| `wsl --status` | Version and default distro |

## Reaching Windows files from Ubuntu

```bash
cd /mnt/c/Users/"Amar Reddy"
```

Fine for copying a file in or out. **Never develop there.**

---

# 12. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `wsl --install` fails with a permissions error | Not run as Administrator | Right-click PowerShell → **Run as administrator** |
| `WSL 2 requires an update to its kernel component` | Kernel missing | `wsl --update`, then reboot |
| Ubuntu window closes immediately | First-run setup didn't finish | `wsl --install -d Ubuntu-24.04` again |
| `ps -p 1 -o comm=` prints `init` not `systemd` | systemd not enabled, or `wsl --shutdown` not run | Redo section 4, then `wsl --shutdown` from PowerShell |
| `permission denied while trying to connect to the Docker daemon` | Not in the `docker` group **in this session** | Close and reopen the Ubuntu window after `usermod` |
| Docker containers can't reach the network | `networkingMode=mirrored` is set | **Remove that line** from `.wslconfig`, then `wsl --shutdown` |
| `python3 -m venv` fails | `python3-venv` missing | `sudo apt install python3-venv` |
| `make: command not found` | `make` missing | `sudo apt install make` (should be installed by section 5) |
| Everything is slow | Project is on `/mnt/c` | Move to `~/projects` — see section 7 |
| WSL uses all 16 GB RAM and won't release it | No `.wslconfig`, or `autoMemoryReclaim` unset | Section 3, then `wsl --shutdown` |
| `Windows Subsystem for Linux has no installed distributions` | Feature enabled but no distro | `wsl --install -d Ubuntu-24.04` |
| Port 8000 unreachable from the Windows browser | NAT mode | It should work; if not, use `localhost:8000` **and** check nothing else holds the port: `ss -tlnp \| grep 8000` |
| Wi-Fi or Bluetooth died after a dual boot | Common on Acer Aspire with Linux drivers | You're on WSL2 — you avoided this entirely |

---

# 13. What changed versus the Windows guide

| | Windows | Ubuntu (WSL2) |
|---|---|---|
| Activate venv | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |
| Run tests | `python -m pytest -q` | `make test` or `python -m pytest -q` |
| `make` | Not installed | ✅ Works |
| Docker | Docker Desktop, licensing prompts | ✅ Native engine, no VM, no prompts |
| systemd timers | Not available | ✅ Works (section 4) |
| Shell scripts | PowerShell / Git Bash | ✅ Real bash — matches your Oracle VM |
| Execution policy errors | Common | ✅ None |

**This is why Linux is the right choice for a DevOps project:** the tooling you
learn here is the tooling that runs on the server you'll deploy to. No
translation layer between practice and production.

---

# ✅ Linux setup checklist

- [ ] WSL2 installed, `uname -r` shows WSL2
- [ ] `.wslconfig` created with `memory=9GB`, `autoMemoryReclaim=gradual`, `sparseVhd=true`
- [ ] **No** `networkingMode=mirrored` (it breaks Docker and k8s)
- [ ] `ps -p 1 -o comm=` prints **`systemd`**
- [ ] `build-essential`, `git`, `make`, `python3-venv`, `jq` installed
- [ ] `docker run --rm hello-world` succeeds without sudo
- [ ] Project cloned to **`~/projects/kisanmandi`** (not `/mnt/c/`)
- [ ] `make test` → **125 passed**
- [ ] VS Code connected via **WSL: Ubuntu-24.04**
- [ ] `make help` lists all 35 targets

---

# Your actual next commands

```bash
# 1. Set up the workspace (Ubuntu terminal)
mkdir -p ~/projects && cd ~/projects
cp "/mnt/c/Users/Amar Reddy/Downloads/kisanmandi.zip" .
unzip -q kisanmandi.zip
cd kisanmandi

# 2. Make it run
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. 🏆
make test
```

**Come back when you see `125 passed`** and tell me:

1. Did it pass?
2. Did `ps -p 1 -o comm=` print `systemd`?
3. Did `docker run --rm hello-world` work?

Then we do the Oracle VM request, the Student Pack, and your first real pull of
Karnataka mandi prices.
