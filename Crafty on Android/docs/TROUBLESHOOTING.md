# Troubleshooting

[Project overview](../README.md) · [Installation](INSTALLATION.md) · [Operations](OPERATIONS.md)

## Start with the logs

In Termux:

```sh
crafty-android status
cat "$HOME/cellhasher-crafty/install.status"
tail -n 100 "$HOME/cellhasher-crafty/logs/install.log"
crafty-android logs
```

Ctrl+C leaves the log viewer. Service logs use UTC. A missing status file
usually means setup did not reach creation of the installer state directory.

| Installer status | Meaning |
| --- | --- |
| `running` | Setup started; inspect logs to establish whether it is still progressing |
| `success:healthy` | Installation completed and the local HTTPS readiness check passed |
| `success:installed-not-started` | Installation completed with immediate startup disabled |
| `failed:NUMBER` | Installation exited unsuccessfully; inspect the preceding error |

The status file is a record of the last installer run, not continuous service
health monitoring. A successful panel check does not prove a Minecraft world
is running. The Python launcher also reports device failures through its exit
status.

## Installation and ADB problems

| Symptom | Action |
| --- | --- |
| No package mirrors are accessible; DNS resolution fails | Check that a website opens on the phone. Restore Wi-Fi/mobile connectivity before retrying. For a reachable but slow mirror, use Termux's `termux-change-repo` and retry after the previous package operation ends. |
| PRoot-Distro feature check fails | Run `pkg update` and inspect `proot-distro install --help`. The installer requires OCI image installation and the `--name` option. Follow Termux's normal package update procedure; do not replace a populated guest to fix a host tool. |
| `run-as` fails or Termux bootstrap is incomplete | Open Termux and wait for setup. If the build disallows `run-as`, install directly inside Termux; an installed app is not automatically replaced. |
| APK SHA-256 is missing or mismatched | Install Termux manually from an official source. Keep verification enabled. |
| ADB reports `unauthorized` or no device | Unlock the phone, accept its USB debugging prompt, check the cable, and run `adb devices -l`. Select a serial with `--device` when multiple phones are connected. |
| `ADB not found` | Put platform-tools on the PC's PATH or supply `--adb` / Cellhasher's `adb_path`. |
| `Panel port is unavailable` | Choose another port, such as `--port 9443`, and retain that port on later installer runs. Check other services before stopping anything. |
| Unknown service/app directory or a different Crafty revision | Back up and inspect the installation. The refusal protects an existing deployment; do not delete directories just to bypass it. |

## Panel cannot be reached

Run `crafty-android start` and inspect its result. Use **HTTPS** and the
configured panel port. On the phone, try `https://127.0.0.1:8443`. On another
LAN device, use the phone's current IP; check Wi-Fi client isolation or VPN
settings if local access works but LAN access fails.

For PC access over an authorized USB debugging connection:

```sh
adb -s YOUR_ADB_SERIAL forward tcp:8443 tcp:8443
```

Then open `https://127.0.0.1:8443` on the PC. Both ports above assume the default
8443 is free on the PC and configured on the phone. Forwarding depends on the
ADB connection and does not publish the panel to the internet.

A self-signed certificate warning is expected initially. Check the destination
before accepting it. Download verification remains enabled; only the installer's
loopback health probe accepts the panel's self-signed certificate directly.

## Crafty starts repeatedly or never becomes healthy

Inspect `crafty-android logs` before rerunning installation. The runit supervisor
can restart a process that exits, so repeated exceptions need their underlying
cause fixed.

If `max` reports unsupported server commands or a heap below its minimum:

```sh
crafty-android performance manual
crafty-android restart
```

This preserves existing commands. Correct them in Crafty before enabling `max`
again. A below-minimum calculated heap depends on total usable RAM and the
number of configured Java servers; closing apps does not increase that budget.
Closing apps can help actual runtime memory pressure.

Android may deny `/proc/filesystems`. The supplied launcher handles that
specific disk-discovery restriction. If the traceback still occurs, confirm
the managed installation includes `/opt/crafty/android-runtime.py` and has been
reinstalled from the current project files. Other errors are not silently hidden.

## Minecraft does not start or players cannot join

Inspect the individual server console in Crafty. Check EULA acceptance, the
chosen JVM, the execution command, available memory, and the Minecraft port.
Other Minecraft installations on the phone may already occupy 25565.

Panel login proves the controller is accessible; players need the separate
Minecraft address and a compatible client. Check a local LAN connection before
investigating VPN/router access. Carrier NAT may prevent inbound mobile-data
connections. Configure remote access separately from the installer.

## Boot, sleep, and interrupted shutdown

For boot failures, confirm matching Termux/Termux:Boot signatures, open the Boot
app once, enable `crafty-android boot on`, unlock the phone after reboot, and
inspect `~/cellhasher-crafty/logs/boot.log`. Check Android background and battery
settings. A saved hook alone does not confirm the receiver ran.

If Android stops all of Termux, reopen it and run `crafty-android start`.
If only Minecraft crashes, inspect its console and Crafty's per-server crash
detection settings. A controller supervisor does not enable server crash
detection automatically.

If `stop` times out, allow world saves to finish and inspect service/server
logs. Avoid force-killing PRoot while it traces a server that is saving. The
app-wide wake lock intentionally remains held after stop; use
`termux-wake-unlock` when no other Termux task needs it.

## Useful information for a bug report

Include the Android model/version, architecture, project commit, exact command
and flags, chosen panel port, failure message, and a short relevant log excerpt.
State whether direct Termux installation and ADB deployment differ. Redact
passwords, API tokens, addresses you wish to keep private, and player data.
Do not share `default-creds.txt`, a full database, or backup archives in a public
issue.
