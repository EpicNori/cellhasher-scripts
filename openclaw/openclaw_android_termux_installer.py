#!/usr/bin/env python3
"""
OpenClaw Android Termux Installer for Cellhasher.

Uses direct execution inside Termux via `run-as com.termux`, provisions an
Ubuntu `proot-distro` environment, installs Node.js 22 there, applies the
Android network-interface workaround from Ali Solanki's guide, and launches the
OpenClaw onboarding flow inside Ubuntu.
"""

import os
import re
import shlex
import sys
import tempfile
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ADB = os.environ.get("adb_path", "adb")
DEVICES = [device for device in os.environ.get("devices", "").split() if device]

SCRIPT_META = {
    "id": "openclaw-android-termux-installer-v4",
    "name": "OpenClaw Android Termux Installer",
    "description": "Installs Termux if needed, provisions Ubuntu via proot-distro, installs Node.js 22, and installs OpenClaw in Ubuntu.",
    "category": "AI",
    "type": "python",
    "version": "4.0.0",
    "author": "Codex",
    "difficulty": "Advanced",
    "estimatedTime": "8-15 min",
    "tags": ["openclaw", "termux", "android", "cellhasher", "ssh", "tmux"],
    "effects": {
        "power": {"reboot": False, "shutdown": False},
        "security": {"modifiesLockScreen": False},
    },
    "estimatedDurationSec": 900,
    "downloads": 0,
    "rating": 5.0,
    "lastUpdated": "2026-03-27",
}

TERMUX_RELEASES_URL = "https://github.com/termux/termux-app/releases/latest"
TERMUX_FALLBACK_APK_URL = (
    "https://github.com/termux/termux-app/releases/download/"
    "v0.119.0-beta.3/"
    "termux-app_v0.119.0-beta.3+apt-android-7-github-debug_universal.apk"
)
TERMUX_PACKAGE = "com.termux"
TERMUX_HOME = "/data/user/0/com.termux/files/home"
TERMUX_PREFIX = "/data/user/0/com.termux/files/usr"
TERMUX_ENV = [
    "env",
    f"PATH={TERMUX_PREFIX}/bin:/system/bin",
    f"HOME={TERMUX_HOME}",
    f"PREFIX={TERMUX_PREFIX}",
]

TERMUX_SETUP_SCRIPT = r'''#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

export HOME=/data/user/0/com.termux/files/home
export PREFIX=/data/user/0/com.termux/files/usr
export PATH="$PREFIX/bin:/system/bin"
UBUNTU_ROOTFS="$PREFIX/var/lib/proot-distro/installed-rootfs/ubuntu"
UBUNTU_LOGIN=("$PREFIX/bin/proot-distro" login ubuntu --shared-tmp -- env -i HOME=/root USER=root LOGNAME=root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -lc)

LOG_DIR="$HOME/server/logs"
LOG_FILE="$LOG_DIR/openclaw-install.log"
STATUS_FILE="$LOG_DIR/openclaw-install.status"
mkdir -p "$HOME/server/bin" "$HOME/server/core" "$HOME/server/logs" "$HOME/server/models" "$HOME/server/scripts" "$HOME/server/temp"
: > "$LOG_FILE"
echo "running" > "$STATUS_FILE"
cleanup() {
  code=$?
  if [ "$code" -ne 0 ] && [ "$(cat "$STATUS_FILE" 2>/dev/null)" = "running" ]; then
    echo "failed:unexpected installer exit" > "$STATUS_FILE"
  fi
}
trap cleanup EXIT

log() {
  printf '%s %s\n' "$(date '+%F %T')" "$1" | tee -a "$LOG_FILE"
}

fail() {
  log "[ERROR] $1"
  echo "failed:$1" > "$STATUS_FILE"
  exit "${2:-1}"
}

log "[INFO] Starting OpenClaw Termux setup"
log "[INFO] Updating Termux packages"
pkg update 2>&1 | tee -a "$LOG_FILE"
pkg upgrade -y 2>&1 | tee -a "$LOG_FILE"
pkg install -y proot-distro python termux-tools 2>&1 | tee -a "$LOG_FILE"

for cmd in proot-distro python termux-wake-lock; do
  if command -v "$cmd" >/dev/null 2>&1; then
    log "[OK] Found $cmd"
  else
    fail "Missing required command: $cmd" 10
  fi
done

echo 'print("Server laeuft")' > "$HOME/server/scripts/test.py"
echo "server start" >> "$HOME/server/logs/system.log"

termux-wake-lock 2>&1 | tee -a "$LOG_FILE" || true

if [ ! -d "$UBUNTU_ROOTFS" ]; then
  log "[INFO] Installing Ubuntu in proot-distro"
  proot-distro install ubuntu 2>&1 | tee -a "$LOG_FILE"
else
  log "[INFO] Ubuntu proot-distro already present"
fi

ubuntu_has_openclaw() {
  local openclaw_path
  openclaw_path="$(
    "${UBUNTU_LOGIN[@]}" 'command -v openclaw || true' 2>/dev/null | tr -d '\r' | tail -n 1
  )"
  [ -n "$openclaw_path" ] || return 1
  case "$openclaw_path" in
    /usr/*|/bin/*) return 0 ;;
    *) return 1 ;;
  esac
}

cat > "$HOME/server/bin/openclaw_ubuntu.sh" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
export HOME=/data/user/0/com.termux/files/home
export PREFIX=/data/user/0/com.termux/files/usr
export PATH="$PREFIX/bin:/system/bin"
exec "$PREFIX/bin/proot-distro" login ubuntu --shared-tmp -- env -i HOME=/root USER=root LOGNAME=root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -lc '
  export NODE_OPTIONS="-r /root/hijack.js ${NODE_OPTIONS:-}"
  cd /root
  exec openclaw "$@"
' bash "$@"
EOF
chmod 755 "$HOME/server/bin/openclaw_ubuntu.sh"

cat > "$HOME/server/bin/enter_ubuntu.sh" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
export HOME=/data/user/0/com.termux/files/home
export PREFIX=/data/user/0/com.termux/files/usr
export PATH="$PREFIX/bin:/system/bin"
exec "$PREFIX/bin/proot-distro" login ubuntu --shared-tmp -- env -i HOME=/root USER=root LOGNAME=root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -il
EOF
chmod 755 "$HOME/server/bin/enter_ubuntu.sh"

cat > "$HOME/server/bin/start_openclaw.sh" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
export HOME=/data/user/0/com.termux/files/home
export PREFIX=/data/user/0/com.termux/files/usr
export PATH="$PREFIX/bin:/system/bin"
exec "$PREFIX/bin/proot-distro" login ubuntu --shared-tmp -- env -i HOME=/root USER=root LOGNAME=root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -lc '
  export NODE_OPTIONS="-r /root/hijack.js ${NODE_OPTIONS:-}"
  cd /root
  exec openclaw gateway --verbose
'
EOF
chmod 755 "$HOME/server/bin/start_openclaw.sh"

if [ -d "$UBUNTU_ROOTFS" ] && ubuntu_has_openclaw; then
  log "[INFO] Ubuntu and Ubuntu-installed OpenClaw already present"
  echo "success" > "$STATUS_FILE"
  log "[INFO] Launching OpenClaw inside Ubuntu"
  exec "$PREFIX/bin/proot-distro" login ubuntu --shared-tmp -- env -i HOME=/root USER=root LOGNAME=root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -lc '
    export NODE_OPTIONS="-r /root/hijack.js ${NODE_OPTIONS:-}"
    cd /root
    openclaw
    printf "\nOpenClaw exited. You are still in Ubuntu.\n\n"
    exec /bin/bash -il
  '
fi

log "[INFO] Configuring Ubuntu environment and installing OpenClaw"
env -i HOME=/root USER=root LOGNAME=root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  "$PREFIX/bin/proot-distro" login ubuntu --shared-tmp -- /bin/bash <<'EOF' 2>&1 | tee -a "$LOG_FILE"
set -euo pipefail
export HOME=/root
export USER=root
export LOGNAME=root
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export DEBIAN_FRONTEND=noninteractive

apt update
apt upgrade -y
apt install -y curl git build-essential ca-certificates

if ! command -v node >/dev/null 2>&1 || ! node -v | grep -q '^v22\.'; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt install -y nodejs
fi

npm install -g openclaw@latest

cat > /root/hijack.js <<'EOJS'
const os = require('os');
os.networkInterfaces = () => ({});
EOJS

if ! grep -Fq 'export NODE_OPTIONS="-r /root/hijack.js ${NODE_OPTIONS:-}"' /root/.bashrc 2>/dev/null; then
  printf '\nexport NODE_OPTIONS="-r /root/hijack.js ${NODE_OPTIONS:-}"\n' >> /root/.bashrc
fi
EOF

if ! "${UBUNTU_LOGIN[@]}" 'test -f /root/hijack.js'; then
  fail "Ubuntu setup verification failed" 22
fi
if ! ubuntu_has_openclaw; then
  fail "OpenClaw was not installed inside Ubuntu" 23
fi

python "$HOME/server/scripts/test.py" 2>&1 | tee -a "$LOG_FILE"
log "[OK] OpenClaw files installed"
log "[OK] Ubuntu helper written to $HOME/server/bin/openclaw_ubuntu.sh"
log "[OK] Ubuntu shell helper written to $HOME/server/bin/enter_ubuntu.sh"
log "[INFO] Launching OpenClaw onboarding inside Ubuntu"
echo "success" > "$STATUS_FILE"
exec "$PREFIX/bin/proot-distro" login ubuntu --shared-tmp -- env -i HOME=/root USER=root LOGNAME=root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -lc '
  export NODE_OPTIONS="-r /root/hijack.js ${NODE_OPTIONS:-}"
  cd /root
  openclaw onboard
  printf "\nOpenClaw onboarding finished. You are now in Ubuntu.\nUse: openclaw gateway --verbose\n\n"
  exec /bin/bash -il
'
'''


def run_subprocess(cmd, **kwargs):
    merged = {"capture_output": True, "text": True}
    merged.update(kwargs)
    print(f"[HOST] Running: {format_command(cmd)}")
    result = subprocess.run(cmd, **merged)
    log_completed_process(result)
    return result


def format_command(cmd):
    parts = []
    for item in cmd:
        text = str(item)
        if sys.platform == "win32":
            parts.append(subprocess.list2cmdline([text]))
        else:
            parts.append(shlex.quote(text))
    return " ".join(parts)


def log_completed_process(result):
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            print(f"[HOST][stdout] {line}")
    if result.stderr:
        for line in result.stderr.strip().splitlines():
            print(f"[HOST][stderr] {line}")
    print(f"[HOST] Exit code: {result.returncode}")


def adb_shell(device_id, *args, timeout=120000):
    return run_subprocess([ADB, "-s", device_id, "shell", *args], timeout=timeout)


def termux_exec(device_id, *args, timeout=120000):
    return adb_shell(device_id, "run-as", TERMUX_PACKAGE, *TERMUX_ENV, *args, timeout=timeout)


def get_device_model(device_id):
    result = adb_shell(device_id, "getprop", "ro.product.model", timeout=20000)
    return (result.stdout or "").strip() or "Unknown"


def is_termux_installed(device_id):
    result = adb_shell(device_id, "pm", "list", "packages", TERMUX_PACKAGE, timeout=20000)
    return TERMUX_PACKAGE in (result.stdout or "")


def fetch_termux_apk():
    req = urllib.request.Request(TERMUX_RELEASES_URL, headers={"User-Agent": "Cellhasher-OpenClaw-Installer/3.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8", "replace")
            final_url = response.geturl()
    except Exception:
        html = ""
        final_url = ""

    pattern = re.compile(
        r'/termux/termux-app/releases/download/[^"]+/'
        r'(termux-app_[^"]*apt-android-7[^"]*universal\.apk)'
    )
    match = pattern.search(html)
    if match:
        return "https://github.com" + match.group(0), match.group(1)

    if final_url:
        print("[WARN] Failed to parse latest Termux asset, using fallback.")
    return TERMUX_FALLBACK_APK_URL, TERMUX_FALLBACK_APK_URL.rsplit("/", 1)[-1]


def download_file(url, path):
    print(f"[*] Downloading: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as response, open(path, "wb") as handle:
        while True:
            chunk = response.read(1024 * 64)
            if not chunk:
                break
            handle.write(chunk)


def install_termux_apk(device_id, apk_path):
    result = run_subprocess([ADB, "-s", device_id, "install", "-r", apk_path], timeout=180000)
    combined = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0 or "Success" in combined, combined.strip()


def ensure_termux_permissions(device_id):
    for permission in [
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.WAKE_LOCK",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.POST_NOTIFICATIONS",
    ]:
        result = adb_shell(device_id, "pm", "grant", TERMUX_PACKAGE, permission, timeout=15000)
        if result.returncode != 0:
            print(f"[WARN] Could not grant {permission}; continuing")
    adb_shell(device_id, "settings", "put", "global", "stay_on_while_plugged_in", "3", timeout=15000)


def push_file(device_id, local_path, remote_path):
    result = run_subprocess([ADB, "-s", device_id, "push", local_path, remote_path], timeout=180000)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"adb push failed: {local_path}")


def write_temp_script(contents):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", delete=False, suffix=".sh") as handle:
        handle.write(contents)
        return handle.name


def open_termux_and_run(device_id, command_text):
    print(f"[{device_id}] Opening Termux on the phone for visible execution")
    adb_shell(device_id, "am", "force-stop", TERMUX_PACKAGE, timeout=15000)
    adb_shell(device_id, "am", "start", "-n", "com.termux/com.termux.app.TermuxActivity", timeout=30000)
    time.sleep(5)
    run_subprocess([ADB, "-s", device_id, "shell", "input", "keyevent", "67"], timeout=30000)
    run_subprocess([ADB, "-s", device_id, "shell", "input", "text", command_text], timeout=30000)
    run_subprocess([ADB, "-s", device_id, "shell", "input", "keyevent", "66"], timeout=30000)


def read_termux_file(device_id, path, timeout=15000):
    return adb_shell(device_id, "run-as", TERMUX_PACKAGE, "cat", path, timeout=timeout)


def reset_termux_run_state(device_id):
    for path in [
        f"{TERMUX_HOME}/server/logs/openclaw-install.status",
        f"{TERMUX_HOME}/server/logs/openclaw-install.log",
    ]:
        adb_shell(device_id, "run-as", TERMUX_PACKAGE, "rm", "-f", path, timeout=15000)


def wait_for_status(device_id, timeout_sec=2400, poll_sec=10):
    status_path = f"{TERMUX_HOME}/server/logs/openclaw-install.status"
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        result = read_termux_file(device_id, status_path, timeout=15000)
        status = (result.stdout or "").strip()
        if status == "success":
            return "success"
        if status.startswith("failed:"):
            return status
        time.sleep(poll_sec)
    return "timeout"


def process_device(device_id, apk_path, setup_script):
    print(f"[{device_id}] Model: {get_device_model(device_id)}")
    print(f"[{device_id}] OpenClaw itself will only be started inside the phone's Termux session")

    if not is_termux_installed(device_id):
        ok, output = install_termux_apk(device_id, apk_path)
        if not ok:
            return f"[{device_id}] FAILED - Termux install failed: {output}"
    else:
        print(f"[{device_id}] Termux already installed")

    ensure_termux_permissions(device_id)
    reset_termux_run_state(device_id)

    push_file(device_id, setup_script, "/data/local/tmp/openclaw-termux-setup.sh")
    adb_shell(device_id, "chmod", "755", "/data/local/tmp/openclaw-termux-setup.sh", timeout=15000)
    adb_shell(device_id, "chmod", "755", "/data/local/tmp/openclaw-termux-setup.sh", timeout=15000)
    open_termux_and_run(device_id, "bash%s/data/local/tmp/openclaw-termux-setup.sh")
    print(f"[{device_id}] Waiting for Termux setup status")
    status = wait_for_status(device_id)
    if status == "success":
        return f"[{device_id}] OK - Ubuntu and OpenClaw were installed inside Termux"
    if status == "timeout":
        return f"[{device_id}] INCOMPLETE - Setup is still running on the phone; check ~/server/logs/openclaw-install.log"
    return f"[{device_id}] FAILED - {status.removeprefix('failed:')}"


def main():
    print("=" * 68)
    print(" OpenClaw Android Termux Installer for Cellhasher")
    print("=" * 68)
    print("Validated pieces on a real Android 13 Samsung device:")
    print(" - visible Termux package install on the phone")
    print(" - Ubuntu provisioning with proot-distro")
    print(" - Node.js 22 and OpenClaw install inside Ubuntu")
    print()

    if not DEVICES:
        print("[ERROR] No devices found in environment variable 'devices'")
        return

    print("Manual prerequisites:")
    print("  1. USB debugging enabled and authorized")
    print("  2. Phone on stable power")
    print("  3. Phone has working Wi-Fi or mobile data")
    print()

    try:
        apk_url, apk_name = fetch_termux_apk()
        apk_path = os.path.join(tempfile.gettempdir(), apk_name)
        print(f"[*] Downloading Termux APK: {apk_name}")
        download_file(apk_url, apk_path)

    except Exception as exc:
        print(f"[ERROR] Host-side dependency preparation failed: {exc}")
        raise SystemExit(1) from exc
    setup_script = write_temp_script(TERMUX_SETUP_SCRIPT)

    print(f"[*] Devices selected: {len(DEVICES)}")
    for idx, device_id in enumerate(DEVICES, 1):
        print(f"  {idx}. {device_id}")
    print()

    results = []
    with ThreadPoolExecutor(max_workers=max(1, min(len(DEVICES), 4))) as pool:
        future_map = {
            pool.submit(process_device, device_id, apk_path, setup_script): device_id
            for device_id in DEVICES
        }
        for future in as_completed(future_map):
            device_id = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                result = f"[{device_id}] FAILED - {exc}"
            results.append(result)
            print(result)

    for path in (apk_path, setup_script):
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass

    print()
    print("=" * 68)
    print(" Summary")
    print("=" * 68)
    for line in results:
        print(line)
    print()
    print("If install succeeds, complete the visible `openclaw onboard` flow in Ubuntu.")
    print("The terminal will remain inside Ubuntu afterward for manual OpenClaw use.")
    print("Use `openclaw gateway --verbose` there, or later run `~/server/bin/enter_ubuntu.sh`.")


if __name__ == "__main__":
    main()
