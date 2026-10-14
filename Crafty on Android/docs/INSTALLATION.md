# Installation and options

[Project overview](../README.md) · [Operations](OPERATIONS.md) · [Troubleshooting](TROUBLESHOOTING.md)

## Requirements

Use the primary Android user's Termux installation on a 64-bit ARM or x86
device. The installer accepts `aarch64` and `x86_64`; 32-bit environments are
rejected. Install Termux from F-Droid or its official GitHub releases and let
its first-run bootstrap finish. Android 7+ and an internet connection are
required. Keep several GB of internal storage free for Ubuntu, Java, Python
build tools, and the eventual worlds and backups.

Termux's package repository must provide OCI-aware PRoot-Distro v5+.
Minecraft capacity depends on the phone and world. Start with one small Java
server and leave RAM for Android and Crafty. Allow 15–30 minutes for setup;
slow mirrors, devices, or native extension builds can take longer.

## Install in Termux

Run these commands in the Android Termux app:

```sh
pkg update -y
pkg install -y python curl
curl --fail --location 'https://raw.githubusercontent.com/EpicNori/cellhasher-scripts/main/Crafty%20on%20Android/crafty_android_installer.py' -o crafty_android_installer.py
python crafty_android_installer.py
```

The Python file contains all installation payloads. No companion Python package
or repository checkout is required. Interactive prompts select Android boot,
Minecraft autostart, immediate panel startup, and the performance profile.

For explicit, unattended settings:

```sh
python crafty_android_installer.py --boot yes --server-autostart all --performance max --start-now yes --port 8443
```

`--boot yes` writes a hook; complete Termux:Boot installation and activation
as described in [Operations](OPERATIONS.md#android-boot-startup).

## Standalone Bash alternative

```sh
curl --fail --location 'https://raw.githubusercontent.com/EpicNori/cellhasher-scripts/main/Crafty%20on%20Android/crafty_android_termux.sh' -o crafty_android_termux.sh
bash crafty_android_termux.sh --boot no --server-autostart keep --performance manual --start-now yes
```

Omit the options to answer prompts on the phone. Noninteractive Bash execution
requires all four choice flags; the port defaults to 8443. Run Bash inside
Termux as its normal app user. Do not launch the installer with `su` or from
inside an existing PRoot guest.

## Cellhasher and PC deployment

On the PC, use Python 3.9+ and Android platform-tools. Enable USB debugging,
connect the phone, and accept its debugging authorization prompt. From this
project's directory:

```sh
adb devices -l
python crafty_android_installer.py --device YOUR_ADB_SERIAL --boot no --server-autostart keep --performance max --start-now yes
```

The script reads Cellhasher's `adb_path` and space-separated `devices`
environment variables and exposes `SCRIPT_META`. `--adb` overrides the ADB
executable; repeated `--device` flags override the environment's device list.
With no selection, exactly one authorized connected device is required.
Selected devices run sequentially with the same settings; any failed device
makes the Python launcher return a failure status.

If Termux is absent, ADB deployment installs a compatible official release
APK after verifying its published SHA-256. Open Termux and rerun after its
bootstrap finishes. An existing Termux installation is preserved. Automated
execution needs `run-as com.termux`, which requires a debuggable build; use
direct Termux installation if your build does not allow it.

## Option reference

| Option | Accepted values | Effect |
| --- | --- | --- |
| `--boot` | `yes`, `no` | Create or remove this project's Android boot hook |
| `--server-autostart` | `all`, `none`, `keep` | Set the policy applied to existing Java servers before Crafty starts |
| `--performance` | `max`, `manual` | Tune standard Java commands, or preserve their current settings |
| `--start-now` | `yes`, `no` | Start the panel and check HTTPS readiness after installation |
| `--port` | Integer 1024–65535 | Set the panel's HTTPS port; default 8443 |
| `--device` | ADB serial, repeatable | Select phones; Python launcher only |
| `--adb` | Executable name or path | Select ADB; Python launcher only |
| `--export-shell` | Output file path | Write a standalone Bash installer without deploying it; Python only |

Interactive choice defaults are `boot=no`, `server-autostart=keep`,
`performance=manual`, and `start-now=yes`. A noninteractive Python launch uses
and prints those defaults for omitted choices. Specify every choice explicitly
when predictable unattended behavior matters. `--export-shell` exports the
installer itself; pass installation settings when running that shell file.

## First login

Run `crafty-android status`, then open `https://127.0.0.1:8443` on the phone
or `https://PHONE-IP:8443` from its LAN. Substitute your selected port. The
initial certificate is self-signed; verify the destination is your phone.

Read the generated credentials in Termux:

```sh
crafty-android credentials
```

Change the admin password through Crafty. This command reads the original
credential file; it does not reset a password changed in the panel. Continue
with [creating or importing a Minecraft server](OPERATIONS.md#first-minecraft-server).

## What installation changes

The installer installs Termux dependencies and creates a dedicated
`cellhasher-crafty` Ubuntu 24.04 guest, a non-root `crafty` guest account,
Java 21, Java 25 when Ubuntu provides it, a Python virtual environment,
and a host runit service. It stores its state in `~/cellhasher-crafty`.

It installs Crafty's panel and runtime. World creation/import and Minecraft
EULA acceptance happen in Crafty. The installer does not configure router
port forwarding, a VPN, Android thermal controls, or external backend rules.
