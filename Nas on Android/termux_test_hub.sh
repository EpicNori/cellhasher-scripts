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
DUFS_BIN="$BIN_DIR/dufs"
DUFS_CONFIG="$ETC_DIR/dufs.yaml"
DUFS_PID_FILE="$STATE_DIR/dufs.pid"
DUFS_LOG_FILE="$LOG_DIR/dufs.log"
INSTALL_LOG_FILE="$LOG_DIR/install.log"
SYNC_LOG_FILE="$LOG_DIR/sync.log"
TUNNEL_PID_FILE="$STATE_DIR/tunnel.pid"
TUNNEL_LOG_FILE="$LOG_DIR/tunnel.log"
TUNNEL_STATUS_FILE="$STATE_DIR/tunnel.status"
TUNNEL_TOOL_FILE="$STATE_DIR/tunnel.tool"
NPM_PREFIX="$HOME/.npm-global"
LT_BIN="$NPM_PREFIX/bin/lt"
SERVER_URL=""

mkdir -p "$BASE_DIR" "$BIN_DIR" "$ETC_DIR" "$DATA_DIR" "$LOG_DIR" "$STATE_DIR" "$TMP_DIR"

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
    mkdir -p "$ETC_DIR"
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

nas_installed() {
    [ -x "$DUFS_BIN" ] && [ -f "$DUFS_CONFIG" ]
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
    ensure_storage_layout
    local ip_addr install_state run_state tunnel_state tunnel_url
    ip_addr=$(get_device_ip)
    if nas_installed; then install_state="installed"; else install_state="not installed"; fi
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
    echo "dufs binary  : $( [ -x "$DUFS_BIN" ] && printf yes || printf no )"
    echo "dufs config  : $( [ -f "$DUFS_CONFIG" ] && printf yes || printf no )"
}

show_info_screen() {
    dashboard_header
    printf '\n'
    line
    echo "Info"
    line
    echo "This phone exposes a small WebDAV NAS through dufs inside Termux."
    echo ""
    echo "Access layers:"
    echo "  admin    -> full read/write access to the whole NAS"
    echo "  uploader -> read/write on shared/upload and own user folder, read-only on shared/public"
    echo "  viewer   -> read-only on shared/public and own user folder"
}

ensure_base_packages() {
    {
        echo "[$(date '+%F %T')] Updating Termux packages"
        pkg update -y || true
        yes '' | pkg upgrade -y 2>/dev/null || true
        echo "[$(date '+%F %T')] Installing required packages"
        pkg install -y curl jq tar gzip unzip procps psmisc rsync nodejs rclone termux-tools
        echo "[$(date '+%F %T')] Package step finished"
    } >> "$INSTALL_LOG_FILE" 2>&1
}

detect_dufs_asset() {
    case "$(uname -m)" in
        aarch64|arm64) printf '%s' 'aarch64-unknown-linux-musl.tar.gz' ;;
        armv7l|armv8l|arm) printf '%s' 'armv7-unknown-linux-musleabihf.tar.gz' ;;
        x86_64) printf '%s' 'x86_64-unknown-linux-musl.tar.gz' ;;
        i686|i386) printf '%s' 'i686-unknown-linux-musl.tar.gz' ;;
        *) return 1 ;;
    esac
}

install_dufs() {
    local release_json asset_needle download_url archive_path extract_dir dufs_path version
    asset_needle=$(detect_dufs_asset) || { cecho "31" "Unsupported device architecture for dufs: $(uname -m)"; return 1; }
    echo "[2/4] Fetching dufs release metadata..."
    release_json=$(curl -fsSL "https://api.github.com/repos/sigoden/dufs/releases/latest") || { cecho "31" "Could not fetch dufs release metadata."; return 1; }
    version=$(printf '%s' "$release_json" | jq -r '.tag_name // empty' | sed 's/^v//')
    download_url=$(printf '%s' "$release_json" | jq -r --arg needle "$asset_needle" '.assets[] | select(.name | contains($needle)) | .browser_download_url' | head -n1)
    if [ -z "$download_url" ]; then cecho "31" "Could not find a matching dufs binary asset."; return 1; fi
    archive_path="$TMP_DIR/dufs.tar.gz"
    extract_dir="$TMP_DIR/dufs-extract"
    rm -rf "$extract_dir"
    mkdir -p "$extract_dir"
    echo "[3/4] Downloading dufs $version..."
    curl -fL "$download_url" -o "$archive_path" >> "$INSTALL_LOG_FILE" 2>&1 || { cecho "31" "Failed to download dufs."; return 1; }
    echo "[4/4] Unpacking and installing dufs..."
    tar -xzf "$archive_path" -C "$extract_dir" >> "$INSTALL_LOG_FILE" 2>&1 || { cecho "31" "Failed to unpack dufs."; return 1; }
    dufs_path=$(find "$extract_dir" -type f -name dufs | head -n1)
    if [ -z "$dufs_path" ]; then cecho "31" "dufs binary was not found after unpacking."; return 1; fi
    cp "$dufs_path" "$DUFS_BIN"
    chmod 755 "$DUFS_BIN"
    DUFS_VERSION="$version"
    save_runtime
    cecho "32" "dufs $version installed."
}

write_dufs_config() {
    ensure_storage_layout
    cat > "$DUFS_CONFIG" <<EOF
serve-path: '$(yaml_value "$NAS_ROOT")'
bind: '$(yaml_value "$NAS_BIND")'
port: $NAS_PORT
auth:
  - '$(yaml_value "$ADMIN_USER"):$(yaml_value "$ADMIN_PASS")@/:rw'
  - '$(yaml_value "$UPLOADER_USER"):$(yaml_value "$UPLOADER_PASS")@/shared/upload:rw,/users/$(yaml_value "$UPLOADER_USER"):rw,/shared/public'
  - '$(yaml_value "$VIEWER_USER"):$(yaml_value "$VIEWER_PASS")@/shared/public,/users/$(yaml_value "$VIEWER_USER")'
allow-upload: true
allow-delete: true
allow-search: true
allow-archive: true
render-index: true
render-try-index: true
log-file: '$(yaml_value "$DUFS_LOG_FILE")'
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
    echo "Requesting Termux shared-storage setup..."
    termux-setup-storage >/dev/null 2>&1 || true
    sleep 2
    if nas_is_running; then stop_nas >/dev/null 2>&1; fi
    install_dufs || {
        [ -f "$INSTALL_LOG_FILE" ] && tail -n 40 "$INSTALL_LOG_FILE"
        return 1
    }
    echo "Writing NAS config and folders..."
    ensure_storage_layout
    write_dufs_config
    LAST_INSTALL_AT=$(date '+%F %T')
    save_runtime
    cecho "32" "NAS installed or refreshed."
}

start_nas() {
    load_runtime
    if ! nas_installed; then cecho "31" "NAS is not installed yet. Use install or reinstall first."; return 1; fi
    if nas_is_running; then cecho "33" "NAS is already running."; return 0; fi
    write_dufs_config
    if ! "$DUFS_BIN" --version >/dev/null 2>&1; then
        cecho "31" "dufs binary is installed but could not execute."
        cecho "31" "Reinstall the NAS and check the install log."
        return 1
    fi
    clear_log_if_huge "$DUFS_LOG_FILE"
    nohup "$DUFS_BIN" "$NAS_ROOT" \
        --bind "${NAS_BIND}:${NAS_PORT}" \
        --auth "$ADMIN_USER:$ADMIN_PASS@/:rw" \
        --auth "$UPLOADER_USER:$UPLOADER_PASS@/shared/upload:rw,/users/$UPLOADER_USER:rw,/shared/public" \
        --auth "$VIEWER_USER:$VIEWER_PASS@/shared/public,/users/$VIEWER_USER" \
        --allow-upload \
        --allow-delete \
        --allow-search \
        --allow-archive \
        --render-try-index \
        --log-file "$DUFS_LOG_FILE" >> "$DUFS_LOG_FILE" 2>&1 &
    echo $! > "$DUFS_PID_FILE"
    sleep 2
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
    if [ -f "$DUFS_CONFIG" ]; then cat "$DUFS_CONFIG"; else echo "No NAS config written yet."; fi
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
    ensure_storage_layout
    while true; do
        dashboard_header
        printf '\n1. Install or reinstall NAS\n2. Start NAS\n3. Stop NAS\n4. Restart NAS\n5. Show status\n6. Show info\n7. Config menu\n8. Users menu\n9. Tunnel menu\n10. External datakeepers\n11. Logs\n12. Refresh\n13. Exit\n\nSelect [1-13]: '
        read -r choice || choice=""
        case "$choice" in
            1) install_or_reinstall_nas; pause ;;
            2) start_nas; pause ;;
            3) stop_nas; pause ;;
            4) restart_nas; pause ;;
            5) show_status_screen; pause ;;
            6) show_info_screen; pause ;;
            7) config_menu ;;
            8) users_menu ;;
            9) tunnel_menu ;;
            10) external_datakeepers_menu ;;
            11) logs_menu ;;
            12) ;;
            13|0|q|Q|exit|Exit|quit|Quit) exit 0 ;;
        esac
    done
}

main_menu