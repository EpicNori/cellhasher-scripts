# Operations and performance

[Project overview](../README.md) · [Installation](INSTALLATION.md) · [Troubleshooting](TROUBLESHOOTING.md)

Run management commands in the Android Termux shell. A shell opened by
`crafty-android shell` is inside Ubuntu; use `exit` to return to Termux.

## First Minecraft server

1. Sign in to Crafty's HTTPS panel and change the initial admin password.
2. Create a Minecraft Java server using Crafty's creation flow, or import a
   copy of an existing Java server. Choose the Minecraft release and server
   software you intend to use. Preserve an off-device copy of existing worlds.
3. Choose an unused Minecraft port, commonly 25565/TCP. Stop the old server
   before reusing its port; avoid running two instances against the same world.
4. Inspect installed JVMs with `crafty-android shell`, `ls /usr/lib/jvm`, then
   `exit`. Set the required JVM's absolute `bin/java` path in Crafty's execution
   command if the default Java version does not suit the chosen release.
5. Configure RAM and world settings. Read the Minecraft EULA and accept it in
   the server setup if you agree. Start the server in Crafty.
6. Join from a compatible Minecraft Java client at `PHONE-IP:SERVER-PORT`.
   Verify world saving with a graceful stop and restart before relying on it.

The HTTPS panel port and Minecraft port serve different purposes. The installer
targets Java servers; native Bedrock binaries are outside its supported scope.
Use a trusted LAN or a separately configured VPN for access.

## Daily commands

| Termux command | Behavior |
| --- | --- |
| `crafty-android` | Show the management menu |
| `crafty-android start` | Start supervision as needed and wait for HTTPS readiness |
| `crafty-android stop` | Request graceful Crafty and Minecraft shutdown |
| `crafty-android restart` | Stop gracefully, then start and check readiness |
| `crafty-android status` | Report service state and local HTTPS availability |
| `crafty-android logs` | Follow the last 100 service log lines; Ctrl+C leaves the viewer |
| `crafty-android credentials` | Read the original admin credential file |
| `crafty-android shell` | Open Ubuntu as the non-root Crafty account |

Stopping Crafty can stop every Minecraft server it manages. Use Crafty's
individual server controls when you only want to stop one world. If a graceful
stop exceeds the command's 180-second wait, inspect the logs and allow saving
to finish; a timeout does not force-kill the server.

## Android boot startup

1. Install Termux:Boot from the same signing source as Termux and open its
   launcher once.
2. Allow background activity and notifications for Termux and Termux:Boot.
   Disable their Android battery optimization and enable any vendor-specific
   autostart permission your phone requires.
3. In Termux, run:

```sh
crafty-android boot on
crafty-android server-autostart all
crafty-android restart
```

Save active worlds before the restart. After rebooting at a convenient time,
unlock Android and verify panel access and Minecraft startup. The boot hook
waits 15 seconds, then starts the service. Its log is
`~/cellhasher-crafty/logs/boot.log`.

`crafty-android boot off` removes this project's hook without stopping the
current service. `crafty-android stop` stops the current service without removing
the boot hook. Termux and Android must remain able to run background processes;
force-stop, memory pressure, loss of power, or thermal shutdown can interrupt them.

## Minecraft autostart policy

| Policy command | On the next Crafty start |
| --- | --- |
| `crafty-android server-autostart all` | Enable Auto Start for every existing Java server |
| `crafty-android server-autostart none` | Disable Auto Start for every existing Java server |
| `crafty-android server-autostart keep` | Preserve per-server settings selected in Crafty |

These commands save a policy; they do not immediately start or stop worlds.
Newly created servers are covered at the next Crafty restart. Per-server crash
detection is a separate Crafty setting. Policy changes back up the database
before modifying rows while Crafty is stopped.

## Maximum-performance profile

```sh
crafty-android performance info
crafty-android performance max
crafty-android restart
```

At each startup, `max` tunes existing Java commands of the form
`java ... -jar ...` or an absolute path to `java`. It sets the JVM processor
count to the cores available to the process and the initial heap to 256 MB.
The combined maximum heap budget, in MB as computed from `/proc/meminfo`, is:

```text
budget = max(0, min(floor(total_ram_mb * 70 / 100), total_ram_mb - 1536))
per_server_heap = floor(budget / configured_java_server_count / 64) * 64
```

All configured Java servers share the budget, including servers with autostart
disabled. Each server needs at least 512 MB under this profile. Custom wrappers,
shell scripts, and Java argument files are rejected so their commands can be
configured manually. The database is backed up before command changes.

For the tested phone's 3570 MB usable RAM, the budget is 2034 MB: one Java
server gets a 1984 MB maximum heap, or two get 960 MB each. These are ceilings;
Java native memory and Android need additional RAM. Current free RAM is reported
separately and does not change the configured ceiling. Close other apps and
check Minecraft TPS, process memory, and temperature under actual gameplay.

Use `crafty-android performance manual` to stop automatic tuning on subsequent
starts. It preserves the last commands, so change heap sizes in Crafty yourself
if needed. Android still controls CPU clocks, CPU sets, and thermal throttling.

## Backups and recovery

Use Crafty's backup features for scheduled world backups. Copy important
backups off the phone. For a full guest snapshot, stop the service successfully
and then run in Termux:

```sh
crafty-android stop
backup="$HOME/crafty-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
proot-distro backup --output "$backup" cellhasher-crafty
tar -tzf "$backup" >/dev/null
printf 'Backup archive: %s\n' "$backup"
crafty-android start
```

If stopping or export fails, resolve it before proceeding. Reading the archive
checks its format, not whether recovery works. Retain the host settings too:

```sh
tar -czf "$HOME/crafty-host-settings-$(date +%Y%m%d-%H%M%S).tar.gz" -C "$HOME" cellhasher-crafty
```

Keep these archives private: controller data includes credentials and account
information. The guest archive contains Ubuntu and `/opt/crafty`; the host
archive holds installer settings, payloads, and logs. Host runit files live
separately under `$PREFIX/var/service/crafty-android`.

Before restoring, read `proot-distro restore --help` for the installed version
and the [upstream backup/restore reference](https://github.com/termux/proot-distro#commands-reference).
Validate the archive in a separate recovery environment first. The runtime
expects the active guest name `cellhasher-crafty`; a differently named recovery
guest is not automatically managed by `crafty-android`. Preserve the existing
guest and off-device backups until recovered accounts and worlds are verified.

Reinstalling Termux or removing its app data deletes its private storage.
Reinstalling this script is not a backup or a restore procedure.

## Reinstalling and upgrading

Rerun the installer with the same port and explicitly chosen settings to repair
the managed installation. It stops the service, preserves controller data, and
reinstalls dependencies. It may take the panel and managed worlds offline.

Crafty's source revision is pinned. A different existing revision is rejected;
an installer rerun does not silently upgrade or downgrade Crafty. Back up first
and follow the [developer maintenance procedure](DEVELOPMENT.md#upstream-upgrades)
when changing that pin.
