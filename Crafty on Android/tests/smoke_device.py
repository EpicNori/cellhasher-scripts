#!/usr/bin/env python3
"""Explicit, optional real-device smoke test. Never prints passwords/tokens.

Requires an already installed Crafty instance and authorized ADB. --restart
gracefully restarts the actual service, including any Minecraft servers.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import ssl
import subprocess
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer", ROOT / "crafty_android_installer.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--device", required=True)
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()

    def termux(*command, timeout=60):
        return installer.adb_shell(
            args.adb, args.device, "run-as", "com.termux", "env",
            f"HOME={installer.TERMUX_HOME}", f"PREFIX={installer.TERMUX_PREFIX}",
            f"PATH={installer.TERMUX_PREFIX}/bin:/system/bin", *command,
            capture_output=True, text=True, timeout=timeout,
        ).stdout

    def guest(*command):
        return termux("proot-distro", "login", "cellhasher-crafty", "--user", "crafty", "--", *command)

    status = termux(installer.TERMUX_PREFIX + "/bin/crafty-android", "status")
    if "HTTPS panel healthy" not in status:
        raise RuntimeError("Service/panel is not ready")
    print("PASS: supervised service and phone-local HTTPS probe")
    subprocess.run([args.adb, "-s", args.device, "forward", f"tcp:{args.port}", f"tcp:{args.port}"], check=True, capture_output=True)
    cert = guest("cat", "/opt/crafty/app/app/config/web/certs/commander.cert.pem")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False  # ADB loopback name can differ from the cert's DNS names.
    context.load_verify_locations(cadata=cert)  # Trust only the certificate read from this phone.
    base = f"https://127.0.0.1:{args.port}"
    # Ignore proxy environment variables for the ADB loopback connection.
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))

    def request(path, *, payload=None, token=None):
        headers = {}
        if token:
            headers["Authorization"] = "Bearer " + token
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, headers=headers,
                                     data=None if payload is None else json.dumps(payload).encode())
        with client.open(req, timeout=45) as response:
            return response.read()

    if b"crafty" not in request("/login").lower():
        raise RuntimeError("Login page is missing Crafty content")
    print("PASS: login page over ADB-forwarded localhost with phone certificate verification")
    try:
        request("/api/v2/servers")
    except urllib.error.HTTPError as error:
        if error.code not in (400, 401, 403):
            raise
    else:
        raise RuntimeError("Server API allowed unauthenticated access")
    print("PASS: unauthenticated server API access denied")
    credentials = json.loads(guest("cat", "/opt/crafty/app/app/config/default-creds.txt"))
    login = json.loads(request("/api/v2/auth/login", payload={
        "username": credentials["username"], "password": credentials["password"],
    }))
    if login.get("status") != "ok":
        raise RuntimeError("Initial credential login failed; if the password changed, test login manually")
    token = login["data"]["token"]
    servers = json.loads(request("/api/v2/servers", token=token))
    if servers.get("status") != "ok":
        raise RuntimeError("Authenticated API request failed")
    print("PASS: generated admin credentials and authenticated server API")
    stats = json.loads(request("/api/v2/crafty/stats", token=token))
    if stats.get("status") != "ok":
        raise RuntimeError("Host statistics API failed")
    print("PASS: authenticated host statistics API")
    info = json.loads(guest("python3", "/opt/crafty/config-helper.py", "hardware"))
    print("Hardware:", json.dumps(info))
    if args.restart:
        termux(installer.TERMUX_PREFIX + "/bin/crafty-android", "restart", timeout=600)
        after = termux(installer.TERMUX_PREFIX + "/bin/crafty-android", "status")
        if "HTTPS panel healthy" not in after:
            raise RuntimeError("Panel failed to recover after restart")
        print("PASS: graceful service restart and panel recovery")
    print(f"Panel available on this PC: {base}")


if __name__ == "__main__":
    main()
