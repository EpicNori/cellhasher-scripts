#!/data/data/com.termux/files/usr/bin/bash
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

cat > "$BASE/payload/config-helper.py" <<'CELLHASHER_PAYLOAD_0'
#!/usr/bin/env python3
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
CELLHASHER_PAYLOAD_0

cat > "$BASE/payload/guest-setup.sh" <<'CELLHASHER_PAYLOAD_1'
#!/bin/bash
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
CELLHASHER_PAYLOAD_1

cat > "$BASE/payload/guest-run.sh" <<'CELLHASHER_PAYLOAD_2'
#!/bin/bash
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
CELLHASHER_PAYLOAD_2

cat > "$BASE/payload/service-run.sh" <<'CELLHASHER_PAYLOAD_3'
#!/data/data/com.termux/files/usr/bin/bash
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
CELLHASHER_PAYLOAD_3

cat > "$BASE/payload/log-run.sh" <<'CELLHASHER_PAYLOAD_4'
#!/data/data/com.termux/files/usr/bin/sh
umask 077
mkdir -p "$HOME/cellhasher-crafty/logs/service"
exec svlogd -tt "$HOME/cellhasher-crafty/logs/service"
CELLHASHER_PAYLOAD_4

cat > "$BASE/payload/control.sh" <<'CELLHASHER_PAYLOAD_5'
#!/data/data/com.termux/files/usr/bin/bash
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
CELLHASHER_PAYLOAD_5

cat > "$BASE/payload/boot.sh" <<'CELLHASHER_PAYLOAD_6'
#!/data/data/com.termux/files/usr/bin/bash
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
CELLHASHER_PAYLOAD_6

cat > "$BASE/payload/android-runtime.py" <<'CELLHASHER_PAYLOAD_7'
#!/usr/bin/env python3
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
CELLHASHER_PAYLOAD_7

proot-distro login cellhasher-crafty --bind "$BASE/payload:/mnt/cellhasher" -- \
    /bin/bash /mnt/cellhasher/guest-setup.sh fe65b372a4388552e9f4a1fe54251b2321f042fa "$PORT"
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
