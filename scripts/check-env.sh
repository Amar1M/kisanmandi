#!/usr/bin/env bash
# KisanMandi environment check.
#
# Detects whether you're on native Ubuntu or WSL2, then verifies everything the
# project needs. Safe to run repeatedly -- it only reads, never installs or changes
# anything. Exit code 0 means you're ready.
#
#   chmod +x scripts/check-env.sh && ./scripts/check-env.sh

set -uo pipefail

# --- colours (disabled when not a terminal, e.g. piped to a file) -------------
if [ -t 1 ]; then
    R='\033[0;31m'; G='\033[0;32m'; Y='\033[0;33m'; B='\033[0;34m'
    BOLD='\033[1m'; DIM='\033[2m'; N='\033[0m'
else
    R=''; G=''; Y=''; B=''; BOLD=''; DIM=''; N=''
fi

PASS=0; WARN=0; FAIL=0
FAILURES=()

# awk is part of the base Ubuntu install (mawk). Bail out clearly rather than
# printing confusing "awk: command not found" lines partway through the report.
if ! command -v awk >/dev/null 2>&1; then
    printf "This script needs awk, which is missing from PATH.\n"
    printf "Install it with:  sudo apt install gawk\n"
    exit 2
fi

ok()   { printf "  ${G}✔${N} %-34s ${DIM}%s${N}\n" "$1" "${2:-}"; PASS=$((PASS+1)); }
warn() { printf "  ${Y}!${N} %-34s ${DIM}%s${N}\n" "$1" "${2:-}"; WARN=$((WARN+1)); }
bad()  { printf "  ${R}✘${N} %-34s ${DIM}%s${N}\n" "$1" "${2:-}"; FAIL=$((FAIL+1)); FAILURES+=("$1"); }
hdr()  { printf "\n${BOLD}${B}%s${N}\n" "$1"; }
note() { printf "      ${DIM}%s${N}\n" "$1"; }

printf "\n${BOLD}KisanMandi -- environment check${N}\n"
printf "${DIM}%s${N}\n" "$(date -u '+%Y-%m-%d %H:%M UTC')"

# =============================================================================
hdr "1. Operating system"
# =============================================================================
IS_WSL=0
if grep -qi microsoft /proc/version 2>/dev/null || [ -n "${WSL_DISTRO_NAME:-}" ]; then
    IS_WSL=1
fi

if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    DISTRO="${PRETTY_NAME:-unknown}"
else
    DISTRO="unknown"
fi

if [ "$IS_WSL" -eq 1 ]; then
    ok "Linux distribution" "$DISTRO"
    ok "Environment" "WSL2 (Ubuntu inside Windows)"
    WSLVER=$(wsl.exe --version 2>/dev/null | tr -d '\0' | head -1 || echo "")
    [ -n "$WSLVER" ] && note "WSL: $WSLVER"
    # WSL2 vs older WSL1 matters: WSL1 has no real kernel and no systemd.
    if uname -r | grep -qi "microsoft-standard"; then
        ok "WSL 2 kernel" "$(uname -r)"
    else
        bad "WSL 2 kernel" "found $(uname -r) -- that looks like WSL1"
        note "WSL1 cannot run Docker or systemd. Upgrade: wsl --set-version <distro> 2"
    fi
else
    ok "Linux distribution" "$DISTRO"
    ok "Environment" "Native Linux (not WSL)"
fi

ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  ok "Architecture" "$ARCH (amd64)" ;;
    aarch64|arm64) warn "Architecture" "$ARCH -- works, but some tools need arm64 builds" ;;
    *) warn "Architecture" "$ARCH (unusual -- Docker images may need attention)" ;;
esac

# =============================================================================
hdr "2. Where the project lives"
# =============================================================================
CWD=$(pwd)
case "$CWD" in
    /mnt/*)
        bad "Project location" "$CWD"
        note "You are inside the Windows filesystem. File operations here are 5-10x slower"
        note "and 'make test' will crawl. Move the project to your Linux home:"
        note "  mkdir -p ~/projects && cd ~/projects && cp -r \"$CWD\" ."
        ;;
    /home/*)
        ok "Project location" "$CWD (Linux filesystem)"
        ;;
    *)
        warn "Project location" "$CWD (unusual path -- fine, but ~/projects is tidy)"
        ;;
esac

PROJECT_FOUND=0
if [ -f "Makefile" ] && [ -d "src/kisanmandi" ]; then
    ok "Looks like the KisanMandi repo" "Makefile + src/kisanmandi found"
    PROJECT_FOUND=1
elif [ -f "Makefile" ]; then
    warn "Makefile found" "but src/kisanmandi is missing -- incomplete checkout?"
else
    warn "Not inside the project directory" "cd into the kisanmandi folder and re-run"
fi

# =============================================================================
hdr "3. System resources"
# =============================================================================
CPU=$(nproc 2>/dev/null || echo 0)
if [ "$CPU" -ge 2 ]; then
    ok "CPU cores" "$CPU"
else
    bad "CPU cores" "$CPU -- need at least 2"
fi

if command -v free >/dev/null 2>&1; then
    MEM_MB=$(free -m | awk '/^Mem:/ {print $2}')
    MEM_GB=$(awk -v m="$MEM_MB" 'BEGIN {printf "%.1f", m/1024}')
    if [ "$MEM_MB" -ge 3500 ]; then
        ok "RAM available" "${MEM_GB} GB"
    elif [ "$MEM_MB" -ge 1800 ]; then
        warn "RAM available" "${MEM_GB} GB -- tight once Docker is running"
    else
        bad "RAM available" "${MEM_GB} GB -- need ~4 GB for the full stack"
    fi
    if [ "$IS_WSL" -eq 1 ] && [ "$MEM_MB" -lt 6000 ]; then
        note "On WSL, raise this in %USERPROFILE%\\.wslconfig:  memory=9GB"
        note "Then run 'wsl --shutdown' in PowerShell."
    fi
fi

DISK_AVAIL=$(df -BG --output=avail "$HOME" 2>/dev/null | tail -1 | tr -dc '0-9')
if [ -n "${DISK_AVAIL:-}" ]; then
    if [ "$DISK_AVAIL" -ge 10 ]; then
        ok "Free disk in \$HOME" "${DISK_AVAIL} GB"
    elif [ "$DISK_AVAIL" -ge 3 ]; then
        warn "Free disk in \$HOME" "${DISK_AVAIL} GB -- Docker images add up"
    else
        bad "Free disk in \$HOME" "${DISK_AVAIL} GB -- need at least 3 GB"
    fi
fi

# =============================================================================
hdr "4. Required tools"
# =============================================================================
check_ver() {  # name, command, minimum-major
    local name="$1" cmd="$2"
    if command -v "$cmd" >/dev/null 2>&1; then
        local v
        v=$("$cmd" --version 2>&1 | head -1)
        ok "$name" "$v"
    else
        bad "$name" "not installed"
        return 1
    fi
}

PY_OK=0
if command -v python3 >/dev/null 2>&1; then
    PYV=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null)
    PYM=$(python3 -c 'import sys; print(sys.version_info[0]*100 + sys.version_info[1])' 2>/dev/null)
    if [ "${PYM:-0}" -ge 310 ] && [ "${PYM:-0}" -le 314 ]; then
        ok "Python 3" "$PYV (supported)"
        PY_OK=1
    elif [ "${PYM:-0}" -gt 314 ]; then
        warn "Python 3" "$PYV -- newer than tested (3.10-3.14); likely fine"
        PY_OK=1
    else
        bad "Python 3" "$PYV -- need 3.10 or newer"
    fi
else
    bad "Python 3" "not installed -- sudo apt install python3 python3-venv python3-pip"
fi

if [ "$PY_OK" -eq 1 ]; then
    if python3 -m venv --help >/dev/null 2>&1; then
        ok "Python venv module" "available"
    else
        bad "Python venv module" "missing -- sudo apt install python3-venv"
    fi
    if python3 -m pip --version >/dev/null 2>&1; then
        ok "pip" "$(python3 -m pip --version 2>/dev/null | awk '{print $2}')"
    else
        bad "pip" "missing -- sudo apt install python3-pip"
    fi
fi

check_ver "git" git
check_ver "make" make
check_ver "curl" curl
command -v unzip >/dev/null 2>&1 && ok "unzip" "$(unzip -v 2>/dev/null | head -1 | awk '{print $2}')" \
    || warn "unzip" "missing -- sudo apt install unzip (needed to extract the project)"
command -v jq >/dev/null 2>&1 && ok "jq" "$(jq --version)" \
    || warn "jq" "missing -- sudo apt install jq (pretty-prints CLI/API output)"

# =============================================================================
hdr "5. systemd (needed in week 4 for the nightly timer)"
# =============================================================================
PID1=$(ps -p 1 -o comm= 2>/dev/null | tr -d ' ')
if [ "$PID1" = "systemd" ]; then
    ok "systemd is PID 1" "services and timers will work"
elif [ "$IS_WSL" -eq 1 ]; then
    warn "systemd not enabled" "PID 1 is '$PID1', not systemd"
    note "Add to /etc/wsl.conf inside Ubuntu:"
    note "  [boot]"
    note "  systemd=true"
    note "Then run 'wsl --shutdown' in PowerShell and reopen Ubuntu."
    note "Not urgent today -- you need this in week 4."
else
    bad "systemd not PID 1" "PID 1 is '$PID1'"
    note "On native Ubuntu this should be automatic. Check: systemctl status"
fi

if command -v systemctl >/dev/null 2>&1 && [ "$PID1" = "systemd" ]; then
    # `systemctl is-system-running` exits non-zero when degraded, so capture the
    # text first and only fall back if it is empty. Chaining with `||` appends a
    # second line to the variable instead of replacing it.
    STATE=$(systemctl is-system-running 2>/dev/null | head -1 | tr -d ' ')
    [ -z "$STATE" ] && STATE="unknown"
    case "$STATE" in
        running) ok "systemd state" "running" ;;
        degraded) warn "systemd state" "degraded (usually harmless, but check: systemctl --failed)" ;;
        *) warn "systemd state" "$STATE" ;;
    esac
fi

# =============================================================================
hdr "6. Docker (needed in week 6)"
# =============================================================================
if command -v docker >/dev/null 2>&1; then
    ok "Docker installed" "$(docker --version 2>/dev/null)"
    if docker info >/dev/null 2>&1; then
        ok "Docker daemon reachable" "no sudo required"
    elif sudo -n docker info >/dev/null 2>&1; then
        warn "Docker needs sudo" "you are not in the 'docker' group in this session"
        note "Run:  sudo usermod -aG docker \$USER   then CLOSE and REOPEN the terminal"
    else
        warn "Docker daemon not running" "start it: sudo systemctl start docker"
    fi
    if docker compose version >/dev/null 2>&1; then
        ok "Docker Compose (v2 plugin)" "$(docker compose version --short 2>/dev/null)"
    else
        warn "Docker Compose missing" "sudo apt install docker-compose-plugin"
    fi
else
    warn "Docker not installed" "not needed until week 6"
    note "When you need it:  curl -fsSL https://get.docker.com | sh"
fi

# =============================================================================
hdr "7. Network -- can you reach the data source?"
# =============================================================================
if command -v curl >/dev/null 2>&1; then
    if curl -sSf --max-time 12 -o /dev/null "https://api.data.gov.in" 2>/dev/null; then
        ok "api.data.gov.in reachable" "the ingest will work"
    elif curl -sS --max-time 12 -o /dev/null "https://data.gov.in" 2>/dev/null; then
        ok "data.gov.in reachable" "api subdomain didn't respond, but the host resolves"
    else
        warn "data.gov.in unreachable" "check your internet connection or DNS"
        note "Test manually:  curl -I https://api.data.gov.in"
    fi

    if curl -sSf --max-time 12 -o /dev/null "https://pypi.org" 2>/dev/null; then
        ok "pypi.org reachable" "pip install will work"
    else
        warn "pypi.org unreachable" "pip install will fail -- check network or proxy"
    fi

    if curl -sSf --max-time 12 -o /dev/null "https://github.com" 2>/dev/null; then
        ok "github.com reachable" "git push and CI will work"
    else
        warn "github.com unreachable" "check network or proxy"
    fi
fi

# =============================================================================
hdr "8. Ports"
# =============================================================================
if command -v ss >/dev/null 2>&1; then
    if ss -tln 2>/dev/null | grep -q ':8000 '; then
        warn "Port 8000 in use" "the API needs it -- find the process: ss -tlnp | grep 8000"
    else
        ok "Port 8000 free" "ready for 'make serve'"
    fi
    if ss -tln 2>/dev/null | grep -q ':5432 '; then
        warn "Port 5432 in use" "a Postgres may already be running (fine if it's yours)"
    else
        ok "Port 5432 free" "ready for docker compose Postgres"
    fi
fi

# =============================================================================
hdr "9. The project itself"
# =============================================================================
if [ -d ".venv" ]; then
    ok "Virtual environment exists" ".venv/"
    if [ -x ".venv/bin/python" ]; then
        VV=$(.venv/bin/python -c 'import sys; print(".".join(map(str,sys.version_info[:3])))' 2>/dev/null)
        ok "venv interpreter" "Python $VV"
        if .venv/bin/python -c 'import kisanmandi' >/dev/null 2>&1; then
            ok "kisanmandi importable" "dependencies installed"
        else
            warn "kisanmandi not importable" "activate and install: source .venv/bin/activate && pip install -e '.[dev]'"
        fi
        if .venv/bin/python -c 'import pytest' >/dev/null 2>&1; then
            ok "pytest available" "ready to run the test suite"
        else
            warn "pytest missing" "pip install -e '.[dev]'"
        fi
    fi
else
    warn "No .venv yet" "create it: python3 -m venv .venv"
    note "Then:  source .venv/bin/activate && pip install -e '.[dev]'"
fi

if [ -f ".env" ]; then
    if grep -qE '^DATA_GOV_API_KEY=.+' .env 2>/dev/null; then
        ok ".env has an API key" "you'll get full pages, not 10-record chunks"
    else
        warn "DATA_GOV_API_KEY is empty" "you'll be capped at 10 records per request"
        note "Free key: https://data.gov.in/user/register"
    fi
    PERMS=$(stat -c '%a' .env 2>/dev/null || echo "")
    if [ -n "$PERMS" ] && [ "$PERMS" != "600" ]; then
        warn ".env permissions are $PERMS" "it holds a credential: chmod 600 .env"
    fi
else
    warn "No .env yet" "create it: cp .env.example .env"
fi

# =============================================================================
# Summary
# =============================================================================
printf "\n${BOLD}%s${N}\n" "$(printf '%.0s-' {1..64})"
printf "${BOLD}Summary:${N} ${G}%d passed${N}" "$PASS"
[ "$WARN" -gt 0 ] && printf ", ${Y}%d warning(s)${N}" "$WARN"
[ "$FAIL" -gt 0 ] && printf ", ${R}%d blocker(s)${N}" "$FAIL"
printf "\n"

if [ "$FAIL" -eq 0 ] && [ "$PROJECT_FOUND" -eq 1 ]; then
    printf "\n${G}${BOLD}You're good to go.${N}\n"
    cat <<'EOF'

Next:
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -e ".[dev]"
  make test              # expected: 125 passed

EOF
    exit 0
elif [ "$FAIL" -eq 0 ]; then
    printf "\n${G}${BOLD}Your machine is ready.${N} ${Y}The project isn't here yet.${N}\n"
    cat <<'EOF'

Do this next:

  mkdir -p ~/projects && cd ~/projects
  unzip kisanmandi.zip          # or: git clone <your-repo-url>
  cd kisanmandi
  ./scripts/check-env.sh        # run me again from inside the project

EOF
    exit 0
else
    printf "\n${R}${BOLD}Fix these first:${N}\n"
    for f in "${FAILURES[@]}"; do printf "  ${R}✘${N} %s\n" "$f"; done
    printf "\nThen run this script again.\n\n"
    exit 1
fi
