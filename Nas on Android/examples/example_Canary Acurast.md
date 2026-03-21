#!/usr/bin/env python3
import os
import sys
import subprocess
import tempfile
import urllib.request
import json
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed

# Windows console encoding fix
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Windows subprocess flags
CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0

# Environment variables
ADB = os.environ.get("adb_path", "adb")
devices = os.environ.get("devices", "").split()

# GitHub API - use releases list to search through multiple releases
GITHUB_RELEASES_URL = "https://api.github.com/repos/Acurast/acurast-processor-update/releases"

# Global SSL context - create once, use everywhere
SSL_CONTEXT = None

def get_ssl_context():
    """Get or create SSL context that bypasses certificate verification"""
    global SSL_CONTEXT
    if SSL_CONTEXT is None:
        try:
            SSL_CONTEXT = ssl._create_unverified_context()
            print("[*] SSL: Using unverified context")
        except AttributeError:
            SSL_CONTEXT = ssl.create_default_context()
            print("[*] SSL: Using default context")
    return SSL_CONTEXT

def fetch_url(url, timeout=60):
    """Fetch URL with proper SSL context"""
    req = urllib.request.Request(url, headers={"User-Agent": "Cellhasher-Acurast-Updater/1.0"})
    ctx = get_ssl_context()
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)

def get_latest_acurast_lite_canary_apk():
    """Find the latest processor-lite-*-canary.apk from releases"""
    print("[*] Fetching Acurast releases to find Lite Canary APK...")

    with fetch_url(GITHUB_RELEASES_URL, timeout=30) as resp:
        releases = json.loads(resp.read().decode())

    print(f"[*] Searching through {len(releases)} releases...")

    for release in releases:
        tag_name = release.get('tag_name', 'unknown')
        
        for asset in release.get("assets", []):
            name = asset["name"].lower()
            # Look specifically for processor-lite-*-canary.apk
            if (
                name.startswith("processor-lite-")
                and name.endswith("-canary.apk")
            ):
                print(f"[+] Found Lite Canary in release: {tag_name}")
                print(f"[+] Selected APK: {asset['name']}")
                return asset["browser_download_url"], asset["name"], tag_name

    raise RuntimeError("processor-lite-*-canary.apk not found in any recent releases")

def download_apk(url, name):
    temp_path = os.path.join(tempfile.gettempdir(), name)
    print(f"[*] Downloading {name}")
    print(f"[*] Saving to {temp_path}")

    with fetch_url(url, timeout=120) as resp, open(temp_path, "wb") as f:
        total = 0
        while True:
            chunk = resp.read(8192)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
            if total % (1024 * 1024) == 0:
                print(f"[*] Downloaded {total / (1024*1024):.0f} MB...")

    size_mb = os.path.getsize(temp_path) / (1024 * 1024)
    print(f"[+] Download complete ({size_mb:.2f} MB)")
    return temp_path

def install_apk(device, apk_path):
    try:
        print(f"[{device}] Installing Acurast Lite Canary...")
        
        cmd = [ADB, "-s", device, "install", "-r", apk_path]
        
        kwargs = {"capture_output": True, "text": True, "timeout": 120}
        if sys.platform == 'win32':
            kwargs["creationflags"] = CREATE_NO_WINDOW
        
        result = subprocess.run(cmd, **kwargs)

        output = result.stdout + result.stderr
        if "Success" in output:
            print(f"[{device}] SUCCESS - Installed successfully")
            return f"[{device}] SUCCESS"
        elif result.returncode == 0 and "Failure" not in output:
            print(f"[{device}] SUCCESS - Installed (code 0)")
            return f"[{device}] SUCCESS"
        else:
            print(f"[{device}] FAILED: {output.strip()}")
            return f"[{device}] FAILED: {output.strip()}"

    except subprocess.TimeoutExpired:
        return f"[{device}] ERROR: Timeout"
    except FileNotFoundError:
        return f"[{device}] ERROR: ADB not found"
    except Exception as e:
        return f"[{device}] ERROR: {e}"

def main():
    print("=" * 60)
    print("     Acurast Lite CANARY Installer")
    print("=" * 60)

    if not devices:
        print("[!] No devices selected")
        return

    print(f"[*] Devices: {len(devices)}")
    for i, d in enumerate(devices, 1):
        print(f"  {i}. {d}")

    try:
        apk_url, apk_name, release_tag = get_latest_acurast_lite_canary_apk()
        print(f"[*] Using release: {release_tag}")
        apk_path = download_apk(apk_url, apk_name)

        print("\n[*] Installing on devices...\n")

        with ThreadPoolExecutor(max_workers=min(len(devices), 4)) as pool:
            futures = [pool.submit(install_apk, d, apk_path) for d in devices]
            for f in as_completed(futures):
                print(f.result())

        print("\n[*] Cleaning up...")
        if os.path.exists(apk_path):
            os.remove(apk_path)

        print("\n[+] Acurast Lite CANARY install complete!")

    except Exception as e:
        print(f"[!] Script failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()