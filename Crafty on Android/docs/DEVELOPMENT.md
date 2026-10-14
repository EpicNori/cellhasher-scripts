# Developer guide

[Project overview](../README.md) · [Installation](INSTALLATION.md) · [Validation record](../VALIDATION.md)

## Source and runtime architecture

`crafty_android_installer.py` is the source of truth and uses only the Python
standard library on the launching machine. It contains `SCRIPT_META`, ADB
deployment logic, and the payload strings rendered into
`crafty_android_termux.sh`.

```text
Python / Cellhasher / standalone Bash
  -> Termux package setup and dedicated Ubuntu 24.04 guest
  -> non-root Crafty account, Python venv and Java installation
  -> Termux runit supervisor
     -> host service wrapper, instance lock and wake lock
        -> PRoot login as crafty
           -> guest lock, saved server policy and performance profile
              -> Android compatibility launcher -> Crafty main.py --daemon
                 -> HTTPS panel and configured Minecraft Java processes
```

The supervisor runs on the Termux host; there is no guest systemd service.
The host wrapper forwards shutdown to the verified Crafty PID and waits for
the traced process to exit. The Android launcher only substitutes app-storage
disk discovery when the original `psutil.disk_partitions` raises
`PermissionError`. It leaves other failures visible.

## File and state boundaries

| Location | Purpose |
| --- | --- |
| `~/cellhasher-crafty/port` | Configured HTTPS port |
| `~/cellhasher-crafty/server-autostart` | Saved `all`, `none`, or `keep` policy |
| `~/cellhasher-crafty/performance` | Saved `max` or `manual` profile |
| `~/cellhasher-crafty/payload/` | Rendered setup/control payloads |
| `~/cellhasher-crafty/logs/` | Install, boot, and rotating supervisor logs |
| `$PREFIX/bin/crafty-android` | Host management command |
| `$PREFIX/var/service/crafty-android` | Host runit service and log process |
| `~/.termux/boot/30-cellhasher-crafty` | Optional Android boot hook |
| `/opt/crafty/app` inside Ubuntu | Upstream application and controller/server data |
| `/opt/crafty/venv` inside Ubuntu | Crafty's Python environment |
| `/opt/crafty/config-helper.py` inside Ubuntu | Configuration, database policy, hardware and PID helper |
| `/opt/crafty/android-runtime.py` inside Ubuntu | Android disk-discovery compatibility launcher |

The helper updates existing Java server rows before Crafty starts. It checks
the expected columns and creates SQLite backups before changes. It introduces
no database schema migrations or external backend permission rules. Upstream
Crafty performs its own migrations.

## Regeneration and local checks

From `Crafty on Android` in the repository:

```sh
python crafty_android_installer.py --export-shell crafty_android_termux.sh
python -m unittest discover -s tests -v
bash -n crafty_android_termux.sh
git diff --check
```

Edit payloads in the Python source, then regenerate the shell artifact. The
suite checks that the committed shell bytes match the renderer. Folder-local
`.gitattributes` keeps scripts and Markdown in LF format across platforms.

Tests use temporary files/databases and mocks for network/ADB operations. Bash
syntax/control tests require Bash; set `BASH_TEST_BIN` to a usable executable
if the default command is unavailable. The existing real-device validation
record is historical evidence, not a claim that every future revision passes.

## Phone smoke test

With Crafty already installed and running, from the project directory:

```sh
python tests/smoke_device.py --device YOUR_ADB_SERIAL
```

Use `--adb PATH` for a custom executable and `--port PORT` for a nondefault
panel port. Add `--restart` when interrupting the active controller and its
servers is appropriate. The test reads the original credential file without
printing it; it cannot log in with that file after the admin password changes.
Verify login manually in that case.

The test checks service readiness, the login page, unauthenticated API denial,
authenticated server/statistics APIs, and the hardware report. It verifies TLS
against the certificate read from that phone and forwards the port to PC
localhost. The forwarding remains available after the test.

Gameplay, world import, sustained memory/temperature behavior, and an actual
Android reboot with Termux:Boot need separate acceptance tests. Record those
results explicitly in [VALIDATION.md](../VALIDATION.md).

## Upstream upgrades

Crafty is pinned by `CRAFTY_COMMIT` in the Python source. Before changing it:

1. Export and verify a full backup of the existing deployment.
2. Review upstream Python dependencies, Ubuntu/JVM support, configuration
   defaults, database schema, daemon invocation, PID handling, and disk discovery.
3. Review the helper's `MASTER_CONFIG` extraction and server-column assumptions.
4. Update the pin deliberately, regenerate the shell, and run local checks.
5. Test a fresh installation and a backed-up existing deployment on Android,
   including authentication, shutdown, and world saving.

The current installer rejects an existing different revision. Changing the pin
alone is not an implemented in-place migration path; do not delete the guard
or the guest to force an upgrade. Design and verify a backed-up migration first.

Keep private device logs, credentials, extracted tools, and temporary outputs
outside tracked files. The local `.gitignore` excludes `.test-output` and Python
bytecode. Include documentation and any validation-scope changes with runtime
changes.
