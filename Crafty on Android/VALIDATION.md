# Validation — 2026-10-14

## Automated local checks

- 28 standard-library regression tests passed on Windows with Python 3.13.
- Bash parsed the standalone installer and every embedded shell payload.
- The generated standalone shell file matches the Python source exactly.
- Coverage includes config preservation, database backups, Java-only autostart
  changes, RAM budgeting, command preservation, Android disk-discovery fallback,
  ADB argument quoting, APK SHA-256 rejection, CLI failures, and boot-hook isolation.

## Real Android device

Tested on a Samsung Galaxy A51, Android 13, ARM64, 8 available CPU cores, and
3570 MB of kernel-reported usable RAM. Termux provided PRoot-Distro 5.10.0.
The dedicated guest is Ubuntu 24.04 with Python 3.12, Java 21 and Java 25.

Verified:

- Full dependency installation on the phone, including native Python extensions.
- `pip check` reports no broken requirements.
- Crafty runs as the non-root `crafty` guest user.
- Supervised service startup and loopback HTTPS readiness.
- Login page through ADB forwarding to the PC's localhost.
- TLS verification against the certificate read directly from the phone.
- Generated admin credential login and authenticated server API access.
- Authenticated host statistics API access.
- Unauthenticated server API access is denied.
- Graceful service stop/restart and panel recovery.
- Installer rerun preserves the initialized controller and generated credentials.
- Maximum-performance profile selected; automatic Android boot left disabled
  during testing.

The final hardware probe reported 8 cores and a 2034 MB combined Java heap
budget. A single standard Java server receives a 1984 MB maximum heap after
64 MB rounding; its initial heap stays at 256 MB. Actual gameplay memory use
and performance still need testing with the intended world.

The device test found and fixed a Bash pipe-handling error in the PRoot feature
probe and Android's restriction on `/proc/filesystems`. The compatibility
launcher falls back to monitoring Crafty's real app storage without modifying
Crafty's source or inventing disk usage values.

## Scope and remaining acceptance steps

No Minecraft world was created, imported, joined, or stress-tested. Complete the
server creation/import and Minecraft EULA flow in Crafty's panel. Test gameplay,
world saving, RAM pressure, and sustained temperature with the intended server.

Termux:Boot receiver activation and a full Android reboot were not tested.
Install the matching add-on, open it once, enable the boot hook, then verify
startup after unlocking the phone. Android can still terminate background apps.

## Focused security checks

Reviewed remote ADB quoting, verified HTTPS downloads, official APK source and
digest enforcement, non-root execution, private file permissions, parameterized
database updates, and backups before changes. Credentials and tokens are not
embedded in the scripts or printed by the smoke test. Only the loopback HTTPS
readiness probe accepts a self-signed certificate without verification.

No external backend permission rules are changed. Crafty's upstream application
and dependency security remain separate maintenance responsibilities.
