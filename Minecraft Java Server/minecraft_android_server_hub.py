#!/usr/bin/env python3
"""
Cellhasher Minecraft Android Server Hub

Pushes an interactive Termux management script to Android devices. The on-device
menu can install Paper, Vanilla, Fabric, or Bukkit servers, change RAM, install
mods/plugins from Modrinth or CurseForge links, and optionally install playit.
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
    "id": "minecraft-android-server-hub-v1",
    "name": "Minecraft Android Server Hub",
    "description": "Interactive Android Minecraft server hub for Cellhasher. Installs Paper, Vanilla, Fabric, or Bukkit in Termux, lets you set RAM, install add-ons from Modrinth or CurseForge links, and optionally installs playit tunneling.",
    "category": "Gaming",
    "type": "python",
    "version": "1.0.0",
    "author": "Cellhasher Team",
    "difficulty": "Advanced",
    "estimatedTime": "10-20 min",
    "tags": [
        "minecraft",
        "server",
        "android",
        "termux",
        "paper",
        "vanilla",
        "fabric",
        "bukkit",
        "modrinth",
        "curseforge",
        "playit",
    ],
    "effects": {
        "power": {"reboot": False, "shutdown": False},
        "security": {"modifiesLockScreen": False},
    },
    "estimatedDurationSec": 1200,
    "downloads": 0,
    "rating": 5.0,
    "lastUpdated": "2026-03-20",
}


TERMUX_HUB_SCRIPT = r"""#!/data/data/com.termux/files/usr/bin/bash
set -e

BASE_DIR="$HOME/cellhasher-mc"
SERVER_DIR="$BASE_DIR/server"
STATE_DIR="$BASE_DIR/state"
STATE_FILE="$STATE_DIR/server.env"
START_SCRIPT="$BASE_DIR/start-server.sh"
PLAYIT_DIR="$BASE_DIR/playit"
PLAYIT_CONFIG_DIR="$PLAYIT_DIR"
PLAYIT_CONFIG_FILE="$PLAYIT_DIR/playit.toml"
PLAYIT_SECRET_FILE="$PLAYIT_DIR/secret_key.txt"
PLAYIT_VERSION_FILE="$PLAYIT_DIR/version.txt"
PLAYIT_PID_FILE="$PLAYIT_DIR/playit.pid"
PLAYIT_LOG_FILE="$PLAYIT_DIR/playit.log"
PLAYIT_AGENT_BOOT_LOG="$PLAYIT_DIR/playit-boot.log"
PLAYIT_SECRET_URL="https://playit.gg/account/agents"
PLAYIT_API_BASE="https://api.playit.gg"
USER_AGENT="Cellhasher-Minecraft-Hub/1.0 (https://github.com/)"

mkdir -p "$BASE_DIR" "$SERVER_DIR" "$STATE_DIR"

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
    read -r _
}

load_state() {
    SERVER_TYPE=""
    MC_VERSION=""
    RAM_GB="2"
    SERVER_JAR="server.jar"

    if [ -f "$STATE_FILE" ]; then
        # shellcheck disable=SC1090
        . "$STATE_FILE"
    fi
}

save_state() {
    cat > "$STATE_FILE" <<EOF
SERVER_TYPE="$SERVER_TYPE"
MC_VERSION="$MC_VERSION"
RAM_GB="$RAM_GB"
SERVER_JAR="$SERVER_JAR"
EOF
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

show_connection_info() {
    load_state
    local ip_addr
    ip_addr=$(get_device_ip)
    clear
    line
    echo "Minecraft Android Server Hub"
    line
    echo "Server type : ${SERVER_TYPE:-not installed}"
    echo "Version     : ${MC_VERSION:-not installed}"
    echo "RAM         : ${RAM_GB} GB"
    echo "IP          : ${ip_addr}"
    echo "Port        : 25565"
    echo "LAN join    : ${ip_addr}:25565"
    if [ -x "$PLAYIT_DIR/playit" ]; then
        echo "playit      : installed"
    else
        echo "playit      : not installed"
    fi
}

ensure_packages() {
    clear
    line
    echo "Preparing Termux packages"
    line
    pkg update -y || true
    yes '' | pkg upgrade -y 2>/dev/null || true
    pkg install -y openjdk-21 curl jq unzip tar git
}

prompt_server_type() {
    while true; do
        clear
        line
        echo "Choose server software"
        line
        echo "1. Paper"
        echo "2. Vanilla"
        echo "3. Fabric"
        echo "4. Bukkit (BuildTools / CraftBukkit)"
        printf '\nSelect [1-4]: '
        read -r choice
        case "$choice" in
            1) SERVER_TYPE="paper"; return ;;
            2) SERVER_TYPE="vanilla"; return ;;
            3) SERVER_TYPE="fabric"; return ;;
            4) SERVER_TYPE="bukkit"; return ;;
        esac
    done
}

get_latest_release_version() {
    curl -fsSL "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json" | jq -r '.latest.release'
}

prompt_minecraft_version() {
    local latest_version
    latest_version=$(get_latest_release_version)
    printf '\nMinecraft version [latest=%s, press ENTER for latest]: ' "$latest_version"
    read -r requested_version
    if [ -z "$requested_version" ]; then
        MC_VERSION="$latest_version"
    else
        MC_VERSION="$requested_version"
    fi
}

prompt_ram() {
    local default_value="${1:-2}"
    while true; do
        printf '\nRAM in GB [%s]: ' "$default_value"
        read -r requested_ram
        if [ -z "$requested_ram" ]; then
            RAM_GB="$default_value"
            return
        fi
        if [[ "$requested_ram" =~ ^[0-9]+$ ]] && [ "$requested_ram" -ge 1 ] && [ "$requested_ram" -le 16 ]; then
            RAM_GB="$requested_ram"
            return
        fi
        cecho "33" "Enter a whole number between 1 and 16."
    done
}

get_memory_flags() {
    local max_mb min_mb
    max_mb=$((RAM_GB * 1024))
    min_mb=$((max_mb / 2))
    if [ "$min_mb" -lt 512 ]; then
        min_mb=512
    fi
    printf '%s %s' "$min_mb" "$max_mb"
}

write_start_script() {
    local min_mb max_mb
    read -r min_mb max_mb <<< "$(get_memory_flags)"

    cat > "$START_SCRIPT" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
set -e
BASE_DIR="\$HOME/cellhasher-mc"
SERVER_DIR="\$BASE_DIR/server"
SERVER_JAR="${SERVER_JAR}"
MIN_MB="${min_mb}"
MAX_MB="${max_mb}"

if [ ! -f "\$SERVER_DIR/\$SERVER_JAR" ]; then
    echo "Server jar not found: \$SERVER_DIR/\$SERVER_JAR"
    exit 1
fi

cd "\$SERVER_DIR"
echo "Starting ${SERVER_TYPE} ${MC_VERSION} with -Xms\${MIN_MB}M -Xmx\${MAX_MB}M"
java -Xms\${MIN_MB}M -Xmx\${MAX_MB}M -jar "\$SERVER_JAR" nogui
EOF
    chmod +x "$START_SCRIPT"
}

apply_mobile_tuning() {
    if [ -f "$SERVER_DIR/server.properties" ]; then
        sed -i 's/^view-distance=.*/view-distance=6/' "$SERVER_DIR/server.properties" 2>/dev/null || true
        sed -i 's/^simulation-distance=.*/simulation-distance=4/' "$SERVER_DIR/server.properties" 2>/dev/null || true
        sed -i 's/^max-players=.*/max-players=5/' "$SERVER_DIR/server.properties" 2>/dev/null || true
        sed -i 's/^motd=.*/motd=Cellhasher Android Server/' "$SERVER_DIR/server.properties" 2>/dev/null || true
    fi
}

accept_eula() {
    cd "$SERVER_DIR"
    java -Xms512M -Xmx1024M -jar "$SERVER_JAR" nogui >/dev/null 2>&1 || true
    if [ -f "$SERVER_DIR/eula.txt" ]; then
        sed -i 's/eula=false/eula=true/' "$SERVER_DIR/eula.txt"
    else
        echo "eula=true" > "$SERVER_DIR/eula.txt"
    fi
    apply_mobile_tuning
}

install_paper() {
    local builds_json download_url
    SERVER_JAR="server.jar"

    cecho "36" "Installing Paper ${MC_VERSION}"
    builds_json=$(curl -fsSL -H "User-Agent: $USER_AGENT" "https://fill.papermc.io/v3/projects/paper/versions/${MC_VERSION}/builds")
    download_url=$(printf '%s' "$builds_json" | jq -r 'first(.[] | select(.channel == "STABLE") | .downloads."server:default".url) // empty')

    if [ -z "$download_url" ]; then
        cecho "31" "No stable Paper build found for ${MC_VERSION}."
        return 1
    fi

    rm -f "$SERVER_DIR/$SERVER_JAR"
    curl -fL -o "$SERVER_DIR/$SERVER_JAR" "$download_url"
}

install_vanilla() {
    local manifest_json version_json_url version_json download_url
    SERVER_JAR="server.jar"

    cecho "36" "Installing Vanilla ${MC_VERSION}"
    manifest_json=$(curl -fsSL "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
    version_json_url=$(printf '%s' "$manifest_json" | jq -r --arg version "$MC_VERSION" '.versions[] | select(.id == $version) | .url' | head -n1)

    if [ -z "$version_json_url" ]; then
        cecho "31" "Minecraft version ${MC_VERSION} was not found in the Mojang manifest."
        return 1
    fi

    version_json=$(curl -fsSL "$version_json_url")
    download_url=$(printf '%s' "$version_json" | jq -r '.downloads.server.url // empty')

    if [ -z "$download_url" ]; then
        cecho "31" "No official server download found for ${MC_VERSION}."
        return 1
    fi

    rm -f "$SERVER_DIR/$SERVER_JAR"
    curl -fL -o "$SERVER_DIR/$SERVER_JAR" "$download_url"
}

install_fabric() {
    local loader_version installer_version fabric_url
    SERVER_JAR="server.jar"

    cecho "36" "Installing Fabric ${MC_VERSION}"
    loader_version=$(curl -fsSL "https://meta.fabricmc.net/v2/versions/loader/${MC_VERSION}" | jq -r '.[0].loader.version // empty')
    installer_version=$(curl -fsSL "https://meta.fabricmc.net/v2/versions/installer" | jq -r '.[0].version // empty')

    if [ -z "$loader_version" ] || [ -z "$installer_version" ]; then
        cecho "31" "Could not resolve Fabric loader or installer for ${MC_VERSION}."
        return 1
    fi

    fabric_url="https://meta.fabricmc.net/v2/versions/loader/${MC_VERSION}/${loader_version}/${installer_version}/server/jar"
    rm -f "$SERVER_DIR/$SERVER_JAR"
    curl -fL -o "$SERVER_DIR/$SERVER_JAR" "$fabric_url"
}

install_bukkit() {
    local buildtools_jar output_jar
    SERVER_JAR="server.jar"
    buildtools_jar="$BASE_DIR/BuildTools.jar"
    output_jar="$BASE_DIR/craftbukkit-${MC_VERSION}.jar"

    cecho "36" "Installing Bukkit ${MC_VERSION}"
    cecho "33" "CraftBukkit build generation is much slower than Paper or Vanilla on Android."
    curl -fL -o "$buildtools_jar" "https://hub.spigotmc.org/jenkins/job/BuildTools/lastSuccessfulBuild/artifact/target/BuildTools.jar"

    cd "$BASE_DIR"
    rm -f "$output_jar"
    java -jar "$buildtools_jar" --rev "$MC_VERSION" --compile craftbukkit

    if [ ! -f "$output_jar" ]; then
        cecho "31" "BuildTools did not produce $output_jar"
        return 1
    fi

    rm -f "$SERVER_DIR/$SERVER_JAR"
    cp "$output_jar" "$SERVER_DIR/$SERVER_JAR"
}

install_server() {
    ensure_packages
    prompt_server_type
    prompt_minecraft_version
    prompt_ram "$RAM_GB"

    rm -rf "$SERVER_DIR"
    mkdir -p "$SERVER_DIR"

    case "$SERVER_TYPE" in
        paper) install_paper ;;
        vanilla) install_vanilla ;;
        fabric) install_fabric ;;
        bukkit) install_bukkit ;;
        *) cecho "31" "Unsupported server type: $SERVER_TYPE"; return 1 ;;
    esac

    accept_eula
    write_start_script
    save_state

    cecho "32" "Server installed."
    cecho "32" "Type: ${SERVER_TYPE}"
    cecho "32" "Version: ${MC_VERSION}"
    cecho "32" "RAM: ${RAM_GB} GB"
}

addon_dir_for_server() {
    case "$SERVER_TYPE" in
        fabric) printf '%s' "$SERVER_DIR/mods" ;;
        paper|bukkit) printf '%s' "$SERVER_DIR/plugins" ;;
        *) printf '%s' "" ;;
    esac
}

modrinth_loader_candidates() {
    case "$SERVER_TYPE" in
        fabric) echo "fabric quilt" ;;
        paper) echo "paper purpur bukkit spigot" ;;
        bukkit) echo "bukkit spigot paper purpur" ;;
        *) echo "" ;;
    esac
}

resolve_modrinth_url() {
    local input_url="$1"
    local slug version_id api_url candidate response resolved_url

    if [[ "$input_url" =~ ^https://cdn\.modrinth\.com/ ]]; then
        printf '%s' "$input_url"
        return 0
    fi

    if [[ "$input_url" =~ modrinth\.com/.*/version/([^/?#]+) ]]; then
        version_id="${BASH_REMATCH[1]}"
        resolved_url=$(curl -fsSL "https://api.modrinth.com/v2/version/${version_id}" | jq -r 'first(.files[] | select(.primary == true) | .url) // first(.files[]?.url) // empty')
        if [ -n "$resolved_url" ]; then
            printf '%s' "$resolved_url"
            return 0
        fi
    fi

    if [[ "$input_url" =~ modrinth\.com/(mod|plugin)/([^/?#]+) ]]; then
        slug="${BASH_REMATCH[2]}"
    fi

    if [ -z "$slug" ]; then
        return 1
    fi

    for candidate in $(modrinth_loader_candidates); do
        api_url="https://api.modrinth.com/v2/project/${slug}/version?loaders=%5B%22${candidate}%22%5D&game_versions=%5B%22${MC_VERSION}%22%5D"
        response=$(curl -fsSL "$api_url" || true)
        resolved_url=$(printf '%s' "$response" | jq -r '.[0].files | (first(map(select(.primary == true))) // .[0]) | .url // empty' 2>/dev/null || true)
        if [ -n "$resolved_url" ]; then
            printf '%s' "$resolved_url"
            return 0
        fi
    done

    return 1
}

resolve_curseforge_url() {
    local input_url="$1"
    local prefix file_id

    if [[ "$input_url" =~ ^https://(mediafilez|edge)\.forgecdn\.net/ ]]; then
        printf '%s' "$input_url"
        return 0
    fi

    if [[ "$input_url" =~ ^https://www\.curseforge\.com/.*/download/([0-9]+)/file/?$ ]]; then
        printf '%s' "$input_url"
        return 0
    fi

    if [[ "$input_url" =~ ^https://www\.curseforge\.com/.*/download/([0-9]+)/?$ ]]; then
        printf '%s/file' "$input_url"
        return 0
    fi

    if [[ "$input_url" =~ ^(https://www\.curseforge\.com/.*/files)/([0-9]+)/?.*$ ]]; then
        prefix="${BASH_REMATCH[1]}"
        file_id="${BASH_REMATCH[2]}"
        printf '%s/download/%s/file' "${prefix%/files}" "$file_id"
        return 0
    fi

    return 1
}

download_addon() {
    local source_url="$1"
    local target_dir="$2"
    local tmp_file effective_url filename

    mkdir -p "$target_dir"
    tmp_file=$(mktemp)
    effective_url=$(curl -fL -sS -o "$tmp_file" -w '%{url_effective}' "$source_url")
    filename=$(basename "${effective_url%%\?*}")

    if [ -z "$filename" ] || [ "$filename" = "file" ]; then
        rm -f "$tmp_file"
        cecho "31" "Could not determine filename for $source_url"
        return 1
    fi

    mv "$tmp_file" "$target_dir/$filename"
    cecho "32" "Installed: $filename"
}

install_addons() {
    load_state
    local target_dir raw_input token resolved_url

    if [ -z "$SERVER_TYPE" ] || [ ! -f "$SERVER_DIR/$SERVER_JAR" ]; then
        cecho "31" "Install a server first."
        return 1
    fi

    target_dir=$(addon_dir_for_server)
    if [ -z "$target_dir" ]; then
        cecho "31" "Vanilla does not support server mods/plugins here. Use Fabric, Paper, or Bukkit instead."
        return 1
    fi

    clear
    line
    echo "Add-on installer"
    line
    echo "Paste one or more Modrinth or CurseForge links."
    echo "Modrinth project URLs work."
    echo "CurseForge needs a file page or direct download URL."
    echo "Examples:"
    echo "  https://modrinth.com/mod/fabric-api"
    echo "  https://www.curseforge.com/minecraft/mc-mods/example/files/1234567"
    printf '\nLinks (space separated): '
    read -r raw_input

    if [ -z "$raw_input" ]; then
        return 0
    fi

    for token in $raw_input; do
        resolved_url=""

        if [[ "$token" == *"modrinth.com"* ]] || [[ "$token" == https://cdn.modrinth.com/* ]]; then
            resolved_url=$(resolve_modrinth_url "$token" || true)
        elif [[ "$token" == *"curseforge.com"* ]] || [[ "$token" == https://mediafilez.forgecdn.net/* ]] || [[ "$token" == https://edge.forgecdn.net/* ]]; then
            resolved_url=$(resolve_curseforge_url "$token" || true)
        else
            cecho "31" "Unsupported source: $token"
            continue
        fi

        if [ -z "$resolved_url" ]; then
            cecho "31" "Could not resolve a download URL for: $token"
            continue
        fi

        download_addon "$resolved_url" "$target_dir" || true
    done
}

install_playit() {
    local arch asset_name asset_url release_json release_tag

    mkdir -p "$PLAYIT_DIR"
    arch=$(uname -m)
    release_json=$(curl -fsSL -A "$USER_AGENT" "https://api.github.com/repos/playit-cloud/playit-agent/releases/latest")
    release_tag=$(printf '%s' "$release_json" | jq -r '.tag_name // empty' | sed 's/^v//')

    case "$arch" in
        aarch64|arm64) asset_name="playit-linux-aarch64" ;;
        armv7l|armv8l) asset_name="playit-linux-armv7" ;;
        x86_64) asset_name="playit-linux-amd64" ;;
        *)
            cecho "31" "Unsupported CPU architecture: $arch"
            return 1
            ;;
    esac

    asset_url=$(printf '%s' "$release_json" | jq -r --arg name "$asset_name" '.assets[] | select(.name == $name) | .browser_download_url' | head -n1)
    if [ -z "$asset_url" ]; then
        cecho "31" "Could not find a Playit release asset for $asset_name"
        return 1
    fi

    curl -fL -o "$PLAYIT_DIR/playit" "$asset_url"
    chmod +x "$PLAYIT_DIR/playit"

    if [ -n "$release_tag" ]; then
        printf '%s' "$release_tag" > "$PLAYIT_VERSION_FILE"
    fi

    cecho "32" "Playit installed."
}

playit_get_secret_key() {
    if [ ! -f "$PLAYIT_CONFIG_FILE" ]; then
        return 1
    fi
    awk -F= '/secret_key/ {gsub(/["[:space:]]/, "", $2); print $2; exit}' "$PLAYIT_CONFIG_FILE"
}

playit_write_secret_config() {
    local secret_key="$1"
    mkdir -p "$PLAYIT_DIR"
    cat > "$PLAYIT_CONFIG_FILE" <<EOF
secret_key = "$secret_key"
EOF
    chmod 600 "$PLAYIT_CONFIG_FILE" 2>/dev/null || true
    printf '%s' "$secret_key" > "$PLAYIT_SECRET_FILE"
    chmod 600 "$PLAYIT_SECRET_FILE" 2>/dev/null || true
}

playit_get_agent_version() {
    local version_text

    version_text=$(cat "$PLAYIT_VERSION_FILE" 2>/dev/null || true)
    if [ -n "$version_text" ]; then
        printf '%s' "$version_text"
        return 0
    fi

    if [ -x "$PLAYIT_DIR/playit" ]; then
        version_text=$("$PLAYIT_DIR/playit" --version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n1)
        if [ -n "$version_text" ]; then
            printf '%s' "$version_text" > "$PLAYIT_VERSION_FILE"
            printf '%s' "$version_text"
            return 0
        fi
    fi

    return 1
}

playit_has_secret() {
    [ -n "$(playit_get_secret_key 2>/dev/null || true)" ]
}

playit_api_post() {
    local endpoint="$1"
    local auth_header="$2"
    local payload="$3"
    local response_file

    response_file=$(mktemp)

    if [ -n "$auth_header" ]; then
        if ! curl -sS -A "$USER_AGENT" -H "Authorization: $auth_header" -H "Content-Type: application/json" -d "$payload" "$PLAYIT_API_BASE/$endpoint" > "$response_file"; then
            rm -f "$response_file"
            return 1
        fi
    else
        if ! curl -sS -A "$USER_AGENT" -H "Content-Type: application/json" -d "$payload" "$PLAYIT_API_BASE/$endpoint" > "$response_file"; then
            rm -f "$response_file"
            return 1
        fi
    fi

    cat "$response_file"
    rm -f "$response_file"
}

playit_connectivity_check() {
    if ! curl -sS -I --connect-timeout 10 https://api.playit.gg >/dev/null 2>&1; then
        cecho "31" "Cannot reach api.playit.gg from Termux right now."
        return 1
    fi
}

playit_claim_code_from_log() {
    grep -ao 'https://playit.gg/claim/[A-Za-z0-9]\{10\}' "$PLAYIT_AGENT_BOOT_LOG" 2>/dev/null | tail -n1 | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]'
}

playit_start_boot_agent() {
    rm -f "$PLAYIT_AGENT_BOOT_LOG"
    cd "$PLAYIT_DIR"
    "$PLAYIT_DIR/playit" -s --secret_path "$PLAYIT_CONFIG_FILE" > "$PLAYIT_AGENT_BOOT_LOG" 2>&1 &
    echo $!
}

playit_stop_boot_agent() {
    local pid="$1"
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    fi
}

playit_auto_claim_secret() {
    local boot_pid claim_code guest_json session_key agent_version details_json setup_json accept_json exchange_json secret_key attempt

    playit_connectivity_check || return 1

    if [ ! -x "$PLAYIT_DIR/playit" ]; then
        cecho "31" "Playit is not installed."
        return 1
    fi

    agent_version=$(playit_get_agent_version || true)
    if [ -z "$agent_version" ]; then
        cecho "31" "Could not determine the Playit agent version."
        return 1
    fi

    boot_pid=$(playit_start_boot_agent)
    claim_code=""

    for attempt in $(seq 1 60); do
        claim_code=$(playit_claim_code_from_log || true)
        if [ -n "$claim_code" ]; then
            break
        fi
        sleep 1
    done

    if [ -z "$claim_code" ]; then
        playit_stop_boot_agent "$boot_pid"
        cecho "31" "Could not read a Playit claim code from the agent."
        [ -f "$PLAYIT_AGENT_BOOT_LOG" ] && tail -n 20 "$PLAYIT_AGENT_BOOT_LOG"
        return 1
    fi

    guest_json=$(playit_api_post "login/create/guest" "" "{}" || true)
    session_key=$(printf '%s' "$guest_json" | jq -r '.data.session_key // empty' 2>/dev/null)
    if [ -z "$session_key" ]; then
        playit_stop_boot_agent "$boot_pid"
        cecho "31" "Playit guest-session creation failed."
        printf '%s\n' "$guest_json"
        return 1
    fi

    for attempt in $(seq 1 60); do
        details_json=$(playit_api_post "claim/details" "bearer $session_key" "{\"code\":\"$claim_code\",\"agent_type\":\"self-managed\",\"version\":\"$agent_version\"}" || true)
        if [ "$(printf '%s' "$details_json" | jq -r '.status // empty' 2>/dev/null)" = "success" ]; then
            break
        fi
        if [ "$(printf '%s' "$details_json" | jq -r '.data // empty' 2>/dev/null)" != "WaitingForAgent" ]; then
            playit_stop_boot_agent "$boot_pid"
            cecho "31" "Playit claim/details failed."
            printf '%s\n' "$details_json"
            return 1
        fi
        sleep 1
    done

    setup_json=$(playit_api_post "claim/setup" "bearer $session_key" "{\"code\":\"$claim_code\",\"agent_type\":\"self-managed\",\"version\":\"$agent_version\"}" || true)
    if [ "$(printf '%s' "$setup_json" | jq -r '.status // empty' 2>/dev/null)" != "success" ]; then
        playit_stop_boot_agent "$boot_pid"
        cecho "31" "Playit claim/setup failed."
        printf '%s\n' "$setup_json"
        return 1
    fi

    accept_json=$(playit_api_post "claim/accept" "bearer $session_key" "{\"code\":\"$claim_code\",\"name\":\"cellhasher-${claim_code:0:4}\",\"agent_type\":\"self-managed\"}" || true)
    if [ "$(printf '%s' "$accept_json" | jq -r '.status // empty' 2>/dev/null)" != "success" ]; then
        playit_stop_boot_agent "$boot_pid"
        cecho "31" "Playit claim/accept failed."
        printf '%s\n' "$accept_json"
        return 1
    fi

    secret_key=""
    for attempt in $(seq 1 30); do
        exchange_json=$(playit_api_post "claim/exchange" "bearer $session_key" "{\"code\":\"$claim_code\"}" || true)
        secret_key=$(printf '%s' "$exchange_json" | jq -r '.data.secret_key // empty' 2>/dev/null)
        if [ -n "$secret_key" ]; then
            break
        fi
        if [ "$(printf '%s' "$exchange_json" | jq -r '.data // empty' 2>/dev/null)" != "NotAccepted" ]; then
            playit_stop_boot_agent "$boot_pid"
            cecho "31" "Playit claim/exchange failed."
            printf '%s\n' "$exchange_json"
            return 1
        fi
        sleep 1
    done

    playit_stop_boot_agent "$boot_pid"

    if [ -z "$secret_key" ]; then
        cecho "31" "Playit claim/exchange returned no secret key."
        return 1
    fi

    playit_write_secret_config "$secret_key"
    cecho "32" "Playit claimed successfully."
}

playit_get_agent_id() {
    local secret_key agent_json

    secret_key=$(playit_get_secret_key || true)
    if [ -z "$secret_key" ]; then
        return 1
    fi

    agent_json=$(playit_api_post "agents/rundata" "agent-key $secret_key" "{}" || true)
    printf '%s' "$agent_json" | jq -r '.data.agent_id // empty' 2>/dev/null
}

playit_ensure_tunnel() {
    local port="${1:-25565}"
    local protocol="${2:-tcp}"
    local secret_key agent_id tunnels_json existing_id tunnel_budget create_payload create_json

    secret_key=$(playit_get_secret_key || true)
    if [ -z "$secret_key" ]; then
        cecho "31" "No Playit secret key is configured."
        return 1
    fi

    agent_id=$(playit_get_agent_id || true)
    if [ -z "$agent_id" ]; then
        cecho "31" "Could not retrieve the Playit agent ID."
        return 1
    fi

    tunnels_json=$(playit_api_post "tunnels/list" "agent-key $secret_key" "{\"agent_id\":\"$agent_id\"}" || true)
    existing_id=$(printf '%s' "$tunnels_json" | jq -r --arg p "$port" --arg proto "$protocol" '.data.tunnels[]? | select((.origin.data.local_port|tostring) == $p and .port_type == $proto) | .id' 2>/dev/null | head -n1)
    if [ -n "$existing_id" ]; then
        cecho "32" "Playit tunnel already exists for port $port."
        return 0
    fi

    tunnel_budget=$(printf '%s' "$tunnels_json" | jq -r '[.data.tunnels[]? | .port_count] | add // 0' 2>/dev/null)
    if [ -n "$tunnel_budget" ] && [ "$tunnel_budget" -ge 4 ]; then
        cecho "33" "Playit tunnel limit reached."
        return 1
    fi

    create_payload=$(cat <<EOF
{"name":"minecraft-java-$(date +%s)","tunnel_type":"minecraft-java","port_type":"$protocol","port_count":1,"enabled":true,"origin":{"type":"agent","data":{"agent_id":"$agent_id","local_ip":"127.0.0.1","local_port":$port}}}
EOF
)

    create_json=$(playit_api_post "tunnels/create" "agent-key $secret_key" "$create_payload" || true)
    if [ "$(printf '%s' "$create_json" | jq -r '.status // empty' 2>/dev/null)" = "success" ]; then
        cecho "32" "Playit tunnel created for port $port."
        return 0
    fi

    cecho "31" "Failed to create the Playit tunnel."
    printf '%s\n' "$create_json"
    return 1
}

playit_is_running() {
    local pid

    if [ ! -f "$PLAYIT_PID_FILE" ]; then
        return 1
    fi

    pid=$(cat "$PLAYIT_PID_FILE" 2>/dev/null || true)
    if [ -z "$pid" ]; then
        rm -f "$PLAYIT_PID_FILE"
        return 1
    fi

    if kill -0 "$pid" 2>/dev/null; then
        return 0
    fi

    rm -f "$PLAYIT_PID_FILE"
    return 1
}

playit_status() {
    local secret_key agent_version agent_id

    clear
    line
    echo "Playit status"
    line

    if [ -x "$PLAYIT_DIR/playit" ]; then
        echo "Binary : installed"
    else
        echo "Binary : not installed"
    fi

    if playit_has_secret; then
        echo "Config : ready"
    else
        echo "Config : not ready"
    fi

    agent_version=$(playit_get_agent_version || true)
    if [ -n "$agent_version" ]; then
        echo "Version: $agent_version"
    else
        echo "Version: unknown"
    fi

    secret_key=$(playit_get_secret_key || true)
    if [ -n "$secret_key" ]; then
        echo "Secret : saved"
        agent_id=$(playit_get_agent_id || true)
        if [ -n "$agent_id" ]; then
            echo "Agent  : $agent_id"
        fi
    else
        echo "Secret : not saved"
    fi

    if playit_is_running; then
        echo "State  : running (PID $(cat "$PLAYIT_PID_FILE"))"
    else
        echo "State  : stopped"
    fi

    if [ -f "$PLAYIT_LOG_FILE" ]; then
        printf '\nRecent log:\n'
        tail -n 12 "$PLAYIT_LOG_FILE" 2>/dev/null || true
    fi
}

link_playit() {
    if [ ! -x "$PLAYIT_DIR/playit" ]; then
        cecho "31" "Install playit first."
        return 1
    fi

    clear
    line
    echo "Link playit"
    line
    echo "The playit agent will run in the foreground now."
    echo "Use the shown URL/code to link the device to your playit account."
    echo "After linking succeeds, press Ctrl+C to return to this menu."
    printf '\nPress ENTER to continue...'
    read -r _

    cd "$PLAYIT_DIR"
    "$PLAYIT_DIR/playit" -s --secret_path "$PLAYIT_CONFIG_FILE" || true
}

prompt_playit_secret_key() {
    local secret_key
    printf '\nEnter Playit secret key (leave blank to skip): '
    read -r -s secret_key
    printf '\n'

    if [ -z "$secret_key" ]; then
        return 1
    fi

    playit_write_secret_config "$secret_key"
    cecho "32" "Playit secret key saved."
    return 0
}

open_playit_secret_page() {
    clear
    line
    echo "Open Playit secret-key page"
    line
    echo "Opening: $PLAYIT_SECRET_URL"
    echo ""
    echo "If Android asks which browser to use, pick one."
    echo "After copying the key, return to Termux."
    termux-open-url "$PLAYIT_SECRET_URL" 2>/dev/null || am start -a android.intent.action.VIEW -d "$PLAYIT_SECRET_URL" >/dev/null 2>&1 || true
}

auto_setup_playit() {
    clear
    line
    echo "Auto playit setup"
    line
    echo "This mode tries the same automatic guest-claim flow used by auto-mcs."
    echo "If that fails, it returns to the Playit menu without manual fallback."

    if [ ! -x "$PLAYIT_DIR/playit" ]; then
        echo "Installing playit..."
        install_playit || true
    fi

    if [ ! -x "$PLAYIT_DIR/playit" ]; then
        cecho "31" "playit could not be installed."
        return 1
    fi

    if ! playit_has_secret; then
        echo ""
        echo "Trying full automatic Playit claim..."
        if ! playit_auto_claim_secret; then
            cecho "31" "Automatic Playit setup failed."
            cecho "33" "Returning to the Playit menu."
            return 1
        fi
    fi

    if playit_has_secret; then
        playit_ensure_tunnel 25565 tcp || true
        start_playit_background || return 1
        cecho "32" "Auto playit setup finished using automatic API mode."
        return 0
    fi
    cecho "31" "Automatic Playit setup could not complete."
    return 1
}

auto_playit_site_only() {
    clear
    line
    echo "Browser-assisted Playit key setup"
    line
    open_playit_secret_page
    printf '\nPress ENTER after you copied the key and returned to Termux...'
    read -r _
    prompt_playit_secret_key
}

start_playit_background() {
    local secret_key

    if [ ! -x "$PLAYIT_DIR/playit" ]; then
        cecho "31" "Install playit first."
        return 1
    fi

    mkdir -p "$PLAYIT_DIR"

    if playit_is_running; then
        cecho "33" "playit is already running."
        return 0
    fi

    cd "$PLAYIT_DIR"

    if playit_has_secret; then
        secret_key=$(playit_get_secret_key || true)
        if [ -z "$secret_key" ]; then
            cecho "31" "Saved Playit secret key is empty."
            return 1
        fi
        playit_write_secret_config "$secret_key"
        nohup "$PLAYIT_DIR/playit" -s --secret_path "$PLAYIT_CONFIG_FILE" > "$PLAYIT_LOG_FILE" 2>&1 &
    else
        if [ ! -f "$PLAYIT_CONFIG_FILE" ]; then
            cecho "31" "playit is not linked yet. Use secret-key mode or 'Link playit' first."
            return 1
        fi
        nohup "$PLAYIT_DIR/playit" -s --secret_path "$PLAYIT_CONFIG_FILE" > "$PLAYIT_LOG_FILE" 2>&1 &
    fi

    echo $! > "$PLAYIT_PID_FILE"
    sleep 2

    if playit_is_running; then
        cecho "32" "playit started in the background."
        cecho "32" "Use 'Playit status' to inspect the tunnel log."
    else
        cecho "31" "playit failed to stay running."
        [ -f "$PLAYIT_LOG_FILE" ] && tail -n 20 "$PLAYIT_LOG_FILE"
        return 1
    fi
}

stop_playit() {
    if ! playit_is_running; then
        cecho "33" "playit is not running."
        return 0
    fi

    local pid
    pid=$(cat "$PLAYIT_PID_FILE")
    kill "$pid" 2>/dev/null || true
    sleep 1

    if playit_is_running; then
        kill -9 "$pid" 2>/dev/null || true
    fi

    rm -f "$PLAYIT_PID_FILE"
    cecho "32" "playit stopped."
}

playit_menu() {
    while true; do
        playit_status
        printf '\n'
        line
        echo "1. Auto playit setup"
        echo "2. Browser-assisted Playit key setup"
        echo "3. Manual playit setup"
        echo "4. Show playit status"
        echo "5. Stop playit tunnel"
        echo "6. Back"
        printf '\nSelect [1-6]: '
        read -r choice

        case "$choice" in
            1) auto_setup_playit || true; pause ;;
            2) auto_playit_site_only || true; pause ;;
            3) manual_playit_menu ;;
            4) playit_status || true; pause ;;
            5) stop_playit || true; pause ;;
            6) return 0 ;;
        esac
    done
}

manual_playit_menu() {
    while true; do
        playit_status
        printf '\n'
        line
        echo "Manual playit setup"
        line
        echo "1. Install or update playit"
        echo "2. Link playit account"
        echo "3. Save Playit secret key"
        echo "4. Start playit tunnel"
        echo "5. Back"
        printf '\nSelect [1-5]: '
        read -r choice

        case "$choice" in
            1) install_playit || true; pause ;;
            2) link_playit ;;
            3) prompt_playit_secret_key || true; pause ;;
            4) start_playit_background || true; pause ;;
            5) return 0 ;;
        esac
    done
}

open_server_folder() {
    load_state
    if [ ! -d "$SERVER_DIR" ]; then
        cecho "31" "Server folder does not exist yet."
        return 1
    fi

    local shared_root export_dir doc_uri

    clear
    line
    echo "Open server folder"
    line
    echo "Preparing Android Files view..."

    if [ ! -d "$HOME/storage/shared" ]; then
        echo ""
        echo "Setting up Termux shared storage access..."
        termux-setup-storage >/dev/null 2>&1 || true
        sleep 2
    fi

    shared_root="$HOME/storage/shared"
    if [ ! -d "$shared_root" ]; then
        cecho "31" "Shared storage is not available in Termux."
        cecho "33" "Open Termux and grant storage permission first."
        return 1
    fi

    export_dir="$shared_root/CellhasherMCServer"
    rm -rf "$export_dir"
    mkdir -p "$export_dir"

    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete "$SERVER_DIR"/ "$export_dir"/
    else
        cp -a "$SERVER_DIR"/. "$export_dir"/
    fi

    echo "Exported server files to: $export_dir"

    doc_uri="content://com.android.externalstorage.documents/document/primary%3ACellhasherMCServer"

    termux-open "$export_dir" >/dev/null 2>&1 \
        || am start -a android.intent.action.VIEW -d "$doc_uri" >/dev/null 2>&1 \
        || am start -a android.intent.action.VIEW -d "file://$export_dir" >/dev/null 2>&1 \
        || true

    echo ""
    echo "If Android did not open the folder automatically,"
    echo "open Files and browse to: Internal storage/CellhasherMCServer"
}

change_ram() {
    load_state
    if [ -z "$SERVER_TYPE" ]; then
        cecho "31" "Install a server first."
        return 1
    fi
    prompt_ram "$RAM_GB"
    write_start_script
    save_state
    cecho "32" "RAM updated to ${RAM_GB} GB"
}

start_server() {
    load_state
    if [ ! -x "$START_SCRIPT" ]; then
        cecho "31" "No start script found. Install a server first."
        return 1
    fi
    show_connection_info
    printf '\nStart the server now? [Y/n]: '
    read -r answer
    if [ -z "$answer" ] || [[ "$answer" =~ ^[Yy]$ ]]; then
        printf '\n'
        exec "$START_SCRIPT"
    fi
}

main_menu() {
    load_state
    while true; do
        show_connection_info
        printf '\n'
        line
        echo "1. Install or reinstall server"
        echo "2. Install mods/plugins"
        echo "3. Start server"
        echo "4. Change RAM"
        echo "5. Open server folder"
        echo "6. Playit tunnel menu"
        echo "7. Refresh info"
        echo "8. Exit"
        printf '\nSelect [1-8]: '
        read -r choice

        case "$choice" in
            1) install_server || true; pause ;;
            2) install_addons || true; pause ;;
            3) start_server ;;
            4) change_ram || true; pause ;;
            5) open_server_folder || true ;;
            6) playit_menu ;;
            7) ;;
            8) exit 0 ;;
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
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Cellhasher-Minecraft-Hub/1.0"},
    )
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
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Cellhasher-Minecraft-Hub/1.0"},
    )
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
    device_script_path = "/data/local/tmp/cellhasher_mc_hub.sh"

    run_command([ADB, "-s", device_id, "shell", "am", "force-stop", "com.termux"], timeout=20)
    time.sleep(1)

    push_result = run_command([ADB, "-s", device_id, "push", local_script_path, device_script_path], text=True, timeout=60)
    if push_result.returncode != 0:
        return f"[{device_id}] Error: failed to push Termux hub script"

    run_command([ADB, "-s", device_id, "shell", "chmod", "755", device_script_path], timeout=20)
    grant_termux_permissions(device_id)
    run_command([ADB, "-s", device_id, "shell", "am", "start", "-n", "com.termux/com.termux.app.TermuxActivity"], timeout=30)
    time.sleep(15)

    run_command([ADB, "-s", device_id, "shell", "input", "text", "bash%s/data/local/tmp/cellhasher_mc_hub.sh"], timeout=20)
    time.sleep(0.5)
    run_command([ADB, "-s", device_id, "shell", "input", "keyevent", "66"], timeout=20)
    return f"[{device_id}] Success: Minecraft hub opened in Termux"


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
            future_map = {
                executor.submit(install_termux, device_id, apk_path): device_id
                for device_id in missing_devices
            }
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
    print("   Cellhasher Minecraft Android Server Hub")
    print("   Paper | Vanilla | Fabric | Bukkit | Modrinth | CurseForge")
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
        print("[*] Launching the Android Minecraft hub...")
        print()

        with ThreadPoolExecutor(max_workers=min(len(ready_devices), 4)) as executor:
            future_map = {
                executor.submit(launch_hub_on_device, device_id, local_script_path): device_id
                for device_id in ready_devices
            }
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
    print("   1. The script opens Termux on the selected device.")
    print("   2. Use the menu to install Paper, Vanilla, Fabric, or Bukkit.")
    print("   3. Set RAM inside the menu.")
    print("   4. Add mods/plugins using Modrinth or CurseForge links.")
    print("   5. Optional: install playit to expose the server outside your LAN.")
    print("=" * 64)


if __name__ == "__main__":
    main()
