# Crafty on Android

A Python installer for Cellhasher/ADB and direct Termux use, plus an equivalent
standalone Bash installer. Installs Crafty Controller's HTTPS web panel and Java
inside an isolated Ubuntu 24.04 PRoot distribution, without rooting Android.

## Install directly on the phone

Install **Termux from F-Droid or the official Termux GitHub releases**, open it,
and wait for its first-run bootstrap. Then run:

```sh
pkg update -y
pkg install -y python curl
curl --fail --location 'https://raw.githubusercontent.com/EpicNori/cellhasher-scripts/main/Crafty%20on%20Android/crafty_android_installer.py' -o crafty_android_installer.py
python crafty_android_installer.py
```

The installer asks whether to start at Android boot, how to handle Minecraft
server autostart, which performance profile to use, and whether to start the panel immediately. For unattended use:

```sh
python crafty_android_installer.py --boot yes --server-autostart all --performance max --start-now yes
```

The ready-to-run shell version offers the same choices:

```sh
curl --fail --location 'https://raw.githubusercontent.com/EpicNori/cellhasher-scripts/main/Crafty%20on%20Android/crafty_android_termux.sh' -o crafty_android_termux.sh
bash crafty_android_termux.sh
```

Requirements: Android 7+, primary Android user, 64-bit ARM (`aarch64`) or x86,
up-to-date Termux packages including OCI-aware `proot-distro` v5+, a stable
internet connection, and several GB of free **internal** app storage. Allow
15–30 minutes, potentially longer for slow devices or Python extension builds.
For useful Minecraft performance, start with one small world, 1 GB heap, low
view/simulation distance, and a phone with at least 4 GB total RAM. Leave memory
for Android, PRoot, and Crafty. These are starting points, not performance guarantees.

## Install through Cellhasher / ADB

Use `crafty_android_installer.py` as the Cellhasher script. It exposes
`SCRIPT_META` and reads the existing `adb_path` and space-separated `devices`
environment variables. Or run from a PC with Python 3.9+ and Android platform-tools:

```sh
python crafty_android_installer.py --device YOUR_ADB_SERIAL --boot yes --server-autostart all --performance max --start-now yes
```

One authorized connected device is selected automatically. Multiple devices
require explicit `--device` arguments or Cellhasher's `devices` selection.
Each device's result affects the final exit status. Choices are shared across
selected devices; run separately for different settings. Noninteractive Python
launches default to `--boot no --server-autostart keep --performance manual --start-now yes` and print
those defaults. Noninteractive shell launches require explicit choices.

If Termux is absent, the launcher downloads a compatible official release APK,
checks its GitHub-published SHA-256, and installs it. Open Termux once and rerun
after bootstrap finishes. It never replaces an installed Termux to change its
signature. ADB execution uses `run-as com.termux`, which requires a debuggable
Termux build; some distributions do not permit it. In that case install directly
in Termux using the instructions above. No root, shared-storage permissions,
screen input automation, or global Android settings changes are required.

## Open Crafty and create the Minecraft server

1. Open **https://127.0.0.1:8443** in the phone's browser. On another device on
   the same LAN, use **https://PHONE-IP:8443**. Use `--port 9443` during install
   if 8443 is occupied. Crafty uses a self-signed certificate initially; verify
   that you are connecting to your own phone before accepting the browser warning.
2. Run `crafty-android credentials` in Termux to read the generated initial
   admin credentials. Change the password in Crafty after signing in.
3. In Crafty's server creation/import flow, create a **Minecraft Java** server
   (for example Paper or Vanilla) or import an existing server. The installer
   installs the panel and Java; **it does not create a world or accept the
   Minecraft EULA for you**. Complete that flow in Crafty.
4. Choose the Java version required by your Minecraft release. Java 21 is
   installed; Java 25 is also installed if Ubuntu provides it. To inspect paths:
   `crafty-android shell`, then `ls /usr/lib/jvm`. Use the chosen JVM's absolute
   `bin/java` path in Crafty's server execution command when necessary.
5. Review RAM, server port (usually **25565/TCP**), view distance and simulation
   distance, accept the Minecraft EULA if you agree, then start the server in
   Crafty. Players use `PHONE-IP:25565`; the panel port is separate.
6. With `--server-autostart keep`, set **Auto Start** separately for each server
   in Crafty's server configuration. With `all`, restart Crafty after creating
   the server to apply the policy to that server. Save the world before restart.

Native Bedrock server binaries target other CPU/platform combinations; this
installer targets Java servers. Internet access requires your own VPN or router
configuration and may be restricted by mobile carrier NAT. Crafty's panel binds
to all network interfaces by default. No router ports are forwarded automatically.
Keep the panel on a trusted LAN/VPN, use a strong password, and manage users
through Crafty's own permissions.

## Boot and continuous operation

If boot startup is selected, a dedicated hook is written to
`~/.termux/boot/30-cellhasher-crafty`. You must install **Termux:Boot from the
same signing source as Termux** and **open its launcher once**. The installer
does not silently install a potentially incompatible Boot add-on. Android user
storage generally needs to be unlocked after reboot before this can run.

Allow notifications/background activity and disable battery optimization for
Termux and Termux:Boot. Some vendors also require an Android autostart permission.
The service acquires Termux's wake lock when starting. It intentionally leaves
the app-wide wake lock in place when stopping, so it cannot release a lock used
by another Termux task. Run `termux-wake-unlock` yourself if no other task needs it.

Termux's **runit** supervisor restarts Crafty if its process exits. The supervisor
runs outside PRoot; systemd is not used. The boot hook starts the service after
a short delay. Android force-stop, memory pressure, process limits, thermal
shutdown, a reboot before unlock, or battery exhaustion can still interrupt it;
an unrooted phone cannot guarantee 24/7 availability. Use a suitable power source,
monitor temperature, and schedule world backups in Crafty. If Android kills the
whole Termux process tree, reopen Termux and run `crafty-android start`.

`all`, `none`, and `keep` are separate from Android boot startup:

| Policy | On the next Crafty process startup |
| --- | --- |
| `all` | Enable Auto Start for every existing Minecraft Java server |
| `none` | Disable Auto Start for every existing Minecraft Java server |
| `keep` | Preserve Crafty's per-server Auto Start choices |

The policy runs before Crafty opens its database. It validates the existing
schema and creates a SQLite backup before changing any rows. New servers use
Crafty's defaults until their next Crafty restart or until configured in its UI.
This does not enable per-server crash detection; configure that in Crafty if wanted.

## Commands and data

```sh
crafty-android                 # Management menu
crafty-android start           # Wait until the local HTTPS panel responds
crafty-android stop            # Graceful Crafty/Minecraft shutdown; no forced kill
crafty-android restart
crafty-android status
crafty-android logs            # Follow supervisor output (Ctrl+C to leave)
crafty-android credentials     # Sensitive: do not paste this output into issue reports
crafty-android shell           # Linux shell as the non-root Crafty user
crafty-android boot on         # Still requires Termux:Boot setup
crafty-android boot off
crafty-android server-autostart all   # Or none / keep; applied on next start
crafty-android performance info      # Measured RAM, CPU cores, combined heap budget
crafty-android performance max       # Tune existing Java server heap/cores on next start
crafty-android performance manual    # Preserve server commands as configured in Crafty
```

## Maximum performance

Select `--performance max` in the installer, or run
`crafty-android performance max` followed by `crafty-android restart`. At each
Crafty startup the profile sets each existing Java server's CPU count to all
cores available to the process, uses a small 256 MB starting heap, and calculates
its maximum heap from the phone's measured memory. The **combined** heap budget is
the smaller of 70% of total RAM and total RAM minus 1536 MB.
That budget is divided across all configured Java servers and
rounded down to 64 MB increments. Native JVM memory uses additional space.
Current free RAM is reported separately. The ceiling does not reserve that much
physical memory at startup; close other apps before running a busy world and
watch for Android memory pressure as the heap grows.

The profile backs up the database before changing standard `java ... -jar ...`
commands. Custom shell/wrapper/argfile commands are rejected; tune those in Crafty
using `manual`. It also refuses to start if the calculated heap is below 512 MB
per server; close other apps, reduce the number of servers, or switch to manual.
Newly created servers are tuned on the next Crafty restart. Switching to `manual`
keeps the last commands; adjust RAM/CPU in Crafty to change them further.

CPU clocks, Android process CPU sets, and thermal throttling remain under Android
control. The installer does not overclock, disable thermal protection, or require
root. For sustained speed, allow background activity, turn off Android Battery
Saver yourself, keep the phone cool, and reduce Minecraft simulation/view distance.

- Host state/logs: `~/cellhasher-crafty/`; install status is `install.status`.
- Rotating supervisor logs: `~/cellhasher-crafty/logs/service/current` (five
  rotated files of approximately 1 MB each), plus `install.log` and `boot.log`.
- Dedicated guest name: `cellhasher-crafty`; unrelated distributions are preserved.
- Inside the guest: `/opt/crafty/app` (Crafty, accounts, servers, backups),
  `/opt/crafty/venv` (Python), `/opt/crafty/crafty.pid` (managed process).
- A separate Android launcher falls back to Crafty's real app storage directory
  if Android denies `psutil` access to `/proc/filesystems`. It preserves normal
  discovery when allowed and does not patch upstream source. Android/PRoot can
  restrict system-wide metrics; use server process memory and Minecraft TPS
  when assessing gameplay performance. Service logs use UTC.
- Initial password: `/opt/crafty/app/app/config/default-creds.txt` inside the guest.
- Rerunning stops the managed service gracefully and reinstalls dependencies,
  preserving worlds/accounts. The same port/choices should be supplied again;
  selected options replace the previous installer settings. Existing unrecognized
  application directories or different source revisions are rejected.
- No Firebase/Supabase/backend rule changes or database schema migrations are
  introduced by this installer. Crafty performs its own upstream migrations.

Stop Crafty before exporting a full backup of its dedicated distribution:

```sh
crafty-android stop
proot-distro backup --output "$HOME/crafty-backup.tar.gz" cellhasher-crafty
```

Copy the backup off the phone. Never uninstall Termux or remove the distribution
before preserving the worlds and database. Stopping may take longer than three
minutes for a large server: a timeout reports that shutdown is still pending
instead of force-killing a process while it saves.

## Development and verification

`crafty_android_installer.py` is the source of truth. Regenerate the checked-in
standalone shell file after edits, then run the standard-library test suite:

```sh
python crafty_android_installer.py --export-shell crafty_android_termux.sh
python -m unittest discover -s tests -v
bash -n crafty_android_termux.sh
```

Tests cover config preservation, source-default extraction, database policy and
backups, argument/ADB quoting, APK integrity checks, CLI behavior, and shell
syntax where Bash is available. These checks do not prove real Android runtime
compatibility. Hardware acceptance requires completing installation on a phone,
logging in, creating a server, joining it, stopping/restarting it, and rebooting
with Termux:Boot configured.

For an installed phone, `python tests/smoke_device.py --device YOUR_ADB_SERIAL`
checks the service, login page, API authentication, and measured hardware. It
trusts the certificate read from the phone, keeps credentials out of output, and
forwards the panel to this PC's localhost. Add `--adb PATH` if needed. Add
`--restart` only when it is appropriate to restart that phone's active servers.

Crafty source is pinned to commit
`fe65b372a4388552e9f4a1fe54251b2321f042fa` (reports 4.11.0). Future upgrades
must review dependencies, configuration defaults, and the server schema before
changing the pin. No upstream source patches or password defaults are embedded.

Primary references:

- [Crafty Linux installation](https://docs.craftycontrol.com/pages/getting-started/installation/linux/)
- [Crafty panel and initial credentials](https://docs.craftycontrol.com/pages/getting-started/access/)
- [Crafty upstream source](https://gitlab.com/crafty-controller/crafty-4)
- [PRoot-Distro installation, containers and limitations](https://github.com/termux/proot-distro)
- [Termux:Boot installation and activation](https://github.com/termux/termux-boot)
- [Termux services](https://github.com/termux/termux-services)
