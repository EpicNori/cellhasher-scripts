#!/usr/bin/env python3
"""
Cellhasher Android NAS Hub
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


CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
ADB = os.environ.get("adb_path", "adb")
devices = [device for device in os.environ.get("devices", "").split() if device]
TERMUX_RELEASES_API = "https://api.github.com/repos/termux/termux-app/releases/latest"

SCRIPT_META = {
    "id": "android-nas-hub-v1",
    "name": "Android NAS Hub",
    "description": "Interactive Android NAS management hub for Cellhasher. Installs and manages a small multi-user WebDAV NAS in Termux, supports tunnel access, and syncs with external datakeeper targets.",
    "category": "Storage",
    "type": "python",
    "version": "1.0.0",
    "author": "Cellhasher Team",
    "difficulty": "Advanced",
    "estimatedTime": "10-20 min",
    "tags": ["android", "nas", "termux", "webdav", "dufs", "localtunnel", "rclone", "storage", "backup"],
    "effects": {
        "power": {"reboot": False, "shutdown": False},
        "security": {"modifiesLockScreen": False},
    },
    "estimatedDurationSec": 1200,
    "downloads": 0,
    "rating": 5.0,
    "lastUpdated": "2026-03-21",
}

TERMUX_HUB_SCRIPT = r"""
#!/data/data/com.termux/files/usr/bin/bash
set +e

BASE_DIR="$HOME/cellhasher-nas"
BIN_DIR="$BASE_DIR/bin"
ETC_DIR="$BASE_DIR/etc"
DATA_DIR="$BASE_DIR/data"
LOG_DIR="$BASE_DIR/logs"
STATE_DIR="$BASE_DIR/state"
TMP_DIR="$BASE_DIR/tmp"
RUNTIME_ENV="$ETC_DIR/runtime.env"
DUFS_BIN="$BIN_DIR/webdav"
DUFS_CONFIG="$ETC_DIR/webdav.yaml"
DUFS_PID_FILE="$STATE_DIR/webdav.pid"
DUFS_LOG_FILE="$LOG_DIR/webdav.log"
INSTALL_LOG_FILE="$LOG_DIR/install.log"
SYNC_LOG_FILE="$LOG_DIR/sync.log"
TUNNEL_PID_FILE="$STATE_DIR/tunnel.pid"
TUNNEL_LOG_FILE="$LOG_DIR/tunnel.log"
TUNNEL_STATUS_FILE="$STATE_DIR/tunnel.status"
TUNNEL_TOOL_FILE="$STATE_DIR/tunnel.tool"
NPM_PREFIX="$HOME/.npm-global"
LT_BIN="$NPM_PREFIX/bin/lt"
SERVER_URL=""

ensure_base_dirs() {
    mkdir -p "$BASE_DIR" "$BIN_DIR" "$ETC_DIR" "$DATA_DIR" "$LOG_DIR" "$STATE_DIR" "$TMP_DIR"
}

ensure_base_dirs

cecho() {
    local color="$1"
    shift
    printf '\033[%sm%s\033[0m\n' "$color" "$*"
}

line() {
    printf '%s\n' "------------------------------------------------------------"
}

pause() {
    printf '\nPress ENTER to continue...'
    read -r _ || true
}

clear_log_if_huge() {
    local file="$1"
    if [ -f "$file" ]; then
        local size
        size=$(wc -c < "$file" 2>/dev/null || printf '0')
        if [ "${size:-0}" -gt 1048576 ]; then
            tail -n 400 "$file" > "$file.tmp" 2>/dev/null && mv "$file.tmp" "$file"
        fi
    fi
}

safe_value() {
    printf "%s" "$1" | sed "s/'/'\\\\''/g"
}

yaml_value() {
    printf "%s" "$1" | sed "s/'/''/g"
}

load_runtime() {
    ensure_base_dirs
    NAS_PORT="8080"
    NAS_BIND="0.0.0.0"
    NAS_ROOT="$DATA_DIR/storage"
    EXTERNAL_MODE="none"
    EXTERNAL_PATH=""
    RCLONE_REMOTE=""
    TUNNEL_PROVIDER="localtunnel"
    TUNNEL_HOST="https://localtunnel.app"
    TUNNEL_LOCAL_HOST="127.0.0.1"
    TUNNEL_SUBDOMAIN=""
    TUNNEL_URL=""
    DUFS_VERSION=""
    LAST_INSTALL_AT=""
    ADMIN_USER="admin"
    ADMIN_PASS="admin123"
    UPLOADER_USER="uploader"
    UPLOADER_PASS="upload123"
    VIEWER_USER="viewer"
    VIEWER_PASS="viewer123"

    if [ -f "$RUNTIME_ENV" ]; then
        . "$RUNTIME_ENV"
    fi

    [ -z "$NAS_ROOT" ] && NAS_ROOT="$DATA_DIR/storage"
}

save_runtime() {
    ensure_base_dirs
    cat > "$RUNTIME_ENV" <<EOF
NAS_PORT='$(safe_value "$NAS_PORT")'
NAS_BIND='$(safe_value "$NAS_BIND")'
NAS_ROOT='$(safe_value "$NAS_ROOT")'
EXTERNAL_MODE='$(safe_value "$EXTERNAL_MODE")'
EXTERNAL_PATH='$(safe_value "$EXTERNAL_PATH")'
RCLONE_REMOTE='$(safe_value "$RCLONE_REMOTE")'
TUNNEL_PROVIDER='$(safe_value "$TUNNEL_PROVIDER")'
TUNNEL_HOST='$(safe_value "$TUNNEL_HOST")'
TUNNEL_LOCAL_HOST='$(safe_value "$TUNNEL_LOCAL_HOST")'
TUNNEL_SUBDOMAIN='$(safe_value "$TUNNEL_SUBDOMAIN")'
TUNNEL_URL='$(safe_value "$TUNNEL_URL")'
DUFS_VERSION='$(safe_value "$DUFS_VERSION")'
LAST_INSTALL_AT='$(safe_value "$LAST_INSTALL_AT")'
ADMIN_USER='$(safe_value "$ADMIN_USER")'
ADMIN_PASS='$(safe_value "$ADMIN_PASS")'
UPLOADER_USER='$(safe_value "$UPLOADER_USER")'
UPLOADER_PASS='$(safe_value "$UPLOADER_PASS")'
VIEWER_USER='$(safe_value "$VIEWER_USER")'
VIEWER_PASS='$(safe_value "$VIEWER_PASS")'
EOF
}

ensure_storage_layout() {
    mkdir -p "$NAS_ROOT" "$NAS_ROOT/shared" "$NAS_ROOT/shared/public" "$NAS_ROOT/shared/upload" "$NAS_ROOT/users" "$NAS_ROOT/users/$ADMIN_USER" "$NAS_ROOT/users/$UPLOADER_USER" "$NAS_ROOT/users/$VIEWER_USER"
    [ -f "$NAS_ROOT/README.txt" ] || cat > "$NAS_ROOT/README.txt" <<EOF
Cellhasher Android NAS

shared/public   : read-mostly shared files
shared/upload   : uploader drop area
users/*         : per-user folders
EOF
}

validate_simple_token() {
    printf "%s" "$1" | grep -Eq '^[A-Za-z0-9._@-]{1,32}$'
}

get_device_ip() {
    local ip_addr
    ip_addr=$(ip addr show wlan0 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -n1)
    if [ -z "$ip_addr" ]; then
        ip_addr=$(ip route 2>/dev/null | awk '/src/ {print $NF}' | head -n1)
    fi
    if [ -z "$ip_addr" ]; then
        ip_addr="Unknown"
    fi
    printf '%s' "$ip_addr"
}

nas_binary_installed() {
    [ -x "$DUFS_BIN" ]
}

nas_config_present() {
    [ -f "$DUFS_CONFIG" ]
}

nas_config_valid() {
    nas_config_present || return 1
    grep -q '^address:' "$DUFS_CONFIG" 2>/dev/null || return 1
    grep -q '^port:' "$DUFS_CONFIG" 2>/dev/null || return 1
    grep -q '^directory:' "$DUFS_CONFIG" 2>/dev/null || return 1
    grep -q '^users:' "$DUFS_CONFIG" 2>/dev/null || return 1
}

nas_installed() {
    nas_binary_installed && nas_config_valid
}

nas_install_state() {
    if nas_installed; then
        printf '%s' 'installed'
    elif nas_binary_installed && nas_config_present; then
        printf '%s' 'partial (config invalid)'
    elif nas_binary_installed; then
        printf '%s' 'partial (binary only)'
    elif nas_config_present; then
        printf '%s' 'partial (config only)'
    else
        printf '%s' 'not installed'
    fi
}

nas_is_running() {
    local pid
    if [ ! -f "$DUFS_PID_FILE" ]; then
        return 1
    fi
    pid=$(cat "$DUFS_PID_FILE" 2>/dev/null || true)
    if [ -z "$pid" ]; then
        rm -f "$DUFS_PID_FILE"
        return 1
    fi
    if kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    rm -f "$DUFS_PID_FILE"
    return 1
}

tunnel_is_running() {
    local pid
    if [ ! -f "$TUNNEL_PID_FILE" ]; then
        return 1
    fi
    pid=$(cat "$TUNNEL_PID_FILE" 2>/dev/null || true)
    if [ -z "$pid" ]; then
        rm -f "$TUNNEL_PID_FILE"
        return 1
    fi
    if kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    rm -f "$TUNNEL_PID_FILE"
    return 1
}

extract_tunnel_url() {
    if [ -f "$TUNNEL_STATUS_FILE" ]; then
        grep -Eo 'https://[^[:space:]]+' "$TUNNEL_STATUS_FILE" | tail -n1
        return
    fi
    if [ -f "$TUNNEL_LOG_FILE" ]; then
        grep -Eo 'https://[^[:space:]]+' "$TUNNEL_LOG_FILE" | tail -n1
    fi
}

dashboard_header() {
    load_runtime
    local ip_addr install_state run_state tunnel_state tunnel_url
    ip_addr=$(get_device_ip)
    install_state=$(nas_install_state)
    if nas_is_running; then run_state="running"; else run_state="stopped"; fi
    if tunnel_is_running; then tunnel_state="running"; else tunnel_state="stopped"; fi
    tunnel_url=$(extract_tunnel_url || true)
    [ -n "$tunnel_url" ] && TUNNEL_URL="$tunnel_url"
    save_runtime
    clear
    line
    echo "Cellhasher Android NAS Hub"
    line
    echo "NAS state    : $install_state / $run_state"
    echo "NAS root     : $NAS_ROOT"
    echo "WebDAV port  : $NAS_PORT"
    echo "LAN address  : http://$ip_addr:$NAS_PORT"
    echo "Tunnel       : $tunnel_state"
    if [ -n "$TUNNEL_URL" ]; then echo "Tunnel URL   : $TUNNEL_URL"; else echo "Tunnel URL   : not assigned"; fi
    echo "External     : ${EXTERNAL_MODE}${EXTERNAL_PATH:+ -> $EXTERNAL_PATH}${RCLONE_REMOTE:+ -> $RCLONE_REMOTE}"
    echo "Users        : $ADMIN_USER, $UPLOADER_USER, $VIEWER_USER"
    echo "Last install : ${LAST_INSTALL_AT:-never}"
}
show_status_screen() {
    dashboard_header
    printf '\n'
    line
    echo "Detailed status"
    line
    if nas_is_running; then echo "NAS PID      : $(cat "$DUFS_PID_FILE" 2>/dev/null)"; else echo "NAS PID      : not running"; fi
    if tunnel_is_running; then
        echo "Tunnel PID   : $(cat "$TUNNEL_PID_FILE" 2>/dev/null)"
        echo "Tunnel tool  : $(cat "$TUNNEL_TOOL_FILE" 2>/dev/null || echo unknown)"
    else
        echo "Tunnel PID   : not running"
        echo "Tunnel tool  : $(cat "$TUNNEL_TOOL_FILE" 2>/dev/null || echo not set)"
    fi
    if command -v curl >/dev/null 2>&1; then
        if curl -fsS -I "http://127.0.0.1:$NAS_PORT/" >/dev/null 2>&1; then echo "Loopback     : reachable"; else echo "Loopback     : not reachable"; fi
    else
        echo "Loopback     : curl not installed yet"
    fi
    echo "webdav bin   : $( [ -x "$DUFS_BIN" ] && printf yes || printf no )"
    echo "webdav conf  : $( [ -f "$DUFS_CONFIG" ] && printf yes || printf no )"
    echo "conf valid   : $( nas_config_valid && printf yes || printf no )"
}

show_info_screen() {
    dashboard_header
    printf '\n'
    line
    echo "Info"
    line
    echo "This phone exposes a small WebDAV NAS through the MIT-licensed hacdias/webdav server inside Termux."
    echo ""
    echo "Access layers:"
    echo "  admin    -> full read/write access to the whole NAS"
    echo "  uploader -> read/write on shared/upload and own user folder, read-only on shared/public"
    echo "  viewer   -> read-only on shared/public and own user folder"
}

ensure_base_packages() {
    ensure_base_dirs
    {
        echo "[$(date '+%F %T')] Updating Termux packages"
        pkg update -y || true
        yes '' | pkg upgrade -y 2>/dev/null || true
        echo "[$(date '+%F %T')] Installing required packages"
        pkg install -y curl jq tar gzip unzip procps psmisc rsync nodejs rclone termux-tools
        echo "[$(date '+%F %T')] Package step finished"
    } >> "$INSTALL_LOG_FILE" 2>&1
}

ensure_termux_storage_access() {
    if [ -d "$HOME/storage/shared" ]; then
        echo "Termux shared storage already available."
        return 0
    fi

    echo "Requesting Termux shared-storage setup..."
    echo "If Android shows a permission dialog, keep Termux open and tap Allow."
    termux-setup-storage >/dev/null 2>&1 &

    local wait_seconds
    for wait_seconds in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        if [ -d "$HOME/storage/shared" ]; then
            echo "Shared storage permission granted."
            return 0
        fi
        sleep 1
    done

    echo "Shared storage is still unavailable."
    echo "Continuing with app-private NAS storage only."
    echo "You can grant storage later in Termux by running: termux-setup-storage"
    return 1
}

install_dufs() {
    local release_json download_url archive_path extract_dir webdav_path version
    case "$(uname -m)" in
        aarch64|arm64) download_url="https://github.com/hacdias/webdav/releases/latest/download/linux-arm64-webdav.tar.gz" ;;
        *) cecho "31" "Unsupported device architecture for webdav: $(uname -m)"; return 1 ;;
    esac
    echo "[2/4] Fetching webdav release metadata..."
    release_json=$(curl -fsSL --connect-timeout 20 --max-time 60 --retry 2 "https://api.github.com/repos/hacdias/webdav/releases/latest" 2>> "$INSTALL_LOG_FILE") || true
    version=$(printf '%s' "$release_json" | jq -r '.tag_name // empty' 2>/dev/null | sed 's/^v//')
    [ -z "$version" ] && version="latest"
    archive_path="$TMP_DIR/webdav.tar.gz"
    extract_dir="$TMP_DIR/webdav-extract"
    rm -rf "$extract_dir"
    mkdir -p "$extract_dir"
    echo "[3/4] Downloading webdav $version..."
    echo "This can take a minute on mobile data or slow Wi-Fi."
    curl --progress-bar -fL --connect-timeout 20 --max-time 300 --retry 3 --retry-delay 2 "$download_url" -o "$archive_path" 2>> "$INSTALL_LOG_FILE" || { cecho "31" "Failed to download webdav."; return 1; }
    echo "[4/4] Unpacking and installing webdav..."
    tar -xzf "$archive_path" -C "$extract_dir" >> "$INSTALL_LOG_FILE" 2>&1 || { cecho "31" "Failed to unpack webdav."; return 1; }
    webdav_path=$(find "$extract_dir" -type f -name webdav | head -n1)
    if [ -z "$webdav_path" ]; then cecho "31" "webdav binary was not found after unpacking."; return 1; fi
    cp "$webdav_path" "$DUFS_BIN"
    chmod 755 "$DUFS_BIN"
    if ! "$DUFS_BIN" version >/dev/null 2>&1; then
        cecho "31" "webdav installed but does not run on this device."
        return 1
    fi
    DUFS_VERSION="$version"
    save_runtime
    cecho "32" "webdav $version installed."
}

write_dufs_config() {
    ensure_storage_layout
    cat > "$DUFS_CONFIG" <<EOF
address: $(yaml_value "$NAS_BIND")
port: $NAS_PORT
directory: $(yaml_value "$NAS_ROOT")
permissions: R
log:
  format: console
  colors: false
  outputs:
    - stderr
users:
  - username: $(yaml_value "$ADMIN_USER")
    password: $(yaml_value "$ADMIN_PASS")
    permissions: CRUD
  - username: $(yaml_value "$UPLOADER_USER")
    password: $(yaml_value "$UPLOADER_PASS")
    directory: $(yaml_value "$NAS_ROOT")
    permissions: none
    rules:
      - path: /shared/public/
        permissions: R
      - path: /shared/upload/
        permissions: CRUD
      - path: /users/$(yaml_value "$UPLOADER_USER")/
        permissions: CRUD
  - username: $(yaml_value "$VIEWER_USER")
    password: $(yaml_value "$VIEWER_PASS")
    directory: $(yaml_value "$NAS_ROOT")
    permissions: none
    rules:
      - path: /shared/public/
        permissions: R
      - path: /users/$(yaml_value "$VIEWER_USER")/
        permissions: R
EOF
}

install_or_reinstall_nas() {
    load_runtime
    dashboard_header
    printf '\nContinue? [Y/n]: '
    read -r answer || answer=""
    if [ -n "$answer" ] && ! printf '%s' "$answer" | grep -Eq '^[Yy]$'; then cecho "33" "Installation cancelled."; return 0; fi
    printf '\n'
    line
    echo "Installing NAS"
    line
    echo "[1/4] Preparing Termux packages..."
    ensure_base_packages
    if [ $? -ne 0 ]; then
        cecho "31" "Package preparation failed."
        [ -f "$INSTALL_LOG_FILE" ] && tail -n 40 "$INSTALL_LOG_FILE"
        return 1
    fi
    ensure_termux_storage_access || true
    if nas_is_running; then stop_nas >/dev/null 2>&1; fi
    install_dufs || {
        [ -f "$INSTALL_LOG_FILE" ] && tail -n 40 "$INSTALL_LOG_FILE"
        return 1
    }
    echo "Writing WebDAV NAS config and folders..."
    ensure_storage_layout
    write_dufs_config
    LAST_INSTALL_AT=$(date '+%F %T')
    save_runtime
    cecho "32" "NAS installed or refreshed with webdav."
}

start_nas() {
    load_runtime
    if ! nas_binary_installed; then
        cecho "31" "NAS binary is not installed yet. Use install or reinstall first."
        return 1
    fi
    if ! nas_config_valid; then
        cecho "31" "NAS config is missing or invalid."
        cecho "33" "Use install or reinstall NAS, or save/regenerate the NAS config first."
        if nas_config_present; then
            echo ""
            echo "Current config file:"
            cat "$DUFS_CONFIG"
        fi
        return 1
    fi
    if nas_is_running; then cecho "33" "NAS is already running."; return 0; fi
    write_dufs_config
    if ! "$DUFS_BIN" version >/dev/null 2>&1; then
        cecho "31" "webdav binary is installed but could not execute."
        cecho "31" "Reinstall the NAS and check the install log."
        return 1
    fi
    clear_log_if_huge "$DUFS_LOG_FILE"
    nohup "$DUFS_BIN" -c "$DUFS_CONFIG" >> "$DUFS_LOG_FILE" 2>&1 &
    echo $! > "$DUFS_PID_FILE"
    sleep 3
    if nas_is_running; then
        cecho "32" "NAS started."
        cecho "32" "LAN URL: http://$(get_device_ip):$NAS_PORT/"
    else
        cecho "31" "NAS failed to stay running."
        if [ -f "$DUFS_LOG_FILE" ]; then
            echo ""
            echo "Recent NAS log:"
            tail -n 30 "$DUFS_LOG_FILE"
        fi
        return 1
    fi
}

stop_nas() {
    local pid
    if ! nas_is_running; then cecho "33" "NAS is not running."; return 0; fi
    pid=$(cat "$DUFS_PID_FILE" 2>/dev/null || true)
    kill "$pid" 2>/dev/null || true
    sleep 1
    if nas_is_running; then kill -9 "$pid" 2>/dev/null || true; fi
    rm -f "$DUFS_PID_FILE"
    cecho "32" "NAS stopped."
}

restart_nas() {
    stop_nas || true
    start_nas
}

uninstall_nas() {
    load_runtime
    dashboard_header
    printf '\nThis removes the NAS files in %s\n' "$BASE_DIR"
    printf 'Installed Termux packages are kept.\n'
    printf 'Continue uninstall? [y/N]: '
    read -r answer || answer=""
    if ! printf '%s' "$answer" | grep -Eq '^[Yy]$'; then
        echo "Uninstall cancelled."
        return 0
    fi

    stop_tunnel >/dev/null 2>&1 || true
    stop_nas >/dev/null 2>&1 || true
    rm -rf "$BASE_DIR"
    TUNNEL_URL=""
    LAST_INSTALL_AT=""
    save_runtime
    cecho "32" "NAS uninstalled."
}

show_runtime_config() {
    load_runtime
    dashboard_header
    printf '\n'
    cat <<EOF
NAS_PORT=$NAS_PORT
NAS_BIND=$NAS_BIND
NAS_ROOT=$NAS_ROOT
EXTERNAL_MODE=$EXTERNAL_MODE
EXTERNAL_PATH=$EXTERNAL_PATH
RCLONE_REMOTE=$RCLONE_REMOTE
TUNNEL_HOST=$TUNNEL_HOST
TUNNEL_LOCAL_HOST=$TUNNEL_LOCAL_HOST
TUNNEL_SUBDOMAIN=$TUNNEL_SUBDOMAIN
TUNNEL_URL=$TUNNEL_URL
EOF
}

show_full_nas_config() {
    dashboard_header
    printf '\n'
    if [ -f "$DUFS_CONFIG" ]; then
        cat "$DUFS_CONFIG"
        echo ""
        echo "Valid config: $( nas_config_valid && printf yes || printf no )"
    else
        echo "No NAS config written yet."
    fi
}

change_nas_port() {
    load_runtime
    dashboard_header
    printf '\nCurrent port [%s], new port: ' "$NAS_PORT"
    read -r new_port || new_port=""
    if [ -z "$new_port" ]; then echo "Port unchanged."; return 0; fi
    NAS_PORT="$new_port"
    write_dufs_config
    save_runtime
    echo "Port updated to $NAS_PORT."
}

show_current_users() { dashboard_header; printf '\n'; echo "admin=$ADMIN_USER"; echo "uploader=$UPLOADER_USER"; echo "viewer=$VIEWER_USER"; echo "Passwords are set for all three users."; }
show_access_layers() { dashboard_header; printf '\n'; echo "admin: read/write /"; echo "uploader: read/write shared/upload + own folder, read-only shared/public"; echo "viewer: read-only shared/public + own folder"; }

edit_username() {
    load_runtime
    dashboard_header
    printf '\nEdit which user? [1=admin 2=uploader 3=viewer]: '
    read -r role || role=""
    printf 'New username: '
    read -r value || value=""
    if ! validate_simple_token "$value"; then echo "Invalid username."; return 1; fi
    case "$role" in
        1) ADMIN_USER="$value" ;;
        2) UPLOADER_USER="$value" ;;
        3) VIEWER_USER="$value" ;;
        *) echo "Invalid role."; return 1 ;;
    esac
    ensure_storage_layout
    save_runtime
    echo "Username updated. Regenerate the NAS config to apply it."
}

edit_password() {
    load_runtime
    dashboard_header
    printf '\nEdit which password? [1=admin 2=uploader 3=viewer]: '
    read -r role || role=""
    printf 'New password: '
    read -r value || value=""
    if ! validate_simple_token "$value"; then echo "Invalid password."; return 1; fi
    case "$role" in
        1) ADMIN_PASS="$value" ;;
        2) UPLOADER_PASS="$value" ;;
        3) VIEWER_PASS="$value" ;;
        *) echo "Invalid role."; return 1 ;;
    esac
    save_runtime
    echo "Password updated. Regenerate the NAS config to apply it."
}

rewrite_nas_config_after_user_edits() { write_dufs_config; save_runtime; echo "NAS config regenerated."; }

show_user_folders() { dashboard_header; printf '\n'; printf '%s\n' "$NAS_ROOT/shared/public" "$NAS_ROOT/shared/upload" "$NAS_ROOT/users/$ADMIN_USER" "$NAS_ROOT/users/$UPLOADER_USER" "$NAS_ROOT/users/$VIEWER_USER"; }

configure_npm_prefix() { mkdir -p "$NPM_PREFIX/bin"; export PATH="$NPM_PREFIX/bin:$PATH"; npm config set prefix "$NPM_PREFIX" >/dev/null 2>&1 || true; }
ensure_localtunnel() { configure_npm_prefix; [ -x "$LT_BIN" ] || npm install -g localtunnel >> "$INSTALL_LOG_FILE" 2>&1; [ -x "$LT_BIN" ]; }

show_tunnel_status() { dashboard_header; printf '\n'; if tunnel_is_running; then echo "Tunnel: running"; else echo "Tunnel: stopped"; fi; extract_tunnel_url || true; }

start_tunnel() {
    load_runtime
    if ! nas_is_running; then echo "Start the NAS first."; return 1; fi
    ensure_localtunnel || { echo "localtunnel install failed."; return 1; }
    nohup sh -c "\"$LT_BIN\" --port \"$NAS_PORT\" --local-host \"$TUNNEL_LOCAL_HOST\" --host \"$TUNNEL_HOST\" ${TUNNEL_SUBDOMAIN:+--subdomain \"$TUNNEL_SUBDOMAIN\"}" > "$TUNNEL_LOG_FILE" 2>&1 &
    echo $! > "$TUNNEL_PID_FILE"
    echo "localtunnel" > "$TUNNEL_TOOL_FILE"
    sleep 5
    TUNNEL_URL=$(extract_tunnel_url || true)
    save_runtime
    echo "${TUNNEL_URL:-Tunnel started; check logs.}"
}

stop_tunnel() { if tunnel_is_running; then kill "$(cat "$TUNNEL_PID_FILE")" 2>/dev/null || true; rm -f "$TUNNEL_PID_FILE"; fi; TUNNEL_URL=""; save_runtime; echo "Tunnel stopped."; }
show_tunnel_config() { dashboard_header; printf '\n'; echo "TUNNEL_HOST=$TUNNEL_HOST"; echo "TUNNEL_LOCAL_HOST=$TUNNEL_LOCAL_HOST"; echo "TUNNEL_SUBDOMAIN=$TUNNEL_SUBDOMAIN"; echo "TUNNEL_URL=$TUNNEL_URL"; }
edit_tunnel_settings() { dashboard_header; printf '\nHost [%s]: ' "$TUNNEL_HOST"; read -r v || v=""; [ -n "$v" ] && TUNNEL_HOST="$v"; printf 'Local host [%s]: ' "$TUNNEL_LOCAL_HOST"; read -r v || v=""; [ -n "$v" ] && TUNNEL_LOCAL_HOST="$v"; printf 'Subdomain [%s]: ' "$TUNNEL_SUBDOMAIN"; read -r v || v=""; TUNNEL_SUBDOMAIN="$v"; save_runtime; echo "Tunnel settings saved."; }

show_external_target() { dashboard_header; printf '\n'; echo "mode=$EXTERNAL_MODE"; echo "path=$EXTERNAL_PATH"; echo "remote=$RCLONE_REMOTE"; }
configure_external_target() { dashboard_header; printf '\n1.none 2.local/shared/SD folder 3.rclone remote\nSelect [1-3]: '; read -r c || c=""; case "$c" in 1) EXTERNAL_MODE="none"; EXTERNAL_PATH=""; RCLONE_REMOTE="";; 2) printf 'Folder path: '; read -r p || p=""; EXTERNAL_MODE="local"; EXTERNAL_PATH="$p"; RCLONE_REMOTE="";; 3) printf 'rclone remote:path: '; read -r p || p=""; EXTERNAL_MODE="rclone"; RCLONE_REMOTE="$p"; EXTERNAL_PATH="";; esac; save_runtime; echo "External target saved."; }
push_data_to_external() { case "$EXTERNAL_MODE" in local) rsync -a --delete "$NAS_ROOT"/ "$EXTERNAL_PATH"/ >> "$SYNC_LOG_FILE" 2>&1 ;; rclone) rclone sync "$NAS_ROOT" "$RCLONE_REMOTE" >> "$SYNC_LOG_FILE" 2>&1 ;; *) echo "No external target configured."; return 1 ;; esac; echo "Push finished."; }
pull_data_from_external() { case "$EXTERNAL_MODE" in local) rsync -a "$EXTERNAL_PATH"/ "$NAS_ROOT"/ >> "$SYNC_LOG_FILE" 2>&1 ;; rclone) rclone sync "$RCLONE_REMOTE" "$NAS_ROOT" >> "$SYNC_LOG_FILE" 2>&1 ;; *) echo "No external target configured."; return 1 ;; esac; echo "Pull finished."; }

logs_menu() {
    while true; do
        dashboard_header
        printf '\n'
        echo "1. Show install log"
        echo "2. Show NAS log"
        echo "3. Show tunnel log"
        echo "4. Show sync log"
        echo "5. Clear logs"
        echo "6. Back"
        printf '\nSelect [1-6]: '
        read -r c || c=""
        case "$c" in
            1) [ -f "$INSTALL_LOG_FILE" ] && tail -n 80 "$INSTALL_LOG_FILE" || echo none; pause ;;
            2) [ -f "$DUFS_LOG_FILE" ] && tail -n 80 "$DUFS_LOG_FILE" || echo none; pause ;;
            3) [ -f "$TUNNEL_LOG_FILE" ] && tail -n 80 "$TUNNEL_LOG_FILE" || echo none; pause ;;
            4) [ -f "$SYNC_LOG_FILE" ] && tail -n 80 "$SYNC_LOG_FILE" || echo none; pause ;;
            5) : > "$INSTALL_LOG_FILE"; : > "$DUFS_LOG_FILE"; : > "$TUNNEL_LOG_FILE"; : > "$SYNC_LOG_FILE"; echo cleared; pause ;;
            6|0|b|B|q|Q) return 0 ;;
        esac
    done
}

config_menu() {
    while true; do
        dashboard_header
        printf '\n'
        echo "1. Show runtime config"
        echo "2. Show full NAS config"
        echo "3. Change NAS/WebDAV port"
        echo "4. Configure external target"
        echo "5. Show tunnel config"
        echo "6. Save changes on-device"
        echo "7. Back"
        printf '\nSelect [1-7]: '
        read -r c || c=""
        case "$c" in
            1) show_runtime_config; pause ;;
            2) show_full_nas_config; pause ;;
            3) change_nas_port; pause ;;
            4) configure_external_target; pause ;;
            5) show_tunnel_config; pause ;;
            6) write_dufs_config; save_runtime; echo saved; pause ;;
            7|0|b|B|q|Q) return 0 ;;
        esac
    done
}

users_menu() {
    while true; do
        dashboard_header
        printf '\n'
        echo "1. Show current users"
        echo "2. Show access layers"
        echo "3. Edit usernames"
        echo "4. Edit passwords"
        echo "5. Regenerate/write NAS config"
        echo "6. Show user folders"
        echo "7. Back"
        printf '\nSelect [1-7]: '
        read -r c || c=""
        case "$c" in
            1) show_current_users; pause ;;
            2) show_access_layers; pause ;;
            3) edit_username; pause ;;
            4) edit_password; pause ;;
            5) rewrite_nas_config_after_user_edits; pause ;;
            6) show_user_folders; pause ;;
            7|0|b|B|q|Q) return 0 ;;
        esac
    done
}

tunnel_menu() {
    while true; do
        dashboard_header
        printf '\n'
        echo "1. Show tunnel status"
        echo "2. Start tunnel"
        echo "3. Stop tunnel"
        echo "4. Show tunnel config"
        echo "5. Edit tunnel settings"
        echo "6. Back"
        printf '\nSelect [1-6]: '
        read -r c || c=""
        case "$c" in
            1) show_tunnel_status; pause ;;
            2) start_tunnel; pause ;;
            3) stop_tunnel; pause ;;
            4) show_tunnel_config; pause ;;
            5) edit_tunnel_settings; pause ;;
            6|0|b|B|q|Q) return 0 ;;
        esac
    done
}

external_datakeepers_menu() {
    while true; do
        dashboard_header
        printf '\n'
        echo "1. Show current external target"
        echo "2. Configure mode"
        echo "3. Push data to external target"
        echo "4. Pull data from external target"
        echo "5. Back"
        printf '\nSelect [1-5]: '
        read -r c || c=""
        case "$c" in
            1) show_external_target; pause ;;
            2) configure_external_target; pause ;;
            3) push_data_to_external; pause ;;
            4) pull_data_from_external; pause ;;
            5|0|b|B|q|Q) return 0 ;;
        esac
    done
}

main_menu() {
    load_runtime
    while true; do
        dashboard_header
        printf '\n1. Install or reinstall NAS\n2. Start NAS\n3. Stop NAS\n4. Restart NAS\n5. Uninstall NAS\n6. Show status\n7. Show info\n8. Config menu\n9. Users menu\n10. Tunnel menu\n11. External datakeepers\n12. Logs\n13. Refresh\n14. Exit\n\nSelect [1-14]: '
        read -r choice || choice=""
        case "$choice" in
            1) install_or_reinstall_nas; pause ;;
            2) start_nas; pause ;;
            3) stop_nas; pause ;;
            4) restart_nas; pause ;;
            5) uninstall_nas; pause ;;
            6) show_status_screen; pause ;;
            7) show_info_screen; pause ;;
            8) config_menu ;;
            9) users_menu ;;
            10) tunnel_menu ;;
            11) external_datakeepers_menu ;;
            12) logs_menu ;;
            13) ;;
            14|0|q|Q|exit|Exit|quit|Quit) exit 0 ;;
        esac
    done
}

main_menu
"""

def create_ssl_context():
    try:
        return ssl._create_unverified_context()
    except Exception:
        return ssl.create_default_context()


def run_command(command, *, text=False, timeout=None):
    kwargs = {"capture_output": True, "timeout": timeout}
    if text:
        kwargs["text"] = True
    if sys.platform == "win32":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return subprocess.run(command, **kwargs)


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Cellhasher-Android-NAS-Hub/1.0"})
    with urllib.request.urlopen(request, timeout=30, context=create_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def get_latest_termux_apk():
    release_data = fetch_json(TERMUX_RELEASES_API)
    assets = release_data.get("assets", [])
    preferred_names = ["arm64-v8a", "universal", "apk"]
    for needle in preferred_names:
        for asset in assets:
            name = asset.get("name", "").lower()
            if needle in name and name.endswith(".apk"):
                return asset["browser_download_url"], asset["name"], release_data.get("tag_name", "latest")
    raise RuntimeError("No suitable Termux APK found in latest release")


def download_file(url, filename):
    local_path = os.path.join(tempfile.gettempdir(), filename)
    request = urllib.request.Request(url, headers={"User-Agent": "Cellhasher-Android-NAS-Hub/1.0"})
    with urllib.request.urlopen(request, timeout=180, context=create_ssl_context()) as response, open(local_path, "wb") as handle:
        while True:
            chunk = response.read(1024 * 128)
            if not chunk:
                break
            handle.write(chunk)
    return local_path


def check_termux_installed(device_id):
    result = run_command([ADB, "-s", device_id, "shell", "pm", "list", "packages", "com.termux"], text=True, timeout=30)
    return "com.termux" in (result.stdout or "")


def install_termux(device_id, apk_path):
    result = run_command([ADB, "-s", device_id, "install", "-r", apk_path], text=True, timeout=180)
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    return result.returncode == 0 or "Success" in output


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
            run_command([ADB, "-s", device_id, "shell", "pm", "grant", "com.termux", permission], timeout=20)
        except Exception:
            pass


def launch_hub_on_device(device_id, local_script_path):
    device_script_path = "/data/local/tmp/cellhasher_android_nas_hub.sh"
    run_command([ADB, "-s", device_id, "shell", "am", "force-stop", "com.termux"], timeout=20)
    time.sleep(1)
    push_result = run_command([ADB, "-s", device_id, "push", local_script_path, device_script_path], text=True, timeout=60)
    if push_result.returncode != 0:
        return f"[{device_id}] Error: failed to push Termux NAS hub script"
    run_command([ADB, "-s", device_id, "shell", "chmod", "755", device_script_path], timeout=20)
    grant_termux_permissions(device_id)
    run_command([ADB, "-s", device_id, "shell", "am", "start", "-n", "com.termux/com.termux.app.TermuxActivity"], timeout=30)
    time.sleep(15)
    run_command([ADB, "-s", device_id, "shell", "input", "text", "bash%s/data/local/tmp/cellhasher_android_nas_hub.sh"], timeout=20)
    time.sleep(0.5)
    run_command([ADB, "-s", device_id, "shell", "input", "keyevent", "66"], timeout=20)
    return f"[{device_id}] Success: Android NAS hub opened in Termux"


def ensure_termux_on_devices(selected_devices):
    ready_devices = []
    missing_devices = []
    for device_id in selected_devices:
        if check_termux_installed(device_id):
            print(f"[{device_id}] Termux already installed")
            ready_devices.append(device_id)
        else:
            print(f"[{device_id}] Termux missing")
            missing_devices.append(device_id)
    if not missing_devices:
        return ready_devices

    print()
    print("[*] Downloading latest Termux APK...")
    apk_url, apk_name, tag_name = get_latest_termux_apk()
    print(f"[*] Termux release: {tag_name}")
    apk_path = download_file(apk_url, apk_name)
    try:
        with ThreadPoolExecutor(max_workers=min(len(missing_devices), 4)) as executor:
            future_map = {executor.submit(install_termux, device_id, apk_path): device_id for device_id in missing_devices}
            for future in as_completed(future_map):
                device_id = future_map[future]
                try:
                    success = future.result()
                except Exception as exc:
                    print(f"[{device_id}] Termux install failed: {exc}")
                    continue
                if success:
                    print(f"[{device_id}] Termux installed")
                    ready_devices.append(device_id)
                else:
                    print(f"[{device_id}] Termux installation failed")
    finally:
        if os.path.exists(apk_path):
            os.remove(apk_path)
    if ready_devices:
        time.sleep(5)
    return ready_devices


def main():
    print("=" * 64)
    print("   Cellhasher Android NAS Hub")
    print("   Termux | webdav | localtunnel | rclone")
    print("=" * 64)
    print()
    if not devices:
        print("[ERROR] No devices found in environment variable 'devices'")
        print("[INFO] Select at least one Android device in Cellhasher and rerun")
        return
    print(f"[*] Devices selected: {len(devices)}")
    for index, device_id in enumerate(devices, start=1):
        print(f"    {index}. {device_id}")
    print()
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", delete=False, suffix=".sh") as handle:
        handle.write(TERMUX_HUB_SCRIPT)
        local_script_path = handle.name
    try:
        ready_devices = ensure_termux_on_devices(devices)
        if not ready_devices:
            print("[ERROR] No device is ready for Termux deployment")
            return
        print()
        print("[*] Launching the Android NAS hub...")
        print()
        with ThreadPoolExecutor(max_workers=min(len(ready_devices), 4)) as executor:
            future_map = {executor.submit(launch_hub_on_device, device_id, local_script_path): device_id for device_id in ready_devices}
            for future in as_completed(future_map):
                try:
                    print(future.result())
                except Exception as exc:
                    device_id = future_map[future]
                    print(f"[{device_id}] Launch failed: {exc}")
    finally:
        if os.path.exists(local_script_path):
            os.remove(local_script_path)
    print()
    print("=" * 64)
    print("   Next step on the phone")
    print("=" * 64)
    print("   1. Termux opens on the selected device.")
    print("   2. The NAS dashboard and menu appear before any install step.")
    print("   3. Use 'Install or reinstall NAS' for first-time setup.")
    print("   4. Use the same hub later to start, stop, reconfigure, sync, and tunnel the NAS.")
    print("=" * 64)


if __name__ == "__main__":
    main()
