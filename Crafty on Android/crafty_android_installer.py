#!/usr/bin/env python3
"""Cellhasher / standalone Termux installer for Crafty Controller on Android.

Only the Python standard library is required. --export-shell produces the same
standalone Bash installer that the ADB deployment runs on the phone.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request


SCRIPT_META = {
    "id": "crafty-on-android-v1",
    "name": "Crafty on Android",
    "description": "Install Crafty Controller and its HTTPS panel in Termux with Ubuntu, Java, supervised service management and optional Android boot startup.",
    "category": "Gaming",
    "type": "python",
    "version": "1.0.0",
    "author": "Cellhasher Team",
    "difficulty": "Advanced",
    "estimatedTime": "15-30 min",
    "tags": ["crafty", "minecraft", "android", "termux", "autostart", "performance"],
    "effects": {"power": {"reboot": False, "shutdown": False},
                "security": {"modifiesLockScreen": False}},
    "estimatedDurationSec": 1800,
    "downloads": 0,
    "rating": 5.0,
    "lastUpdated": "2026-10-14",
}

TERMUX_PREFIX = "/data/data/com.termux/files/usr"
TERMUX_HOME = "/data/data/com.termux/files/home"
# Auditable, reproducible source. Upgrades should be deliberate and revalidated.
CRAFTY_COMMIT = "fe65b372a4388552e9f4a1fe54251b2321f042fa"


CONFIG_HELPER = r'''#!/usr/bin/env python3
"""Run inside the guest, while Crafty is stopped; never rewrite its schema."""
import ast
from contextlib import closing
import json
import os
from pathlib import Path
import shlex
import sqlite3
import sys
import time

ROOT = Path("/opt/crafty/app")


def configure(root, port):
    config_path = root / "app/config/config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text())
        backup = config_path.with_name("config.json.before-android")
        if not backup.exists():
            backup.write_text(config_path.read_text())
            backup.chmod(0o600)
    else:
        # Read the upstream defaults without importing Crafty or triggering setup.
        tree = ast.parse((root / "app/classes/helpers/helpers.py").read_text())
        config = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "MASTER_CONFIG"
                for target in node.targets
            ):
                config = ast.literal_eval(node.value)
        if not isinstance(config, dict):
            raise RuntimeError("Upstream MASTER_CONFIG changed; review installer")
    config["https_port"] = int(port)
    config["base_url"] = f"localhost:{port}"
    config["show_errors"] = False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temp = config_path.with_suffix(".tmp")
    temp.write_text(json.dumps(config, indent=2) + "\n")
    temp.chmod(0o600)
    temp.replace(config_path)


def server_policy(root, policy):
    if policy not in {"all", "none", "keep"}:
        raise ValueError("Invalid server autostart policy")
    db_path = root / "app/config/db/crafty.sqlite"
    if policy == "keep" or not db_path.exists():
        return
    with closing(sqlite3.connect(f"file:{db_path}?mode=rw", uri=True, timeout=30)) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(servers)")}
        if not {"auto_start", "type"}.issubset(columns):
            raise RuntimeError("Crafty server schema changed; review installer")
        value = int(policy == "all")
        count = db.execute(
            "SELECT COUNT(*) FROM servers WHERE type = ? AND auto_start != ?",
            ("minecraft-java", value),
        ).fetchone()[0]
        if not count:
            return
        backup_path = db_path.with_name(f"crafty.before-autostart-{time.time_ns()}.sqlite")
        with closing(sqlite3.connect(backup_path)) as backup:
            db.backup(backup)
        backup_path.chmod(0o600)
        db.execute("UPDATE servers SET auto_start = ? WHERE type = ?",
                   (value, "minecraft-java"))
        db.commit()
        print(f"Set Java server autostart={bool(value)} for {count} server(s)")


def stop(root):
    # Check identity before signalling a PID that may have been reused.
    pidfile = root.parent / "crafty.pid"
    if not pidfile.exists():
        return False
    pid = int(pidfile.read_text().strip())
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except FileNotFoundError:
        return False
    allowed = {str(root / "main.py").encode(), str(root.parent / "android-runtime.py").encode()}
    if not allowed.intersection(argv):
        raise RuntimeError("PID no longer belongs to this Crafty instance")
    import signal
    os.kill(pid, signal.SIGTERM)
    return True


def hardware():
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.strip().split()[0]) // 1024
    try:
        cores = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cores = os.cpu_count() or 1
    total = memory["MemTotal"]
    available = memory.get("MemAvailable", memory.get("MemFree", 0))
    # Heap is a ceiling, not preallocated RAM. Reserve OS/controller/native JVM
    # headroom. Report free RAM separately so cached/background apps do not make
    # the configured ceiling unpredictable at boot.
    budget = max(0, min(total * 70 // 100, total - 1536))
    return {"cores": cores, "total_mb": total, "available_mb": available,
            "combined_heap_budget_mb": budget}


def tune_command(command, heap_mb, cores):
    tokens = shlex.split(command)
    if (not tokens or Path(tokens[0]).name != "java" or "-jar" not in tokens
            or any(token.startswith("@") for token in tokens)):
        return None
    jar = tokens.index("-jar")
    prefix = [token for token in tokens[1:jar]
              if not token.startswith(("-Xms", "-Xmx", "-XX:ActiveProcessorCount="))]
    return shlex.join([tokens[0], *prefix, "-Xms256M", f"-Xmx{heap_mb}M",
                       f"-XX:ActiveProcessorCount={cores}", *tokens[jar:]])


def performance(root, profile, measured=None):
    if profile == "manual":
        return
    if profile != "max":
        raise ValueError("Unknown performance profile")
    measured = hardware() if measured is None else measured
    print("Maximum performance profile:", json.dumps(measured))
    db_path = root / "app/config/db/crafty.sqlite"
    if not db_path.exists():
        print("Create/import a Java server, then restart Crafty to apply this profile.")
        return
    with closing(sqlite3.connect(f"file:{db_path}?mode=rw", uri=True, timeout=30)) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(servers)")}
        if not {"server_id", "type", "execution_command"}.issubset(columns):
            raise RuntimeError("Crafty server command schema changed; review installer")
        rows = db.execute("SELECT server_id, execution_command FROM servers WHERE type = ?",
                          ("minecraft-java",)).fetchall()
        if not rows:
            return
        heap = measured["combined_heap_budget_mb"] // len(rows)
        heap = heap // 64 * 64
        if heap < 512:
            raise RuntimeError("Not enough free RAM for max profile (512 MB/server minimum). Close other apps or select manual.")
        changes = []
        for server_id, command in rows:
            tuned = tune_command(command, heap, measured["cores"])
            if tuned is None:
                # Never guess how to edit a shell script, custom wrapper or argfile.
                raise RuntimeError(f"Server {server_id} uses a custom command. Select manual performance and tune it in Crafty.")
            if tuned != command:
                changes.append((tuned, server_id))
        if changes:
            backup_path = db_path.with_name(f"crafty.before-performance-{time.time_ns()}.sqlite")
            with closing(sqlite3.connect(backup_path)) as backup:
                db.backup(backup)
            backup_path.chmod(0o600)
            db.executemany("UPDATE servers SET execution_command = ? WHERE server_id = ?", changes)
            db.commit()
        print(f"Java servers: {len(rows)}, heap ceiling each: {heap} MB, available CPU cores: {measured['cores']}")
        if measured.get("available_mb", heap * len(rows) + 512) < heap * len(rows) + 384:
            print("Heap ceilings exceed currently free RAM. Close other apps before running busy worlds; Android memory pressure can still stop a server.")


if __name__ == "__main__":
    if sys.argv[1] == "configure":
        configure(ROOT, sys.argv[2])
    elif sys.argv[1] == "policy":
        server_policy(ROOT, sys.argv[2])
    elif sys.argv[1] == "stop":
        raise SystemExit(0 if stop(ROOT) else 3)
    elif sys.argv[1] == "performance":
        performance(ROOT, sys.argv[2])
    elif sys.argv[1] == "hardware":
        print(json.dumps(hardware(), indent=2))
    else:
        raise SystemExit("Unknown guest helper command")
'''

ANDROID_RUNTIME = r'''#!/usr/bin/env python3
"""Android procfs compatibility; no changes to Crafty's upstream source."""
from collections import namedtuple
import os
from pathlib import Path
import runpy
import sys

ROOT = Path("/opt/crafty/app")


def install_compat(psutil, storage=ROOT):
    original_partitions = psutil.disk_partitions
    warned = False

    def android_partitions(all=False):
        nonlocal warned
        try:
            return original_partitions(all=all)
        except PermissionError:
            if not warned:
                print("Android restricts disk discovery; monitoring Crafty's app storage only.", flush=True)
                warned = True
            partition = namedtuple("sdiskpart", "device mountpoint fstype opts")
            # disk_usage still queries the real directory with statvfs; no
            # capacity or utilization values are fabricated.
            return [partition("android-app-storage", str(storage), "unknown", "rw")]

    psutil.disk_partitions = android_partitions


if __name__ == "__main__":
    import psutil
    os.chdir(ROOT)
    install_compat(psutil)
    sys.path.insert(0, str(ROOT))
    sys.argv[0] = str(ROOT / "main.py")
    runpy.run_path(str(ROOT / "main.py"), run_name="__main__")
'''

GUEST_SETUP = r'''#!/bin/bash
set -Eeuo pipefail
umask 077
export DEBIAN_FRONTEND=noninteractive
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
commit="$1"
port="$2"
. /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || {
    echo 'Expected Ubuntu 24.04. Update proot-distro and retry.' >&2; exit 1;
}
# PRoot has no systemd. Prevent package postinst hooks from starting services.
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod 755 /usr/sbin/policy-rc.d
apt-get update
apt-get install -y --no-install-recommends ca-certificates git python3 python3-venv \
    python3-dev build-essential pkg-config libffi-dev libssl-dev libjpeg-dev \
    zlib1g-dev rustc cargo passwd util-linux openjdk-21-jre-headless
# Java 25 is useful for newer Minecraft releases; Java 21 remains available.
if apt-cache show openjdk-25-jre-headless >/dev/null 2>&1; then
    apt-get install -y --no-install-recommends openjdk-25-jre-headless
fi
id crafty >/dev/null 2>&1 || useradd --create-home --shell /bin/bash crafty
mkdir -p /opt/crafty
chown crafty:crafty /opt/crafty
if [[ ! -d /opt/crafty/app/.git ]]; then
    [[ ! -e /opt/crafty/app ]] || { echo 'Refusing to overwrite an unknown app directory'; exit 1; }
    runuser -u crafty -- git clone https://gitlab.com/crafty-controller/crafty-4.git /opt/crafty/app
    runuser -u crafty -- git -C /opt/crafty/app checkout --detach "$commit"
else
    actual=$(runuser -u crafty -- git -C /opt/crafty/app rev-parse HEAD)
    [[ "$actual" == "$commit" ]] || {
        echo 'Existing Crafty revision differs. Back up and review before upgrading.' >&2; exit 1;
    }
fi
runuser -u crafty -- python3 -m venv /opt/crafty/venv
runuser -u crafty -- /opt/crafty/venv/bin/python -m pip install --upgrade pip wheel
runuser -u crafty -- /opt/crafty/venv/bin/python -m pip install -r /opt/crafty/app/requirements.txt
runuser -u crafty -- /opt/crafty/venv/bin/python -m pip check
install -o crafty -g crafty -m 700 /mnt/cellhasher/config-helper.py /opt/crafty/config-helper.py
install -o crafty -g crafty -m 700 /mnt/cellhasher/guest-run.sh /opt/crafty/run.sh
install -o crafty -g crafty -m 700 /mnt/cellhasher/android-runtime.py /opt/crafty/android-runtime.py
runuser -u crafty -- python3 /opt/crafty/config-helper.py configure "$port"
runuser -u crafty -- /bin/bash -c 'cd /opt/crafty/app; /opt/crafty/venv/bin/python -c "from app.classes.helpers.helpers import Helpers; assert not Helpers.check_root()"'
java -version
echo 'Crafty dependencies and non-root user verified.'
'''

GUEST_RUN = r'''#!/bin/bash
set -Eeuo pipefail
umask 077
export TZ=Etc/UTC
cd /opt/crafty/app
exec 8>/opt/crafty/instance.lock
flock -n 8 || { echo 'Another Crafty instance holds the lock'; exit 1; }
python3 /opt/crafty/config-helper.py policy "$1"
python3 /opt/crafty/config-helper.py performance "$2"
# Upstream checks its session lock and removes stale entries itself. Preserve
# that protection against an instance started manually outside this wrapper.
printf '%s\n' "$$" > /opt/crafty/crafty.pid
exec /opt/crafty/venv/bin/python /opt/crafty/android-runtime.py --daemon
'''

SERVICE_RUN = r'''#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
umask 077
BASE="$HOME/cellhasher-crafty"
exec 2>&1
# Serialize against configuration/reinstallation, across the entire lifetime.
exec 9>"$BASE/instance.lock"
flock -n 9 || { echo 'Installer or service already holds the lock'; sleep 5; exit 1; }
policy=$(cat "$BASE/server-autostart")
profile=$(cat "$BASE/performance")
termux-wake-lock || true
guest=(proot-distro login cellhasher-crafty --user crafty --)
shutdown() {
    echo 'Requesting graceful Crafty and Minecraft shutdown...'
    # Startup may not have written its PID yet. Retry only until a TERM was
    # delivered, avoiding repeated signals while Minecraft is saving worlds.
    for ((i=0; i<60; i++)); do
        kill -0 "$child" 2>/dev/null || return 0
        "${guest[@]}" /usr/bin/python3 /opt/crafty/config-helper.py stop && return 0
        sleep 1
    done
    echo 'Could not deliver graceful shutdown; inspect the guest PID and logs.'
}
"${guest[@]}" /bin/bash /opt/crafty/run.sh "$policy" "$profile" &
child=$!
trap shutdown TERM INT
# wait is interrupted by a trapped signal; keep PRoot alive until Crafty has
# saved worlds and exited. Never kill PRoot first or its tracees may be killed.
while kill -0 "$child" 2>/dev/null; do
    wait "$child" && result=0 || result=$?
done
exit "${result:-1}"
'''

LOG_RUN = r'''#!/data/data/com.termux/files/usr/bin/sh
umask 077
mkdir -p "$HOME/cellhasher-crafty/logs/service"
exec svlogd -tt "$HOME/cellhasher-crafty/logs/service"
'''

CONTROL = r'''#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
umask 077
BASE="$HOME/cellhasher-crafty"
SERVICE="$PREFIX/var/service/crafty-android"
guest=(proot-distro login cellhasher-crafty --user crafty --)
start_supervisor() {
    # termux-services supplies the host runit supervisor; no systemd in PRoot.
    . "$PREFIX/etc/profile.d/start-services.sh"
    for ((i=0; i<30; i++)); do
        [[ -p "$SERVICE/supervise/ok" ]] && return 0
        sleep 1
    done
    echo 'runit supervisor did not become ready' >&2; return 1
}
health() {
    local port
    port=$(cat "$BASE/port")
    # Only this loopback health probe accepts Crafty's self-signed certificate.
    curl --noproxy '*' --silent --fail --insecure --max-time 5 \
        "https://127.0.0.1:$port/login" >/dev/null
}
case "${1:-menu}" in
    start)
        start_supervisor
        sv up "$SERVICE"
        for ((i=0; i<120; i++)); do
            if sv status "$SERVICE" | grep -q '^run:' && health; then
                printf 'Crafty is ready: https://127.0.0.1:%s\n' "$(cat "$BASE/port")"
                exit 0
            fi
            sleep 2
        done
        echo 'Crafty did not become healthy. Run: crafty-android logs' >&2; exit 1
        ;;
    stop)
        start_supervisor
        sv -w 180 down "$SERVICE" || {
            echo 'Graceful stop is still pending. Inspect logs; do not force-kill while saving worlds.' >&2
            exit 1
        }
        ;;
    restart)
        "$0" stop
        exec "$0" start
        ;;
    status)
        start_supervisor
        sv status "$SERVICE"
        health && echo 'HTTPS panel healthy' || { echo 'HTTPS panel unavailable'; exit 1; }
        ;;
    logs) tail -n 100 -F "$BASE/logs/service/current" ;;
    credentials) "${guest[@]}" /bin/cat /opt/crafty/app/app/config/default-creds.txt ;;
    shell) exec proot-distro login cellhasher-crafty --user crafty ;;
    boot)
        case "${2:-}" in
            on)
                mkdir -p "$HOME/.termux/boot"
                cp "$BASE/boot-template.sh" "$HOME/.termux/boot/30-cellhasher-crafty"
                chmod 700 "$HOME/.termux/boot/30-cellhasher-crafty"
                echo 'Boot hook enabled. Install matching Termux:Boot and open it once.'
                ;;
            off) rm -f "$HOME/.termux/boot/30-cellhasher-crafty"; echo 'Boot hook disabled' ;;
            *) echo 'Usage: crafty-android boot on|off' >&2; exit 2 ;;
        esac
        ;;
    server-autostart)
        case "${2:-}" in all|none|keep) ;; *) echo 'Choose all, none or keep' >&2; exit 2 ;; esac
        # The policy is applied by the guest on its next start, while stopped.
        printf '%s\n' "$2" > "$BASE/server-autostart.new"
        mv "$BASE/server-autostart.new" "$BASE/server-autostart"
        echo 'Saved. Policy applies to existing Java servers on the next Crafty start.'
        ;;
    performance)
        case "${2:-info}" in
            info) "${guest[@]}" /usr/bin/python3 /opt/crafty/config-helper.py hardware ;;
            max|manual)
                printf '%s\n' "$2" > "$BASE/performance.new"
                mv "$BASE/performance.new" "$BASE/performance"
                echo 'Saved. Profile applies on next restart. manual preserves current server commands; max recalculates heap/cores.'
                ;;
            *) echo 'Usage: crafty-android performance info|max|manual' >&2; exit 2 ;;
        esac
        ;;
    menu)
        printf '\nCrafty on Android\n1) Start\n2) Stop\n3) Restart\n4) Status\n5) Logs\n6) Initial credentials\n7) Enable boot\n8) Disable boot\n9) Server autostart policy\n10) Performance profile\n0) Exit\n'
        read -r -p 'Choose: ' choice
        case "$choice" in
            1) exec "$0" start ;; 2) exec "$0" stop ;; 3) exec "$0" restart ;;
            4) exec "$0" status ;; 5) exec "$0" logs ;; 6) exec "$0" credentials ;;
            7) exec "$0" boot on ;; 8) exec "$0" boot off ;;
            9) read -r -p 'all / none / keep: ' policy; exec "$0" server-autostart "$policy" ;;
            10) read -r -p 'max / manual / info: ' profile; exec "$0" performance "$profile" ;;
            0) exit 0 ;; *) exit 2 ;;
        esac
        ;;
    *) echo 'Commands: start stop restart status logs credentials shell boot server-autostart performance' >&2; exit 2 ;;
esac
'''

BOOT = r'''#!/data/data/com.termux/files/usr/bin/bash
set -eu
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH="$PREFIX/bin:/system/bin"
umask 077
mkdir -p "$HOME/cellhasher-crafty/logs"
exec >>"$HOME/cellhasher-crafty/logs/boot.log" 2>&1
# Let Android finish unlocking app storage. An already-running instance is safe.
sleep 15
exec "$PREFIX/bin/crafty-android" start
'''

INSTALL_HEAD = r'''#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
umask 077
[[ "${PREFIX:-}" == /data/data/com.termux/files/usr || "${PREFIX:-}" == /data/user/0/com.termux/files/usr ]] || {
    echo 'Run this installer inside the primary Android user Termux app.' >&2; exit 1;
}
[[ "$(id -u)" != 0 ]] || { echo 'Run as the Termux app user, without su'; exit 1; }
export PATH="$PREFIX/bin:/system/bin"
BASE="$HOME/cellhasher-crafty"
SERVICE="$PREFIX/var/service/crafty-android"
BOOT_CHOICE=ask
POLICY=ask
START_NOW=ask
PERFORMANCE=ask
PORT=8443
while (($#)); do
    case "$1" in
        --boot|--server-autostart|--start-now|--performance|--port)
            (($# >= 2)) || { echo "Missing value: $1" >&2; exit 2; }
            case "$1" in
                --boot) BOOT_CHOICE="$2" ;; --server-autostart) POLICY="$2" ;;
                --start-now) START_NOW="$2" ;; --port) PORT="$2" ;;
                --performance) PERFORMANCE="$2" ;;
            esac
            shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
ask() {
    local answer
    [[ -t 0 ]] || { echo 'Noninteractive install: supply --boot, --server-autostart, --performance and --start-now.' >&2; exit 2; }
    read -r -p "$1" answer
    printf '%s' "${answer:-$2}"
}
printf '\n=== Crafty on Android | Cellhasher ===\n'
[[ "$BOOT_CHOICE" != ask ]] || BOOT_CHOICE=$(ask 'Start Crafty on Android boot? yes/no [no]: ' no)
[[ "$POLICY" != ask ]] || POLICY=$(ask 'Java servers at Crafty startup: all/none/keep [keep]: ' keep)
[[ "$START_NOW" != ask ]] || START_NOW=$(ask 'Start the web panel after installation? yes/no [yes]: ' yes)
[[ "$PERFORMANCE" != ask ]] || PERFORMANCE=$(ask 'Performance: max (auto heap/all cores) / manual [manual]: ' manual)
[[ "$BOOT_CHOICE" == yes || "$BOOT_CHOICE" == no ]] || exit 2
[[ "$START_NOW" == yes || "$START_NOW" == no ]] || exit 2
[[ "$POLICY" == all || "$POLICY" == none || "$POLICY" == keep ]] || exit 2
[[ "$PERFORMANCE" == max || "$PERFORMANCE" == manual ]] || exit 2
[[ "$PORT" =~ ^[1-9][0-9]{3,4}$ ]] && ((PORT <= 65535)) || { echo 'Port must be 1024..65535'; exit 2; }
((PORT >= 1024)) || exit 2
case "$(uname -m)" in aarch64|x86_64) ;; *) echo 'A 64-bit ARM or x86 Termux environment is required'; exit 1 ;; esac
mkdir -p "$BASE/logs" "$BASE/payload"
chmod 700 "$BASE"
exec > >(tee -a "$BASE/logs/install.log") 2>&1
printf 'running\n' > "$BASE/install.status"
trap 'code=$?; if ((code)); then printf "failed:%s\n" "$code" > "$BASE/install.status"; echo "Installation failed. See $BASE/logs/install.log"; fi' EXIT
# Keep the device awake during long package extraction as well as service use.
if command -v termux-wake-lock >/dev/null 2>&1; then termux-wake-lock || true; fi
pkg update -y
pkg install -y proot-distro termux-services termux-tools curl util-linux python
if [[ -f "$SERVICE/run" && ! -f "$BASE/managed-v1" ]]; then
    echo 'Refusing to replace an unrecognized service'; exit 1
fi
if [[ -f "$SERVICE/run" ]]; then
    "$PREFIX/bin/crafty-android" stop
fi
exec 9>"$BASE/instance.lock"
flock -n 9 || { echo 'Another install or running instance holds the lock'; exit 1; }
python - "$PORT" <<'CELLHASHER_PORT_CHECK'
import socket
import sys
with socket.socket() as listener:
    try:
        listener.bind(("0.0.0.0", int(sys.argv[1])))
    except OSError as error:
        raise SystemExit(f"Panel port is unavailable: {error}. Choose another --port.")
CELLHASHER_PORT_CHECK
# Require OCI-aware PRoot-Distro to pin Ubuntu 24.04 rather than a moving alias.
proot_help=$(proot-distro install --help 2>&1)
if [[ "$proot_help" != *--name* ]]; then
    echo 'This installer needs OCI-aware proot-distro (v5+). Update Termux packages first.'
    exit 1
fi
if ! proot-distro login cellhasher-crafty -- /bin/true >/dev/null 2>&1; then
    proot-distro install ubuntu:24.04 --name cellhasher-crafty
fi
'''

INSTALL_TAIL = r'''
proot-distro login cellhasher-crafty --bind "$BASE/payload:/mnt/cellhasher" -- \
    /bin/bash /mnt/cellhasher/guest-setup.sh __CRAFTY_COMMIT__ "$PORT"
mkdir -p "$SERVICE/log" "$BASE/logs/service"
# Set down before publishing run: runsvdir may discover this directory at once.
touch "$SERVICE/down"
printf 's1000000\nn5\n' > "$BASE/logs/service/config"
cp "$BASE/payload/service-run.sh" "$SERVICE/run"
cp "$BASE/payload/log-run.sh" "$SERVICE/log/run"
cp "$BASE/payload/control.sh" "$PREFIX/bin/crafty-android"
cp "$BASE/payload/boot.sh" "$BASE/boot-template.sh"
chmod 700 "$SERVICE/run" "$SERVICE/log/run" "$PREFIX/bin/crafty-android" "$BASE/boot-template.sh"
# Keep down present: only an explicit start or our optional boot hook starts it.
touch "$SERVICE/down" "$BASE/managed-v1"
printf '%s\n' "$PORT" > "$BASE/port"
printf '%s\n' "$POLICY" > "$BASE/server-autostart"
printf '%s\n' "$PERFORMANCE" > "$BASE/performance"
if [[ "$BOOT_CHOICE" == yes ]]; then crafty-android boot on; else crafty-android boot off; fi
# Release the install lock before the supervised process acquires it.
flock -u 9
exec 9>&-
if [[ "$START_NOW" == yes ]]; then
    crafty-android start
    printf 'success:healthy\n' > "$BASE/install.status"
else
    printf 'success:installed-not-started\n' > "$BASE/install.status"
fi
printf '\nInstalled Crafty. Panel: https://127.0.0.1:%s (or https://PHONE-IP:%s on your LAN).\n' "$PORT" "$PORT"
echo 'Commands: crafty-android menu | start | stop | restart | status | logs | credentials'
echo 'Performance: crafty-android performance info | max | manual (applies on next restart)'
echo 'After first start: crafty-android credentials; change the generated password in the panel.'
echo 'Create/import a Java server in Crafty, choose the required Java version and accept the Minecraft EULA there.'
echo 'The all/none autostart policy applies to existing Java servers at the next Crafty startup; keep preserves per-server settings.'
echo 'For boot: install Termux:Boot from the SAME signing source as Termux and open its launcher once.'
echo 'Allow background activity and disable battery optimization for Termux and Termux:Boot in Android settings.'
echo 'Android may still kill background processes. Keep backups and use modest RAM / view distance.'
'''


def render_installer():
    payload = {
        "config-helper.py": CONFIG_HELPER, "guest-setup.sh": GUEST_SETUP,
        "guest-run.sh": GUEST_RUN, "service-run.sh": SERVICE_RUN,
        "log-run.sh": LOG_RUN, "control.sh": CONTROL, "boot.sh": BOOT,
        "android-runtime.py": ANDROID_RUNTIME,
    }
    chunks = [INSTALL_HEAD]
    for index, (name, content) in enumerate(payload.items()):
        marker = f"CELLHASHER_PAYLOAD_{index}"
        chunks.append(f"\ncat > \"$BASE/payload/{name}\" <<'{marker}'\n{content}{marker}\n")
    chunks.append(INSTALL_TAIL.replace("__CRAFTY_COMMIT__", CRAFTY_COMMIT))
    return "".join(chunks)


def write_lf(path, content):
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)


def adb_shell(adb, device, *args, **kwargs):
    # adb shell reparses a command string on Android, even with shell=False on
    # the host. Quote every Android argument, including paths containing spaces.
    return run([adb, "-s", device, "shell", shlex.join(args)], **kwargs)


def latest_termux_apk(abi, directory):
    request = urllib.request.Request(
        "https://api.github.com/repos/termux/termux-app/releases/latest",
        headers={"User-Agent": "Cellhasher-Crafty/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    assets = [asset for asset in release.get("assets", [])
              if asset["name"].endswith(".apk")
              and "apt-android-7" in asset["name"]
              and (abi in asset["name"] or "universal" in asset["name"])]
    assets.sort(key=lambda asset: abi not in asset["name"])
    if not assets:
        raise RuntimeError("No compatible official Termux APK in latest release")
    asset = assets[0]
    url = asset["browser_download_url"]
    if not url.startswith("https://github.com/termux/termux-app/releases/download/"):
        raise RuntimeError("Unexpected APK source")
    path = directory / "termux.apk"
    request = urllib.request.Request(url, headers={"User-Agent": "Cellhasher-Crafty/1.0"})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=180) as response, path.open("wb") as output:
        while block := response.read(1024 * 1024):
            output.write(block)
            digest.update(block)
    expected = asset.get("digest")
    if not expected or expected != "sha256:" + digest.hexdigest():
        raise RuntimeError("APK SHA-256 missing or mismatched; install Termux manually from its official source")
    return path


def choices(args):
    for name, prompt, default, allowed in [
        ("boot", "Start on Android boot", "no", ("yes", "no")),
        ("server_autostart", "Java server autostart", "keep", ("all", "none", "keep")),
        ("start_now", "Start Crafty after installing", "yes", ("yes", "no")),
        ("performance", "Performance profile", "manual", ("max", "manual")),
    ]:
        if getattr(args, name) is not None:
            continue
        if sys.stdin.isatty():
            while True:
                value = input(f"{prompt} ({'/'.join(allowed)}) [{default}]: ").strip() or default
                if value in allowed:
                    break
        else:
            value = default
            print(f"[INFO] {prompt}: {default} (noninteractive default)")
        setattr(args, name, value)
    return ["--boot", args.boot, "--server-autostart", args.server_autostart,
            "--start-now", args.start_now, "--performance", args.performance, "--port", str(args.port)]


def deploy(args, device, options, directory):
    if not re.fullmatch(r"[A-Za-z0-9_.:\-\[\]]+", device):
        raise ValueError("Invalid ADB device serial")
    output = {"capture_output": True, "text": True, "timeout": 30}
    abi = adb_shell(args.adb, device, "getprop", "ro.product.cpu.abi", **output).stdout.strip()
    if abi not in {"arm64-v8a", "x86_64"}:
        raise RuntimeError(f"Unsupported Android ABI: {abi}")
    packages = adb_shell(args.adb, device, "pm", "list", "packages", "com.termux", **output).stdout.splitlines()
    if "package:com.termux" not in packages:
        apk = latest_termux_apk(abi, directory)
        run([args.adb, "-s", device, "install", "-r", str(apk)], timeout=180)
        adb_shell(args.adb, device, "am", "start", "-n", "com.termux/.app.TermuxActivity", **output)
        raise RuntimeError("Termux installed. Open it once, wait for its bootstrap to finish, then rerun this installer.")
    # Bring up the real app so its foreground service can hold the wake lock.
    # Existing sessions are preserved; never force-stop a running Minecraft host.
    adb_shell(args.adb, device, "am", "start", "-n", "com.termux/.app.TermuxActivity", **output)
    try:
        adb_shell(args.adb, device, "run-as", "com.termux", "test", "-x", TERMUX_PREFIX + "/bin/bash", **output)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            "ADB automation needs a debuggable Termux build and completed bootstrap. "
            "Existing Termux was preserved. Use --export-shell and run the installer manually in Termux."
        ) from error
    remote = "/data/local/tmp/cellhasher-crafty-install.sh"
    script = directory / "crafty-install.sh"
    write_lf(script, render_installer())
    try:
        run([args.adb, "-s", device, "push", str(script), remote], timeout=120)
        adb_shell(args.adb, device, "chmod", "644", remote, **output)
        # Stream into app-private storage, avoiding assumptions about shared
        # /sdcard permissions or the ability of an app to read /data/local/tmp.
        private = TERMUX_HOME + "/.cellhasher-crafty-install.sh"
        command = "cat " + shlex.quote(remote) + " | " + shlex.join([
            "run-as", "com.termux", "sh", "-c", f"umask 077; cat > {shlex.quote(private)}",
        ])
        run([args.adb, "-s", device, "shell", command], timeout=60)
        print(f"[{device}] Installing inside Termux; this can take 15-30 minutes.")
        adb_shell(args.adb, device, "run-as", "com.termux", "env",
                  f"HOME={TERMUX_HOME}", f"PREFIX={TERMUX_PREFIX}",
                  f"PATH={TERMUX_PREFIX}/bin:/system/bin", "TERM=xterm-256color",
                  TERMUX_PREFIX + "/bin/bash", private, *options, timeout=5400)
        print(f"[{device}] Installation completed. Open https://PHONE-IP:{args.port}")
    finally:
        subprocess.run([args.adb, "-s", device, "shell", "rm -f " + shlex.quote(remote)],
                       check=False, capture_output=True, timeout=30)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-shell", type=Path, metavar="FILE", help="Write a standalone Termux Bash installer; do not deploy")
    parser.add_argument("--device", action="append", help="ADB serial; repeat for multiple phones (or use Cellhasher devices env)")
    parser.add_argument("--adb", default=os.environ.get("adb_path", "adb"))
    parser.add_argument("--boot", choices=("yes", "no"))
    parser.add_argument("--server-autostart", choices=("all", "none", "keep"))
    parser.add_argument("--start-now", choices=("yes", "no"))
    parser.add_argument("--performance", choices=("max", "manual"))
    parser.add_argument("--port", type=int, default=8443)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    if args.export_shell:
        write_lf(args.export_shell, render_installer())
        print(f"Exported: {args.export_shell.resolve()}")
        return 0
    options = choices(args)
    if os.environ.get("PREFIX", "").rstrip("/") in {TERMUX_PREFIX, "/data/user/0/com.termux/files/usr"}:
        with tempfile.TemporaryDirectory(prefix="crafty-android-") as temp:
            path = Path(temp) / "install.sh"
            write_lf(path, render_installer())
            run(["bash", str(path), *options])
        return 0
    if not shutil.which(args.adb):
        parser.error("ADB not found. Set adb_path / --adb, or use --export-shell for manual Termux installation")
    devices = args.device or os.environ.get("devices", "").split()
    if not devices:
        result = run([args.adb, "devices"], capture_output=True, text=True, timeout=30)
        devices = [line.split()[0] for line in result.stdout.splitlines()[1:]
                   if len(line.split()) == 2 and line.split()[1] == "device"]
        if len(devices) != 1:
            parser.error("Connect exactly one authorized phone, or select phones with --device / devices")
    failed = 0
    for device in dict.fromkeys(devices):
        try:
            with tempfile.TemporaryDirectory(prefix="crafty-adb-") as temp:
                deploy(args, device, options, Path(temp))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            failed += 1
            print(f"[{device}] FAILED: {error}", file=sys.stderr)
    return int(failed > 0)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Inspect crafty-android status on the phone before rerunning.", file=sys.stderr)
        raise SystemExit(130)
