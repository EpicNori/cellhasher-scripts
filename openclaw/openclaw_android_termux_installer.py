#!/usr/bin/env python3
"""
OpenClaw Android Termux Installer for Cellhasher.

Uses direct execution inside Termux via `run-as com.termux`, bootstraps Node/npm
offline over ADB, and installs OpenClaw with native Termux npm instead of the
official installer, which is not compatible with this Android/Termux setup.
"""

import os
import re
import sys
import tempfile
import subprocess
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
DEVICES = [device for device in os.environ.get("devices", "").split() if device]

SCRIPT_META = {
    "id": "openclaw-android-termux-installer-v3",
    "name": "OpenClaw Android Termux Installer",
    "description": "Installs Termux if needed, bootstraps Node/npm offline over ADB, and installs OpenClaw natively in Termux.",
    "category": "AI",
    "type": "python",
    "version": "3.0.0",
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
    "lastUpdated": "2026-03-21",
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
TERMUX_REPO_BASE = "https://packages.termux.dev/apt/termux-main/"
TERMUX_OFFLINE_PACKAGES = [
    ("pool/main/c/c-ares/c-ares_1.34.6_aarch64.deb", "c-ares_1.34.6_aarch64.deb"),
    ("pool/main/n/nodejs-lts/nodejs-lts_24.14.0_aarch64.deb", "nodejs-lts_24.14.0_aarch64.deb"),
    ("pool/main/n/npm/npm_11.12.0_all.deb", "npm_11.12.0_all.deb"),
]

TERMUX_SETUP_SCRIPT = r'''#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

export HOME=/data/user/0/com.termux/files/home
export PREFIX=/data/user/0/com.termux/files/usr
export PATH="$PREFIX/bin:/system/bin"

LOG_DIR="$HOME/server/logs"
LOG_FILE="$LOG_DIR/openclaw-install.log"
mkdir -p "$HOME/server/bin" "$HOME/server/core" "$HOME/server/logs" "$HOME/server/models" "$HOME/server/scripts" "$HOME/server/temp"
touch "$LOG_FILE"

log() {
  printf '%s %s\n' "$(date '+%F %T')" "$1" | tee -a "$LOG_FILE"
}

log "[INFO] Starting OpenClaw Termux setup"

for cmd in node npm curl git python; do
  if command -v "$cmd" >/dev/null 2>&1; then
    log "[OK] Found $cmd"
  else
    log "[ERROR] Missing required command: $cmd"
    exit 10
  fi
done

if ! curl -I --max-time 20 --retry 1 https://registry.npmjs.org/openclaw/latest >/dev/null 2>&1; then
  log "[ERROR] Phone has no working network/DNS for npm registry"
  exit 21
fi

git config --global user.name "server"
git config --global user.email "server@local"

echo 'print("Server laeuft")' > "$HOME/server/scripts/test.py"
echo "server start" >> "$HOME/server/logs/system.log"

rm -rf "$HOME/.openclaw/lib/node_modules/openclaw" "$HOME/.openclaw/bin/openclaw"
mkdir -p "$HOME/.openclaw"

log "[INFO] Installing OpenClaw with native Termux npm"
npm install -g --prefix "$HOME/.openclaw" --loglevel warn --no-fund --no-audit openclaw@latest 2>&1 | tee -a "$LOG_FILE"

if [ ! -f "$HOME/.openclaw/lib/node_modules/openclaw/openclaw.mjs" ]; then
  log "[ERROR] OpenClaw package layout missing after npm install"
  exit 22
fi

cat > "$PREFIX/bin/openclaw" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
export NODE_OPTIONS="--max-old-space-size=1536 ${NODE_OPTIONS:-}"
exec /data/user/0/com.termux/files/usr/bin/node /data/user/0/com.termux/files/home/.openclaw/lib/node_modules/openclaw/openclaw.mjs "$@"
EOF
chmod 755 "$PREFIX/bin/openclaw"

if ! grep -Fq 'export PATH="$HOME/.openclaw/bin:$PATH"' "$HOME/.bashrc" 2>/dev/null; then
  printf '\nexport PATH="$HOME/.openclaw/bin:$PATH"\n' >> "$HOME/.bashrc"
fi
if ! grep -Fq 'export NODE_OPTIONS="--max-old-space-size=1536 ${NODE_OPTIONS:-}"' "$HOME/.bashrc" 2>/dev/null; then
  printf 'export NODE_OPTIONS="--max-old-space-size=1536 ${NODE_OPTIONS:-}"\n' >> "$HOME/.bashrc"
fi

cat > "$HOME/server/bin/start_openclaw.sh" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
export PATH="/data/user/0/com.termux/files/usr/bin:$HOME/.openclaw/bin:/system/bin"
export NODE_OPTIONS="--max-old-space-size=1536 ${NODE_OPTIONS:-}"
exec openclaw gateway
EOF
chmod 755 "$HOME/server/bin/start_openclaw.sh"

python "$HOME/server/scripts/test.py" 2>&1 | tee -a "$LOG_FILE"
log "[OK] OpenClaw files installed"
log "[OK] Wrapper written to $PREFIX/bin/openclaw"
'''


def run_subprocess(cmd, **kwargs):
    merged = {"capture_output": True, "text": True}
    if sys.platform == "win32":
        merged["creationflags"] = CREATE_NO_WINDOW
    merged.update(kwargs)
    return subprocess.run(cmd, **merged)


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
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as response, open(path, "wb") as handle:
        while True:
            chunk = response.read(1024 * 64)
            if not chunk:
                break
            handle.write(chunk)


def download_offline_packages(cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    paths = []
    for rel_path, filename in TERMUX_OFFLINE_PACKAGES:
        local_path = os.path.join(cache_dir, filename)
        if not os.path.exists(local_path):
            download_file(TERMUX_REPO_BASE + rel_path, local_path)
        paths.append(local_path)
    return paths


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
        adb_shell(device_id, "pm", "grant", TERMUX_PACKAGE, permission, timeout=15000)
    adb_shell(device_id, "settings", "put", "global", "stay_on_while_plugged_in", "3", timeout=15000)


def push_file(device_id, local_path, remote_path):
    result = run_subprocess([ADB, "-s", device_id, "push", local_path, remote_path], timeout=180000)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"adb push failed: {local_path}")


def install_offline_runtime(device_id, local_debs):
    remote_paths = []
    for path in local_debs:
        remote = f"/data/local/tmp/{os.path.basename(path)}"
        push_file(device_id, path, remote)
        remote_paths.append(remote)

    result = termux_exec(device_id, f"{TERMUX_PREFIX}/bin/dpkg", "-i", *remote_paths, timeout=240000)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "offline dpkg install failed")

    node = termux_exec(device_id, f"{TERMUX_PREFIX}/bin/node", "-v", timeout=20000)
    npm = termux_exec(device_id, f"{TERMUX_PREFIX}/bin/npm", "-v", timeout=20000)
    if node.returncode != 0 or npm.returncode != 0:
        raise RuntimeError("node/npm verification failed after offline install")
    return node.stdout.strip(), npm.stdout.strip()


def phone_has_network(device_id):
    result = termux_exec(
        device_id,
        f"{TERMUX_PREFIX}/bin/curl",
        "-I",
        "--max-time",
        "20",
        "--retry",
        "1",
        "https://registry.npmjs.org/openclaw/latest",
        timeout=40000,
    )
    return result.returncode == 0


def write_temp_script(contents):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", delete=False, suffix=".sh") as handle:
        handle.write(contents)
        return handle.name


def open_termux_and_run(device_id, command_text):
    adb_shell(device_id, "am", "force-stop", TERMUX_PACKAGE, timeout=15000)
    adb_shell(device_id, "am", "start", "-n", "com.termux/com.termux.app.TermuxActivity", timeout=30000)
    run_subprocess([ADB, "-s", device_id, "shell", "input", "keyevent", "67"], timeout=30000)
    run_subprocess([ADB, "-s", device_id, "shell", "input", "text", command_text], timeout=30000)
    run_subprocess([ADB, "-s", device_id, "shell", "input", "keyevent", "66"], timeout=30000)


def process_device(device_id, apk_path, local_debs, setup_script):
    print(f"[{device_id}] Model: {get_device_model(device_id)}")

    if not is_termux_installed(device_id):
        ok, output = install_termux_apk(device_id, apk_path)
        if not ok:
            return f"[{device_id}] FAILED - Termux install failed: {output}"
    else:
        print(f"[{device_id}] Termux already installed")

    ensure_termux_permissions(device_id)
    node_version, npm_version = install_offline_runtime(device_id, local_debs)
    print(f"[{device_id}] Offline runtime ready: node {node_version}, npm {npm_version}")

    if not phone_has_network(device_id):
        return f"[{device_id}] BLOCKED - Phone has no working internet/DNS for npm registry"

    push_file(device_id, setup_script, "/data/local/tmp/openclaw-termux-setup.sh")
    adb_shell(device_id, "chmod", "755", "/data/local/tmp/openclaw-termux-setup.sh", timeout=15000)
    adb_shell(device_id, "chmod", "755", "/data/local/tmp/openclaw-termux-setup.sh", timeout=15000)
    open_termux_and_run(device_id, "bash%s/data/local/tmp/openclaw-termux-setup.sh")
    return f"[{device_id}] OK - Termux opened and OpenClaw install script was launched visibly on the device"


def main():
    print("=" * 68)
    print(" OpenClaw Android Termux Installer for Cellhasher")
    print("=" * 68)
    print("Validated pieces on a real Android 13 Samsung device:")
    print(" - offline Node/npm bootstrap via pushed Termux .deb files")
    print(" - native Termux npm install of openclaw")
    print(" - Termux-native wrapper generation in $PREFIX/bin")
    print()

    if not DEVICES:
        print("[ERROR] No devices found in environment variable 'devices'")
        return

    print("Manual prerequisites:")
    print("  1. USB debugging enabled and authorized")
    print("  2. Phone on stable power")
    print("  3. Phone has working Wi-Fi or mobile data")
    print()

    apk_url, apk_name = fetch_termux_apk()
    apk_path = os.path.join(tempfile.gettempdir(), apk_name)
    print(f"[*] Downloading Termux APK: {apk_name}")
    download_file(apk_url, apk_path)

    print("[*] Downloading offline Termux runtime packages")
    local_debs = download_offline_packages(os.path.join(os.getcwd(), "offline-cache"))
    setup_script = write_temp_script(TERMUX_SETUP_SCRIPT)

    print(f"[*] Devices selected: {len(DEVICES)}")
    for idx, device_id in enumerate(DEVICES, 1):
        print(f"  {idx}. {device_id}")
    print()

    results = []
    with ThreadPoolExecutor(max_workers=max(1, min(len(DEVICES), 4))) as pool:
        future_map = {
            pool.submit(process_device, device_id, apk_path, local_debs, setup_script): device_id
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
    print("If install succeeds, next on the phone: run `openclaw onboard` inside Termux.")


if __name__ == "__main__":
    main()
