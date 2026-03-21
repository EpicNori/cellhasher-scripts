#!/usr/bin/env python3
"""
Android WebDAV NAS + Optional Reverse Tunnel for Cellhasher

Deploys a multi-user WebDAV server to Android devices through Termux.
Optionally installs and starts an MIT-licensed reverse tunnel client.
"""

import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


SCRIPT_META = {
    "id": "android-webdav-nas-tunnel-v1",
    "name": "Android NAS (WebDAV + Tunnel)",
    "description": (
        "Turns Android devices into a small NAS using a WebDAV server with "
        "multiple users and optional reverse tunnel support."
    ),
    "category": "Storage",
    "type": "python",
    "version": "1.0.0",
    "author": "Codex",
    "difficulty": "Advanced",
    "estimatedTime": "8-15 min",
    "tags": [
        "android",
        "nas",
        "webdav",
        "storage",
        "termux",
        "tunnel",
        "cellhasher",
    ],
    "effects": {
        "power": {"reboot": False, "shutdown": False},
        "security": {"modifiesLockScreen": False},
    },
    "estimatedDurationSec": 900,
    "downloads": 0,
    "rating": 5.0,
    "lastUpdated": "2026-03-21",
}


ADB = os.environ.get("adb_path", "adb")
DEVICES = [device for device in os.environ.get("devices", "").split() if device]

TERMUX_RELEASE_API = "https://api.github.com/repos/termux/termux-app/releases/latest"

NAS_PORT = os.environ.get("nas_port", "6065").strip() or "6065"
NAS_ADMIN_USER = os.environ.get("nas_admin_user", "admin").strip() or "admin"
NAS_ADMIN_PASSWORD = os.environ.get("nas_admin_password", "change-me-admin").strip() or "change-me-admin"
NAS_UPLOAD_USER = os.environ.get("nas_upload_user", "uploader").strip() or "uploader"
NAS_UPLOAD_PASSWORD = os.environ.get("nas_upload_password", "change-me-upload").strip() or "change-me-upload"
NAS_READONLY_USER = os.environ.get("nas_readonly_user", "viewer").strip() or "viewer"
NAS_READONLY_PASSWORD = os.environ.get("nas_readonly_password", "change-me-viewer").strip() or "change-me-viewer"
RTUN_GATEWAY = os.environ.get("rtun_gateway", "").strip()
RTUN_KEY = os.environ.get("rtun_key", "").strip()
RTUN_REMOTE_PORT = os.environ.get("rtun_remote_port", NAS_PORT).strip() or NAS_PORT
NAS_EXTERNAL_MODE = os.environ.get("nas_external_mode", "none").strip().lower() or "none"
NAS_EXTERNAL_PATH = os.environ.get("nas_external_path", "").strip()
NAS_EXTERNAL_REMOTE = os.environ.get("nas_external_remote", "").strip()

CONFIG = {
    "nas_port": NAS_PORT,
    "nas_admin_user": NAS_ADMIN_USER,
    "nas_admin_password": NAS_ADMIN_PASSWORD,
    "nas_upload_user": NAS_UPLOAD_USER,
    "nas_upload_password": NAS_UPLOAD_PASSWORD,
    "nas_readonly_user": NAS_READONLY_USER,
    "nas_readonly_password": NAS_READONLY_PASSWORD,
    "rtun_gateway": RTUN_GATEWAY,
    "rtun_key": RTUN_KEY,
    "rtun_remote_port": RTUN_REMOTE_PORT,
    "nas_external_mode": NAS_EXTERNAL_MODE,
    "nas_external_path": NAS_EXTERNAL_PATH,
    "nas_external_remote": NAS_EXTERNAL_REMOTE,
}


def shell_quote(value):
    """Return a POSIX shell-safe single-quoted string."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


TERMUX_SETUP_SCRIPT_TEMPLATE = r"""#!/data/data/com.termux/files/usr/bin/bash
set -e

PORT={nas_port}
ADMIN_USER={admin_user}
ADMIN_PASS={admin_pass}
UPLOAD_USER={upload_user}
UPLOAD_PASS={upload_pass}
READONLY_USER={readonly_user}
READONLY_PASS={readonly_pass}
RTUN_GATEWAY={rtun_gateway}
RTUN_KEY={rtun_key}
RTUN_REMOTE_PORT={rtun_remote_port}
EXTERNAL_MODE={external_mode}
EXTERNAL_PATH={external_path}
EXTERNAL_REMOTE={external_remote}

PREFIX_BIN="$PREFIX/bin"
NAS_ROOT="$HOME/cellhasher-nas"
DATA_ROOT="$NAS_ROOT/data"
CONFIG_PATH="$NAS_ROOT/webdav.yml"
RTUN_CONFIG="$NAS_ROOT/rtun.yml"
EXTERNAL_ENV="$NAS_ROOT/external.env"
INSTALL_NAS="$NAS_ROOT/install_nas.sh"
START_NAS="$NAS_ROOT/start_nas.sh"
START_TUNNEL="$NAS_ROOT/start_tunnel.sh"
STOP_NAS="$NAS_ROOT/stop_nas.sh"
STATUS_NAS="$NAS_ROOT/status_nas.sh"
EXTERNAL_PUSH="$NAS_ROOT/external_push.sh"
EXTERNAL_PULL="$NAS_ROOT/external_pull.sh"
EXTERNAL_INFO="$NAS_ROOT/external_info.sh"
NAS_COMMAND="$PREFIX_BIN/nas"
NAS_LOG="$NAS_ROOT/webdav.log"
TUNNEL_LOG="$NAS_ROOT/rtun.log"
EXTERNAL_LOG="$NAS_ROOT/external.log"

mkdir -p "$NAS_ROOT" "$DATA_ROOT/public" "$DATA_ROOT/uploads" "$DATA_ROOT/admin"
mkdir -p "$DATA_ROOT/users/$ADMIN_USER" "$DATA_ROOT/users/$UPLOAD_USER" "$DATA_ROOT/users/$READONLY_USER"

echo "=============================================="
echo "   Android NAS Hub Bootstrap"
echo "   Cellhasher / Termux deployment"
echo "=============================================="
echo ""
cat > "$DATA_ROOT/README.txt" <<EOF
Cellhasher Android NAS

public/   - read-only share for viewer accounts
uploads/  - writable drop folder for uploader accounts
admin/    - private admin content
users/    - per-user home directories
EOF
cat > "$CONFIG_PATH" <<EOF
address: 0.0.0.0
port: $PORT
prefix: /
debug: false
directory: $DATA_ROOT
permissions: R
users:
  - username: $ADMIN_USER
    password: $ADMIN_PASS
    directory: $DATA_ROOT
    permissions: CRUD
  - username: $UPLOAD_USER
    password: $UPLOAD_PASS
    directory: $DATA_ROOT
    permissions: R
    rules:
      - path: /uploads/
        permissions: CRUD
      - path: /public/
        permissions: R
      - path: /admin/
        permissions: none
      - path: /users/
        permissions: none
  - username: $READONLY_USER
    password: $READONLY_PASS
    directory: $DATA_ROOT/public
    permissions: R
EOF

if [ -n "$RTUN_GATEWAY" ] && [ -n "$RTUN_KEY" ]; then
cat > "$RTUN_CONFIG" <<EOF
gateway_url: $RTUN_GATEWAY
auth_key: $RTUN_KEY
forwards:
  - port: $RTUN_REMOTE_PORT/tcp
    destination: 127.0.0.1:$PORT
EOF
echo "[OK] Tunnel config written to $RTUN_CONFIG"
else
echo "[*] Tunnel config skipped"
fi
echo ""

cat > "$EXTERNAL_ENV" <<EOF
EXTERNAL_MODE=$EXTERNAL_MODE
EXTERNAL_PATH=$EXTERNAL_PATH
EXTERNAL_REMOTE=$EXTERNAL_REMOTE
EOF
echo "[OK] Default NAS config files prepared"
echo ""

echo "[1/3] Creating install and service scripts..."
cat > "$INSTALL_NAS" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
set -e

PREFIX_BIN="$PREFIX/bin"
NAS_ROOT="$HOME/cellhasher-nas"
DATA_ROOT="$NAS_ROOT/data"
CONFIG_PATH="$NAS_ROOT/webdav.yml"
RTUN_CONFIG="$NAS_ROOT/rtun.yml"
EXTERNAL_ENV="$NAS_ROOT/external.env"
NAS_LOG="$NAS_ROOT/webdav.log"
TUNNEL_LOG="$NAS_ROOT/rtun.log"

mkdir -p "$NAS_ROOT" "$DATA_ROOT/public" "$DATA_ROOT/uploads" "$DATA_ROOT/admin"
mkdir -p "$DATA_ROOT/users/$ADMIN_USER" "$DATA_ROOT/users/$UPLOAD_USER" "$DATA_ROOT/users/$READONLY_USER"

echo "=============================================="
echo "   Installing / Reinstalling Android NAS"
echo "=============================================="
echo ""
echo "[1/4] Updating Termux packages..."
pkg update -y || true
pkg upgrade -y || true
echo ""
echo "[2/4] Installing dependencies..."
pkg install -y golang git openssl-tool termux-services procps || {
  echo "[!] Package install retry..."
  pkg install -y golang git openssl-tool termux-services procps
}
export GOBIN="$PREFIX_BIN"
export PATH="$GOBIN:$PATH"
pkg install -y rclone rsync termux-tools >/dev/null 2>&1 || true
echo ""
echo "[3/4] Installing WebDAV..."
if ! command -v webdav >/dev/null 2>&1; then
  go install github.com/hacdias/webdav/v5@latest
fi
if [ ! -x "$PREFIX_BIN/webdav" ]; then
  echo "[ERROR] webdav binary not found after install"
  exit 1
fi
echo ""
echo "[4/4] Installing reverse tunnel client..."
if ! command -v rtun >/dev/null 2>&1; then
  if ! go install github.com/snsinfu/reverse-tunnel/agent/cmd@latest; then
    TMP_BUILD="$HOME/.cache/rtun-build"
    rm -rf "$TMP_BUILD"
    git clone --depth 1 https://github.com/snsinfu/reverse-tunnel.git "$TMP_BUILD"
    cd "$TMP_BUILD"
    go build -o "$PREFIX_BIN/rtun" github.com/snsinfu/reverse-tunnel/agent/cmd
    cd "$HOME"
    rm -rf "$TMP_BUILD"
  fi
fi
echo ""
echo "[OK] NAS components installed"
echo "[OK] Config files are in $NAS_ROOT"
EOF
chmod 755 "$INSTALL_NAS"

cat > "$START_NAS" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
set -e
mkdir -p "$NAS_ROOT"
if [ ! -x "$PREFIX_BIN/webdav" ]; then
  echo "[ERROR] NAS is not installed yet. Run install/reinstall first."
  exit 1
fi
if [ ! -f "$CONFIG_PATH" ]; then
  echo "[ERROR] NAS config not found: $CONFIG_PATH"
  exit 1
fi
pkill -f "$PREFIX_BIN/webdav --config $CONFIG_PATH" >/dev/null 2>&1 || true
nohup "$PREFIX_BIN/webdav" --config "$CONFIG_PATH" >> "$NAS_LOG" 2>&1 &
sleep 2
if pgrep -f "$PREFIX_BIN/webdav --config $CONFIG_PATH" >/dev/null 2>&1; then
  echo "[OK] WebDAV NAS is running on port $PORT"
else
  echo "[ERROR] WebDAV NAS failed to start"
  exit 1
fi
EOF
chmod 755 "$START_NAS"

cat > "$STOP_NAS" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
set -e
pkill -f "$PREFIX_BIN/webdav --config $CONFIG_PATH" >/dev/null 2>&1 || true
pkill -f "rtun" >/dev/null 2>&1 || true
echo "[OK] NAS and tunnel stop requested"
EOF
chmod 755 "$STOP_NAS"

cat > "$STATUS_NAS" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
set -e
WEB_STATUS="stopped"
TUNNEL_STATUS="disabled"
if pgrep -f "$PREFIX_BIN/webdav --config $CONFIG_PATH" >/dev/null 2>&1; then
  WEB_STATUS="running"
fi
if [ -n "$RTUN_GATEWAY" ] && [ -n "$RTUN_KEY" ]; then
  TUNNEL_STATUS="stopped"
  if pgrep -f "rtun" >/dev/null 2>&1; then
    TUNNEL_STATUS="running"
  fi
fi
echo "WebDAV : $WEB_STATUS"
echo "Tunnel : $TUNNEL_STATUS"
echo "Port   : $PORT"
EOF
chmod 755 "$STATUS_NAS"

cat > "$EXTERNAL_INFO" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
set -e
source "$EXTERNAL_ENV"
echo "External mode   : $EXTERNAL_MODE"
if [ "$EXTERNAL_MODE" = "folder" ]; then
  echo "External path   : $EXTERNAL_PATH"
  if [ -d "$EXTERNAL_PATH" ]; then
    echo "Folder status   : available"
  else
    echo "Folder status   : missing"
  fi
elif [ "$EXTERNAL_MODE" = "rclone" ]; then
  echo "External remote : $EXTERNAL_REMOTE"
  if command -v rclone >/dev/null 2>&1; then
    echo "rclone status   : installed"
  else
    echo "rclone status   : missing"
  fi
else
  echo "External target : disabled"
fi
EOF
chmod 755 "$EXTERNAL_INFO"

cat > "$EXTERNAL_PUSH" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
set -e
source "$EXTERNAL_ENV"
mkdir -p "$NAS_ROOT"
if [ "$EXTERNAL_MODE" = "folder" ]; then
  if [ -z "$EXTERNAL_PATH" ]; then
    echo "[ERROR] EXTERNAL_PATH is empty"
    exit 1
  fi
  mkdir -p "$EXTERNAL_PATH"
  rsync -a --delete "$DATA_ROOT"/ "$EXTERNAL_PATH"/ | tee -a "$EXTERNAL_LOG"
  echo "[OK] NAS data pushed to external folder"
elif [ "$EXTERNAL_MODE" = "rclone" ]; then
  if [ -z "$EXTERNAL_REMOTE" ]; then
    echo "[ERROR] EXTERNAL_REMOTE is empty"
    exit 1
  fi
  rclone sync "$DATA_ROOT" "$EXTERNAL_REMOTE" --create-empty-src-dirs | tee -a "$EXTERNAL_LOG"
  echo "[OK] NAS data pushed to external remote"
else
  echo "[SKIP] External datakeeper is disabled"
fi
EOF
chmod 755 "$EXTERNAL_PUSH"

cat > "$EXTERNAL_PULL" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
set -e
source "$EXTERNAL_ENV"
mkdir -p "$NAS_ROOT"
if [ "$EXTERNAL_MODE" = "folder" ]; then
  if [ -z "$EXTERNAL_PATH" ]; then
    echo "[ERROR] EXTERNAL_PATH is empty"
    exit 1
  fi
  if [ ! -d "$EXTERNAL_PATH" ]; then
    echo "[ERROR] External folder not found: $EXTERNAL_PATH"
    exit 1
  fi
  mkdir -p "$DATA_ROOT"
  rsync -a "$EXTERNAL_PATH"/ "$DATA_ROOT"/ | tee -a "$EXTERNAL_LOG"
  echo "[OK] NAS data pulled from external folder"
elif [ "$EXTERNAL_MODE" = "rclone" ]; then
  if [ -z "$EXTERNAL_REMOTE" ]; then
    echo "[ERROR] EXTERNAL_REMOTE is empty"
    exit 1
  fi
  mkdir -p "$DATA_ROOT"
  rclone sync "$EXTERNAL_REMOTE" "$DATA_ROOT" --create-empty-src-dirs | tee -a "$EXTERNAL_LOG"
  echo "[OK] NAS data pulled from external remote"
else
  echo "[SKIP] External datakeeper is disabled"
fi
EOF
chmod 755 "$EXTERNAL_PULL"

cat > "$START_TUNNEL" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
set -e
if [ -z "$RTUN_GATEWAY" ] || [ -z "$RTUN_KEY" ]; then
  echo "[SKIP] RTUN gateway/key not set. Tunnel not started."
  exit 0
fi
if ! command -v rtun >/dev/null 2>&1; then
  echo "[ERROR] rtun binary not installed"
  exit 1
fi
pkill -f "rtun" >/dev/null 2>&1 || true
cd "$NAS_ROOT"
nohup rtun >> "$TUNNEL_LOG" 2>&1 &
sleep 3
if pgrep -f "rtun" >/dev/null 2>&1; then
  echo "[OK] Reverse tunnel client started"
else
  echo "[WARN] Tunnel start could not be confirmed"
fi
EOF
chmod 755 "$START_TUNNEL"

cat > "$NAS_COMMAND" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
set -e

NAS_ROOT="$HOME/cellhasher-nas"
INSTALL_NAS="$NAS_ROOT/install_nas.sh"
START_NAS="$NAS_ROOT/start_nas.sh"
START_TUNNEL="$NAS_ROOT/start_tunnel.sh"
STOP_NAS="$NAS_ROOT/stop_nas.sh"
STATUS_NAS="$NAS_ROOT/status_nas.sh"
CONFIG_PATH="$NAS_ROOT/webdav.yml"
RTUN_CONFIG="$NAS_ROOT/rtun.yml"
NAS_LOG="$NAS_ROOT/webdav.log"
TUNNEL_LOG="$NAS_ROOT/rtun.log"
DATA_ROOT="$NAS_ROOT/data"
EXTERNAL_ENV="$NAS_ROOT/external.env"
EXTERNAL_PUSH="$NAS_ROOT/external_push.sh"
EXTERNAL_PULL="$NAS_ROOT/external_pull.sh"
EXTERNAL_INFO="$NAS_ROOT/external_info.sh"
EXTERNAL_LOG="$NAS_ROOT/external.log"
PORT="6065"
ADMIN_USER="admin"
ADMIN_PASS="change-me-admin"
UPLOAD_USER="uploader"
UPLOAD_PASS="change-me-upload"
READONLY_USER="viewer"
READONLY_PASS="change-me-viewer"
EXTERNAL_MODE="none"
EXTERNAL_PATH=""
EXTERNAL_REMOTE=""

line() {
  printf '%s\n' "------------------------------------------------------------"
}

pause() {
  printf '\nPress ENTER to continue...'
  read -r _ || true
}

show_message() {
  clear
  line
  echo "$1"
  line
}

prompt_with_default() {
  local label="$1"
  local current="$2"
  local value=""
  printf '%s [%s]: ' "$label" "$current"
  read -r value || value=""
  if [ -n "$value" ]; then
    printf '%s' "$value"
  else
    printf '%s' "$current"
  fi
}

write_webdav_config() {
  mkdir -p "$DATA_ROOT/public" "$DATA_ROOT/uploads" "$DATA_ROOT/admin"
  mkdir -p "$DATA_ROOT/users/$ADMIN_USER" "$DATA_ROOT/users/$UPLOAD_USER" "$DATA_ROOT/users/$READONLY_USER"
  cat > "$CONFIG_PATH" <<CFG
address: 0.0.0.0
port: $PORT
prefix: /
debug: false
directory: $DATA_ROOT
permissions: R
users:
  - username: $ADMIN_USER
    password: $ADMIN_PASS
    directory: $DATA_ROOT
    permissions: CRUD
  - username: $UPLOAD_USER
    password: $UPLOAD_PASS
    directory: $DATA_ROOT
    permissions: R
    rules:
      - path: /uploads/
        permissions: CRUD
      - path: /public/
        permissions: R
      - path: /admin/
        permissions: none
      - path: /users/
        permissions: none
  - username: $READONLY_USER
    password: $READONLY_PASS
    directory: $DATA_ROOT/public
    permissions: R
CFG
}

write_external_config() {
  cat > "$EXTERNAL_ENV" <<CFG
EXTERNAL_MODE=$EXTERNAL_MODE
EXTERNAL_PATH=$EXTERNAL_PATH
EXTERNAL_REMOTE=$EXTERNAL_REMOTE
CFG
}

edit_port() {
  load_runtime_state
  PORT=$(prompt_with_default "WebDAV port" "$PORT")
  write_webdav_config
  show_message "Port updated to $PORT"
  pause
}

edit_external_target() {
  load_runtime_state
  clear
  line
  echo "Configure external datakeeper"
  line
  echo "1. Disable"
  echo "2. Folder path"
  echo "3. rclone remote"
  printf '\nSelect [1-3]: '
  read -r choice || choice=""
  case "$choice" in
    1)
      EXTERNAL_MODE="none"
      EXTERNAL_PATH=""
      EXTERNAL_REMOTE=""
      ;;
    2)
      EXTERNAL_MODE="folder"
      EXTERNAL_PATH=$(prompt_with_default "Folder path" "${EXTERNAL_PATH:-/storage/emulated/0/NAS-backup}")
      EXTERNAL_REMOTE=""
      ;;
    3)
      EXTERNAL_MODE="rclone"
      EXTERNAL_REMOTE=$(prompt_with_default "rclone remote" "${EXTERNAL_REMOTE:-myremote:android-nas}")
      EXTERNAL_PATH=""
      ;;
    *)
      show_message "Invalid external datakeeper selection"
      pause
      return 0
      ;;
  esac
  write_external_config
  show_message "External datakeeper config updated"
  pause
}

edit_users() {
  load_runtime_state
  clear
  line
  echo "Edit NAS users"
  line
  ADMIN_USER=$(prompt_with_default "Admin username" "$ADMIN_USER")
  ADMIN_PASS=$(prompt_with_default "Admin password" "$ADMIN_PASS")
  UPLOAD_USER=$(prompt_with_default "Upload username" "$UPLOAD_USER")
  UPLOAD_PASS=$(prompt_with_default "Upload password" "$UPLOAD_PASS")
  READONLY_USER=$(prompt_with_default "Read-only username" "$READONLY_USER")
  READONLY_PASS=$(prompt_with_default "Read-only password" "$READONLY_PASS")
  write_webdav_config
  show_message "Users and passwords updated"
  pause
}

load_runtime_state() {
  PORT="6065"
  ADMIN_USER="admin"
  ADMIN_PASS="change-me-admin"
  UPLOAD_USER="uploader"
  UPLOAD_PASS="change-me-upload"
  READONLY_USER="viewer"
  READONLY_PASS="change-me-viewer"
  EXTERNAL_MODE="none"
  EXTERNAL_PATH=""
  EXTERNAL_REMOTE=""

  if [ -f "$CONFIG_PATH" ]; then
    PORT=$(sed -n 's/^port: \(.*\)$/\1/p' "$CONFIG_PATH" | head -n1)
    [ -z "$PORT" ] && PORT="6065"
    ADMIN_USER=$(sed -n 's/^  - username: \(.*\)$/\1/p' "$CONFIG_PATH" | sed -n '1p')
    ADMIN_PASS=$(sed -n 's/^    password: \(.*\)$/\1/p' "$CONFIG_PATH" | sed -n '1p')
    UPLOAD_USER=$(sed -n 's/^  - username: \(.*\)$/\1/p' "$CONFIG_PATH" | sed -n '2p')
    UPLOAD_PASS=$(sed -n 's/^    password: \(.*\)$/\1/p' "$CONFIG_PATH" | sed -n '2p')
    READONLY_USER=$(sed -n 's/^  - username: \(.*\)$/\1/p' "$CONFIG_PATH" | sed -n '3p')
    READONLY_PASS=$(sed -n 's/^    password: \(.*\)$/\1/p' "$CONFIG_PATH" | sed -n '3p')
    [ -z "$ADMIN_USER" ] && ADMIN_USER="admin"
    [ -z "$ADMIN_PASS" ] && ADMIN_PASS="change-me-admin"
    [ -z "$UPLOAD_USER" ] && UPLOAD_USER="uploader"
    [ -z "$UPLOAD_PASS" ] && UPLOAD_PASS="change-me-upload"
    [ -z "$READONLY_USER" ] && READONLY_USER="viewer"
    [ -z "$READONLY_PASS" ] && READONLY_PASS="change-me-viewer"
  fi

  if [ -f "$EXTERNAL_ENV" ]; then
    # shellcheck disable=SC1090
    . "$EXTERNAL_ENV"
    EXTERNAL_MODE="${EXTERNAL_MODE:-none}"
    EXTERNAL_PATH="${EXTERNAL_PATH:-}"
    EXTERNAL_REMOTE="${EXTERNAL_REMOTE:-}"
  fi
}

get_device_ip() {
  local device_ip
  device_ip=$(ip addr show wlan0 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -1)
  if [ -z "$device_ip" ]; then
    device_ip=$(ip route 2>/dev/null | awk '/src/ {print $NF}' | head -1)
  fi
  if [ -z "$device_ip" ]; then
    device_ip="unknown"
  fi
  printf '%s' "$device_ip"
}

install_status() {
  load_runtime_state
  if [ -x "$PREFIX/bin/webdav" ]; then
    printf 'installed'
  else
    printf 'not installed'
  fi
}

webdav_status() {
  load_runtime_state
  if [ ! -x "$PREFIX/bin/webdav" ]; then
    printf 'not installed'
  elif pgrep -f "$PREFIX/bin/webdav --config $CONFIG_PATH" >/dev/null 2>&1; then
    printf 'running'
  else
    printf 'stopped'
  fi
}

tunnel_status() {
  load_runtime_state
  if [ ! -f "$RTUN_CONFIG" ]; then
    printf 'disabled'
  elif pgrep -f "rtun" >/dev/null 2>&1; then
    printf 'running'
  else
    printf 'stopped'
  fi
}

external_summary() {
  load_runtime_state
  case "$EXTERNAL_MODE" in
    folder)
      printf 'folder -> %s' "${EXTERNAL_PATH:-unset}"
      ;;
    rclone)
      printf 'rclone -> %s' "${EXTERNAL_REMOTE:-unset}"
      ;;
    *)
      printf 'disabled'
      ;;
  esac
}

show_dashboard() {
  local device_ip
  load_runtime_state
  device_ip=$(get_device_ip)
  clear
  line
  echo "Android NAS Hub"
  line
  echo "Install     : $(install_status)"
  echo "WebDAV      : $(webdav_status)"
  echo "Tunnel      : $(tunnel_status)"
  echo "Port        : $PORT"
  echo "LAN URL     : http://$device_ip:$PORT/"
  echo "Data root   : $DATA_ROOT"
  echo "Config      : $CONFIG_PATH"
  echo "External    : $(external_summary)"
}

show_users() {
  load_runtime_state
  clear
  line
  echo "NAS users"
  line
  echo "$ADMIN_USER    -> full access"
  echo "$UPLOAD_USER   -> read all + write /uploads"
  echo "$READONLY_USER -> read-only /public"
}

show_runtime_config() {
  load_runtime_state
  clear
  line
  echo "NAS runtime config"
  line
  echo "Port        : $PORT"
  echo "Data root   : $DATA_ROOT"
  echo "WebDAV cfg  : $CONFIG_PATH"
  if [ -f "$RTUN_CONFIG" ]; then
    echo "Tunnel cfg  : $RTUN_CONFIG"
  else
    echo "Tunnel cfg  : not configured"
  fi
  if [ -f "$EXTERNAL_ENV" ]; then
    echo "External cfg: $EXTERNAL_ENV"
  fi
}

show_logs() {
  load_runtime_state
  clear
  line
  echo "NAS logs"
  line
  echo "== WebDAV log =="
  tail -n 40 "$NAS_LOG" 2>/dev/null || echo "No WebDAV log yet"
  echo ""
  echo "== Tunnel log =="
  tail -n 40 "$TUNNEL_LOG" 2>/dev/null || echo "No tunnel log yet"
  echo ""
  echo "== External log =="
  tail -n 40 "$EXTERNAL_LOG" 2>/dev/null || echo "No external sync log yet"
}

show_config() {
  load_runtime_state
  clear
  line
  echo "WebDAV config"
  line
  if [ -f "$CONFIG_PATH" ]; then
    cat "$CONFIG_PATH"
  else
    echo "WebDAV config not found"
  fi
  echo ""
  line
  echo "Tunnel config"
  line
  if [ -f "$RTUN_CONFIG" ]; then
    cat "$RTUN_CONFIG"
  else
    echo "Tunnel not configured"
  fi
}

users_menu() {
  while true; do
    load_runtime_state
    clear
    line
    echo "Users menu"
    line
    echo "1. Show user overview"
    echo "2. Show WebDAV user config"
    echo "3. Edit users and passwords"
    echo "4. Open users home folders"
    echo "0. Back"
    printf '\nSelect [1-4, 0]: '
    read -r choice || choice=""
    case "$choice" in
      1) show_users; pause ;;
      2)
        clear
        line
        echo "WebDAV user config"
        line
        if [ -f "$CONFIG_PATH" ]; then
          sed -n '/^users:/,$p' "$CONFIG_PATH"
        else
          echo "Config file not found"
        fi
        pause
        ;;
      3) edit_users ;;
      4)
        clear
        line
        echo "User home folders"
        line
        ls -la "$DATA_ROOT/users" 2>/dev/null || echo "No user folders yet"
        pause
        ;;
      0|b|B|q|Q|back|Back|exit|Exit) return 0 ;;
      *)
        show_message "Invalid users menu selection"
        pause
        ;;
    esac
  done
}

config_menu() {
  while true; do
    load_runtime_state
    clear
    line
    echo "Config menu"
    line
    echo "1. Show runtime config summary"
    echo "2. Show full WebDAV config"
    echo "3. Change WebDAV port"
    echo "4. Show tunnel config"
    echo "5. Configure external datakeeper"
    echo "6. Show external datakeeper config"
    echo "0. Back"
    printf '\nSelect [1-6, 0]: '
    read -r choice || choice=""
    case "$choice" in
      1) show_runtime_config; pause ;;
      2) show_config; pause ;;
      3) edit_port ;;
      4)
        clear
        line
        echo "Tunnel config"
        line
        if [ -f "$RTUN_CONFIG" ]; then
          cat "$RTUN_CONFIG"
        else
          echo "Tunnel not configured"
        fi
        pause
        ;;
      5) edit_external_target ;;
      6)
        clear
        line
        echo "External datakeeper config"
        line
        if [ -f "$EXTERNAL_ENV" ]; then
          cat "$EXTERNAL_ENV"
        else
          echo "External config not found"
        fi
        pause
        ;;
      0|b|B|q|Q|back|Back|exit|Exit) return 0 ;;
      *)
        show_message "Invalid config menu selection"
        pause
        ;;
    esac
  done
}

external_menu() {
  while true; do
    load_runtime_state
    clear
    line
    echo "External datakeeper menu"
    line
    echo "1. Show external target info"
    echo "2. Push NAS data to external target"
    echo "3. Pull data from external target"
    echo "0. Back"
    printf '\nSelect [1-3, 0]: '
    read -r choice || choice=""
    case "$choice" in
      1) clear; bash "$EXTERNAL_INFO"; pause ;;
      2) clear; bash "$EXTERNAL_PUSH"; pause ;;
      3) clear; bash "$EXTERNAL_PULL"; pause ;;
      0|b|B|q|Q|back|Back|exit|Exit) return 0 ;;
      *)
        show_message "Invalid external menu selection"
        pause
        ;;
    esac
  done
}

main_menu() {
  while true; do
    load_runtime_state
    show_dashboard
    printf '\n'
    line
    echo "1. Install or reinstall NAS"
    echo "2. Start NAS"
    echo "3. Stop NAS"
    echo "4. Restart NAS"
    echo "5. Show status"
    echo "6. Show info"
    echo "7. Config menu"
    echo "8. Users menu"
    echo "9. Start tunnel"
    echo "10. External datakeepers"
    echo "11. Show logs"
    echo "12. Refresh"
    echo "13. Exit"
    printf '\nSelect [1-13]: '
    read -r choice || choice=""

    case "$choice" in
      1) clear; bash "$INSTALL_NAS"; pause ;;
      2) clear; bash "$START_NAS" || true; pause ;;
      3) clear; bash "$STOP_NAS" || true; pause ;;
      4) clear; bash "$STOP_NAS" || true; sleep 1; bash "$START_NAS" || true; pause ;;
      5) clear; bash "$STATUS_NAS" || true; pause ;;
      6) show_dashboard; pause ;;
      7) config_menu ;;
      8) users_menu ;;
      9) clear; bash "$START_TUNNEL" || true; pause ;;
      10) external_menu ;;
      11) show_logs; pause ;;
      12) ;;
      13|0|b|B|q|Q|back|Back|exit|Exit) exit 0 ;;
      *)
        show_message "Invalid main menu selection"
        pause
        ;;
    esac
  done
}

case "${1:-menu}" in
  menu) main_menu ;;
  install) bash "$INSTALL_NAS" ;;
  start) bash "$START_NAS" ;;
  stop) bash "$STOP_NAS" ;;
  restart) bash "$STOP_NAS"; sleep 1; bash "$START_NAS" ;;
  status) bash "$STATUS_NAS" ;;
  info) show_dashboard ;;
  config) show_config ;;
  tunnel) bash "$START_TUNNEL" ;;
  logs) show_logs ;;
  users) show_users ;;
  external-info) bash "$EXTERNAL_INFO" ;;
  external-push) bash "$EXTERNAL_PUSH" ;;
  external-pull) bash "$EXTERNAL_PULL" ;;
  help|--help|-h)
    echo "Usage: nas [menu|start|stop|restart|status|info|config|tunnel|logs|users|external-info|external-push|external-pull]"
    ;;
  *)
    echo "[ERROR] Unknown subcommand: $1"
    exit 1
    ;;
esac
EOF
chmod 755 "$NAS_COMMAND"
echo "[2/3] NAS hub scripts created"
echo ""

DEVICE_IP=$(ip addr show wlan0 2>/dev/null | awk '/inet / {{print $2}}' | cut -d/ -f1 | head -1)
if [ -z "$DEVICE_IP" ]; then
  DEVICE_IP=$(ip route 2>/dev/null | awk '/src/ {{print $NF}}' | head -1)
fi
if [ -z "$DEVICE_IP" ]; then
  DEVICE_IP="unknown"
fi

echo "=============================================="
echo "   Bootstrap Complete"
echo "=============================================="
echo "Local WebDAV URL : http://$DEVICE_IP:$PORT/"
echo "Local storage    : $DATA_ROOT"
echo "NAS config       : $CONFIG_PATH"
echo "Install status   : choose 'Install or reinstall NAS' in the menu if needed"
echo "Users:"
echo "  admin    -> full access to all folders"
echo "  uploader -> read all + write only /uploads"
echo "  viewer   -> read-only /public"
echo ""
echo "Passwords:"
echo "  $ADMIN_USER / $ADMIN_PASS"
echo "  $UPLOAD_USER / $UPLOAD_PASS"
echo "  $READONLY_USER / $READONLY_PASS"
echo ""
echo "Manual start commands:"
echo "  bash $START_NAS"
echo "  bash $START_TUNNEL"
echo "Hub menu         : nas"
echo ""
if [ -n "$RTUN_GATEWAY" ] && [ -n "$RTUN_KEY" ]; then
  echo "Tunnel requested : yes"
  echo "Gateway          : $RTUN_GATEWAY"
  echo "Remote port      : $RTUN_REMOTE_PORT"
else
  echo "Tunnel requested : no"
fi
if [ "$EXTERNAL_MODE" = "folder" ]; then
  echo "External keeper  : folder"
  echo "External path    : $EXTERNAL_PATH"
elif [ "$EXTERNAL_MODE" = "rclone" ]; then
  echo "External keeper  : rclone"
  echo "External remote  : $EXTERNAL_REMOTE"
else
  echo "External keeper  : none"
fi
echo ""
echo "[3/3] Opening NAS hub..."
exec "$NAS_COMMAND"
"""


def create_termux_script():
    script = TERMUX_SETUP_SCRIPT_TEMPLATE
    replacements = {
        "{nas_port}": shell_quote(CONFIG["nas_port"]),
        "{admin_user}": shell_quote(CONFIG["nas_admin_user"]),
        "{admin_pass}": shell_quote(CONFIG["nas_admin_password"]),
        "{upload_user}": shell_quote(CONFIG["nas_upload_user"]),
        "{upload_pass}": shell_quote(CONFIG["nas_upload_password"]),
        "{readonly_user}": shell_quote(CONFIG["nas_readonly_user"]),
        "{readonly_pass}": shell_quote(CONFIG["nas_readonly_password"]),
        "{rtun_gateway}": shell_quote(CONFIG["rtun_gateway"]),
        "{rtun_key}": shell_quote(CONFIG["rtun_key"]),
        "{rtun_remote_port}": shell_quote(CONFIG["rtun_remote_port"]),
        "{external_mode}": shell_quote(CONFIG["nas_external_mode"]),
        "{external_path}": shell_quote(CONFIG["nas_external_path"]),
        "{external_remote}": shell_quote(CONFIG["nas_external_remote"]),
    }
    for token, value in replacements.items():
        script = script.replace(token, value)
    return script


def setup_ssl_context():
    try:
        if hasattr(ssl, "_create_unverified_context"):
            return ssl._create_unverified_context()
        return ssl.create_default_context()
    except Exception:
        return None


def run_adb(args, *, text=False, timeout=120):
    kwargs = {
        "capture_output": True,
        "timeout": timeout,
        "text": text,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run([ADB] + args, **kwargs)


def get_latest_termux_apk():
    print("[*] Fetching latest Termux release...")
    request = urllib.request.Request(
        TERMUX_RELEASE_API,
        headers={"User-Agent": "Cellhasher-Android-NAS/1.0"},
    )
    ctx = setup_ssl_context()
    with urllib.request.urlopen(request, timeout=30, context=ctx) as response:
        release = json.loads(response.read().decode("utf-8"))

    for asset in release.get("assets", []):
        name = asset.get("name", "").lower()
        if "arm64-v8a" in name and name.endswith(".apk"):
            return asset["browser_download_url"], asset["name"]

    raise RuntimeError("Could not locate latest Termux arm64-v8a APK")


def download_apk(url, name):
    target = os.path.join(tempfile.gettempdir(), name)
    print(f"[*] Downloading {name}...")
    request = urllib.request.Request(url, headers={"User-Agent": "Cellhasher-Android-NAS/1.0"})
    ctx = setup_ssl_context()

    with urllib.request.urlopen(request, timeout=180, context=ctx) as response, open(target, "wb") as handle:
        while True:
            chunk = response.read(8192)
            if not chunk:
                break
            handle.write(chunk)

    return target


def check_termux_installed(device_id):
    result = run_adb(["-s", device_id, "shell", "pm", "list", "packages", "com.termux"], text=True, timeout=30)
    return "com.termux" in result.stdout


def install_termux(device_id, apk_path):
    print(f"[{device_id}] Installing Termux...")
    result = run_adb(["-s", device_id, "install", "-r", apk_path], text=True, timeout=180)
    combined = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 0 or "Success" in combined:
        print(f"[{device_id}] [OK] Termux installed")
        return True
    print(f"[{device_id}] [ERROR] Termux install failed: {combined.strip()}")
    return False


def grant_termux_permissions(device_id):
    permissions = [
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.INTERNET",
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.WAKE_LOCK",
        "android.permission.FOREGROUND_SERVICE",
    ]
    for permission in permissions:
        try:
            run_adb(["-s", device_id, "shell", "pm", "grant", "com.termux", permission], timeout=30)
        except Exception:
            pass


def deploy_to_device(device_id, script_path):
    try:
        print(f"[{device_id}] Preparing deployment...")

        if not check_termux_installed(device_id):
            return f"[{device_id}] NEEDS_TERMUX"

        run_adb(["-s", device_id, "shell", "am", "force-stop", "com.termux"], timeout=30)
        time.sleep(1)

        device_script = "/data/local/tmp/cellhasher_nas_setup.sh"
        pushed = run_adb(["-s", device_id, "push", script_path, device_script], text=True, timeout=120)
        if pushed.returncode != 0:
            return f"[{device_id}] Error: failed to push setup script: {pushed.stderr}"

        run_adb(["-s", device_id, "shell", "chmod", "755", device_script], timeout=30)
        grant_termux_permissions(device_id)

        print(f"[{device_id}] Launching Termux...")
        launch_result = run_adb(
            ["-s", device_id, "shell", "am", "start", "-n", "com.termux/com.termux.app.TermuxActivity"],
            text=True,
            timeout=30,
        )
        launch_output = ((launch_result.stdout or "") + (launch_result.stderr or "")).strip()
        if launch_result.returncode != 0:
            fallback_result = run_adb(
                ["-s", device_id, "shell", "am", "start", "-n", "com.termux/.app.TermuxActivity"],
                text=True,
                timeout=30,
            )
            fallback_output = ((fallback_result.stdout or "") + (fallback_result.stderr or "")).strip()
            if fallback_result.returncode != 0:
                return f"[{device_id}] Error: failed to open Termux ({launch_output} | {fallback_output})"
        time.sleep(10)

        cmd = f"bash%s{device_script}"
        run_adb(["-s", device_id, "shell", "input", "text", cmd], timeout=30)
        time.sleep(0.5)
        run_adb(["-s", device_id, "shell", "input", "keyevent", "66"], timeout=30)

        return f"[{device_id}] Success - NAS deployment started in Termux"
    except Exception as exc:
        return f"[{device_id}] Error: {exc}"


def ensure_termux_available(devices):
    needs_termux = [device for device in devices if not check_termux_installed(device)]
    if not needs_termux:
        print("[OK] Termux already installed on all selected devices")
        return devices

    print(f"[*] Termux missing on {len(needs_termux)} device(s)")
    apk_url, apk_name = get_latest_termux_apk()
    apk_path = download_apk(apk_url, apk_name)

    ready = [device for device in devices if device not in needs_termux]
    try:
        with ThreadPoolExecutor(max_workers=max(1, len(needs_termux))) as executor:
            futures = {executor.submit(install_termux, device, apk_path): device for device in needs_termux}
            for future in as_completed(futures):
                device = futures[future]
                if future.result():
                    ready.append(device)
    finally:
        if os.path.exists(apk_path):
            os.unlink(apk_path)

    if ready:
        print("[*] Waiting 5 seconds for installed Termux apps to settle...")
        time.sleep(5)
    return ready


def main():
    print("=" * 60)
    print("   Android NAS (WebDAV + Optional Reverse Tunnel)")
    print("   Phone-side interactive NAS hub")
    print("=" * 60)
    print()

    if not DEVICES:
        print("[ERROR] No devices found in environment variable 'devices'")
        print("[!] Select devices in Cellhasher before running this script")
        return

    print(f"[*] Target devices: {len(DEVICES)}")
    for index, device in enumerate(DEVICES, 1):
        print(f"    {index}. {device}")
    print()
    print(f"[*] WebDAV port: {CONFIG['nas_port']}")
    print(f"[*] Admin user: {CONFIG['nas_admin_user']}")
    print(f"[*] Upload user: {CONFIG['nas_upload_user']}")
    print(f"[*] Read-only user: {CONFIG['nas_readonly_user']}")
    print(f"[*] Tunnel enabled: {'yes' if CONFIG['rtun_gateway'] and CONFIG['rtun_key'] else 'no'}")
    if CONFIG["rtun_gateway"]:
        print(f"[*] Tunnel gateway: {CONFIG['rtun_gateway']}")
    if CONFIG["rtun_remote_port"]:
        print(f"[*] Tunnel remote port: {CONFIG['rtun_remote_port']}")
    print(f"[*] External datakeeper mode: {CONFIG['nas_external_mode']}")
    if CONFIG["nas_external_path"]:
        print(f"[*] External path: {CONFIG['nas_external_path']}")
    if CONFIG["nas_external_remote"]:
        print(f"[*] External remote: {CONFIG['nas_external_remote']}")
    print()

    script_body = create_termux_script()
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", delete=False, suffix=".sh") as handle:
        handle.write(script_body)
        local_script_path = handle.name

    try:
        ready_devices = ensure_termux_available(DEVICES)
        if not ready_devices:
            print("[ERROR] No devices are ready for deployment")
            return

        print()
        print("=" * 60)
        print(f"[*] Starting NAS deployment on {len(ready_devices)} device(s)...")
        print("=" * 60)

        results = []
        with ThreadPoolExecutor(max_workers=max(1, len(ready_devices))) as executor:
            futures = {
                executor.submit(deploy_to_device, device, local_script_path): device
                for device in ready_devices
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                print(result)

        print()
        print("=" * 60)
        print("   Summary")
        print("=" * 60)
        started = sum("Success" in result for result in results)
        print(f"[*] Devices processed: {len(ready_devices)}")
        print(f"[*] Deployments started: {started}")
        print("[INFO] Cellhasher only pushes and opens the phone-side Termux script.")
        print("[INFO] All interactive control now happens on the Android device.")
        print("[INFO] After launch, use the NAS hub menu in Termux on the phone.")
        print()
        print("Environment variables supported:")
        print("  nas_port")
        print("  nas_admin_user / nas_admin_password")
        print("  nas_upload_user / nas_upload_password")
        print("  nas_readonly_user / nas_readonly_password")
        print("  rtun_gateway / rtun_key / rtun_remote_port")
        print("  nas_external_mode (none|folder|rclone)")
        print("  nas_external_path")
        print("  nas_external_remote")
    finally:
        if os.path.exists(local_script_path):
            os.unlink(local_script_path)


if __name__ == "__main__":
    main()
