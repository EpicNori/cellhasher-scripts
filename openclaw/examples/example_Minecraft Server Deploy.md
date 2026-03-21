#!/usr/bin/env python3
"""
PaperMC Minecraft Server - One-Click Deployment Script
Automatically installs Termux (if needed) and deploys PaperMC (latest) server on Android devices
Author: Cellhasher Team
Version: 1.1.0
"""

import os
import sys
import time
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

# Script metadata for Cellhasher integration
SCRIPT_META = {
    "id": "minecraft-papermc-server-v1",
    "name": "Minecraft PaperMC Server",
    "description": "One-click PaperMC Minecraft server deployment. Automatically installs Termux if needed, configures Java 21, downloads the latest Paper version, and starts the server.",
    "category": "Gaming",
    "type": "python",
    "version": "1.1.0",
    "author": "Cellhasher Team",
    "difficulty": "Advanced",
    "estimatedTime": "5-10 min",
    "tags": ["minecraft", "server", "papermc", "gaming", "termux"],
    "effects": {
        "power": {"reboot": False, "shutdown": False},
        "security": {"modifiesLockScreen": False}
    },
    "estimatedDurationSec": 600,
    "downloads": 0,
    "rating": 5.0,
    "lastUpdated": "today"
}

# Get environment variables from Cellhasher
ADB = os.environ.get("adb_path", "adb")
devices = os.environ.get("devices", "").split()

# GitHub API endpoint for Termux app releases
GITHUB_API_URL = "https://api.github.com/repos/termux/termux-app/releases/latest"

# PaperMC installation bash script for Termux
# This script dynamically fetches the latest Paper version using the PaperMC API
PAPERMC_INSTALL_SCRIPT = r'''#!/data/data/com.termux/files/usr/bin/bash
set -e

echo "=============================================="
echo "   PaperMC Minecraft Server Installer"
echo "   Dynamic Latest Version | Java 21"
echo "=============================================="
echo ""

# Step 1: Update system
echo "[1/7] Updating Termux packages..."
yes '' | pkg upgrade -y 2>/dev/null || true
pkg update -y 2>/dev/null || true
echo "[OK] System updated!"
echo ""

# Step 2: Install dependencies
echo "[2/7] Installing dependencies (openjdk-21, curl, jq)..."
pkg install -y openjdk-21 curl jq 2>/dev/null || {
    echo "[!] First attempt failed, retrying..."
    pkg install -y openjdk-21 curl jq
}
echo "[OK] Dependencies installed!"
echo ""

# Enforce Java 21 usage (important for MC 1.21+)
export JAVA_HOME=$PREFIX/lib/jvm/java-21-openjdk
export PATH=$JAVA_HOME/bin:$PATH

echo "[OK] Java enforced:"
java -version
echo ""

# Step 3: Create server directory
echo "[3/7] Creating Minecraft server directory..."
mkdir -p ~/mc
cd ~/mc
echo "[OK] Server directory ready: ~/mc"
echo ""

# Step 4: Download latest PaperMC server
echo "[4/7] Fetching latest PaperMC version..."

LATEST_VERSION=$(curl -s https://api.papermc.io/v2/projects/paper | jq -r '.versions[-1]')
LATEST_BUILD=$(curl -s https://api.papermc.io/v2/projects/paper/versions/$LATEST_VERSION | jq -r '.builds[-1]')

PAPER_URL="https://api.papermc.io/v2/projects/paper/versions/$LATEST_VERSION/builds/$LATEST_BUILD/downloads/paper-$LATEST_VERSION-$LATEST_BUILD.jar"

echo "[*] Latest Paper version: $LATEST_VERSION (build $LATEST_BUILD)"

rm -f paper.jar
curl -L -o paper.jar "$PAPER_URL" --progress-bar

if [ ! -f paper.jar ]; then
    echo "[ERROR] Failed to download PaperMC!"
    exit 1
fi

FILE_SIZE=$(du -h paper.jar | cut -f1)
echo "[OK] PaperMC downloaded successfully ($FILE_SIZE)"
echo ""

# Step 5: Initial server run (generates EULA)
echo "[5/7] Running initial server startup to generate EULA..."
echo "[*] This will fail with EULA error - that's expected!"
java -Xms512M -Xmx1024M -jar paper.jar nogui 2>&1 || true
echo "[OK] Initial run complete!"
echo ""

# Step 6: Accept EULA automatically
echo "[6/7] Accepting Minecraft EULA..."
if [ -f "eula.txt" ]; then
    sed -i 's/eula=false/eula=true/g' eula.txt
    echo "[OK] EULA accepted!"
else
    echo "eula=true" > eula.txt
    echo "[OK] EULA file created and accepted!"
fi
echo ""

# Step 7: Configure server.properties for mobile
echo "[7/7] Configuring server for mobile optimization..."
if [ -f "server.properties" ]; then
    # Optimize for mobile devices
    sed -i 's/view-distance=10/view-distance=6/g' server.properties 2>/dev/null || true
    sed -i 's/simulation-distance=10/simulation-distance=4/g' server.properties 2>/dev/null || true
    sed -i 's/max-players=20/max-players=5/g' server.properties 2>/dev/null || true
    echo "[OK] Server configured for mobile!"
else
    echo "[*] server.properties will be created on first run"
fi
echo ""

echo "=============================================="
echo "   Installation Complete!"
echo "=============================================="
echo ""
echo "To start your Minecraft server, run:"
echo "  cd ~/mc && java -Xms512M -Xmx1024M -jar paper.jar nogui"
echo ""
echo "Server will be available on port 25565"
echo "Connect using your device's IP address"
echo ""

# Final server start
echo "[*] Starting Minecraft server now..."
echo "=============================================="
java -Xms512M -Xmx1024M -jar paper.jar nogui
'''


def setup_ssl_context():
    """Setup SSL context to handle certificate verification issues"""
    try:
        if hasattr(ssl, '_create_unverified_context'):
            ssl_context = ssl._create_unverified_context()
            return ssl_context
        else:
            ssl_context = ssl.create_default_context()
            return ssl_context
    except Exception as e:
        print(f"[!] SSL setup warning: {e}")
        return None


def get_latest_termux_apk():
    """Fetch the latest Termux arm64-v8a APK download URL from GitHub releases"""
    try:
        print("[*] Fetching latest Termux release from GitHub...")
        ssl_context = setup_ssl_context()
        req = urllib.request.Request(
            GITHUB_API_URL, 
            headers={'User-Agent': 'Cellhasher-Minecraft-Deployer/1.0'}
        )
        
        if ssl_context:
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
                release_data = json.loads(response.read().decode())
        else:
            with urllib.request.urlopen(req, timeout=30) as response:
                release_data = json.loads(response.read().decode())

        print(f"[OK] Fetched release: {release_data.get('tag_name', 'unknown')}")

        # Find the arm64-v8a APK
        for asset in release_data.get("assets", []):
            if "arm64-v8a" in asset["name"].lower() and asset["name"].endswith(".apk"):
                apk_url = asset["browser_download_url"]
                apk_name = asset["name"]
                print(f"[OK] Found APK: {apk_name}")
                return apk_url, apk_name

        raise Exception("Could not find arm64-v8a APK in latest release")
    except Exception as e:
        print(f"[ERROR] Error fetching release info: {e}")
        raise


def download_apk(apk_url, apk_name):
    """Download the APK to a temporary location"""
    try:
        temp_dir = tempfile.gettempdir()
        local_apk_path = os.path.join(temp_dir, apk_name)
        
        print(f"[*] Downloading {apk_name}...")
        
        req = urllib.request.Request(
            apk_url, 
            headers={'User-Agent': 'Cellhasher-Minecraft-Deployer/1.0'}
        )
        ssl_context = setup_ssl_context()
        
        if ssl_context:
            with urllib.request.urlopen(req, timeout=120, context=ssl_context) as response:
                with open(local_apk_path, 'wb') as f:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
        else:
            with urllib.request.urlopen(req, timeout=120) as response:
                with open(local_apk_path, 'wb') as f:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
        
        file_size = os.path.getsize(local_apk_path)
        print(f"[OK] Downloaded! Size: {file_size / (1024 * 1024):.2f} MB")
        return local_apk_path
    except Exception as e:
        print(f"[ERROR] Error downloading APK: {e}")
        raise


def check_termux_installed(device_id):
    """Check if Termux is installed on the device"""
    try:
        result = subprocess.run(
            f'"{ADB}" -s {device_id} shell pm list packages com.termux',
            shell=True,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        return "com.termux" in result.stdout
    except Exception as e:
        print(f"[{device_id}] Error checking Termux: {e}")
        return False


def install_termux_on_device(device_id, apk_path):
    """Install Termux APK on a device"""
    try:
        print(f"[{device_id}] Installing Termux...")
        result = subprocess.run(
            f'"{ADB}" -s {device_id} install -r "{apk_path}"',
            shell=True,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        if result.returncode == 0 or "Success" in result.stdout:
            print(f"[{device_id}] [OK] Termux installed successfully!")
            return True
        else:
            print(f"[{device_id}] [ERROR] Termux installation failed: {result.stderr or result.stdout}")
            return False
    except Exception as e:
        print(f"[{device_id}] [ERROR] Error installing Termux: {e}")
        return False


def grant_termux_permissions(device_id):
    """Grant necessary permissions to Termux"""
    permissions = [
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.INTERNET",
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.WAKE_LOCK",
        "android.permission.FOREGROUND_SERVICE",
    ]
    
    for perm in permissions:
        try:
            subprocess.run(
                f'"{ADB}" -s {device_id} shell pm grant com.termux {perm}',
                shell=True,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
        except Exception:
            pass  # Some permissions may not be grantable, continue anyway


def deploy_papermc_server(device_id, script_path):
    """Deploy and run PaperMC server installation on a device"""
    try:
        print(f"[{device_id}] Starting PaperMC deployment...")
        
        # Step 1: Check if Termux is installed
        print(f"[{device_id}] Checking Termux installation...")
        termux_installed = check_termux_installed(device_id)
        
        if not termux_installed:
            print(f"[{device_id}] Termux not found, installation required...")
            return "NEEDS_TERMUX"
        
        print(f"[{device_id}] [OK] Termux is installed!")
        
        # Step 2: Force stop Termux if running
        subprocess.run(
            f'"{ADB}" -s {device_id} shell am force-stop com.termux',
            shell=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        time.sleep(1)
        
        # Step 3: Push the installation script to device
        device_temp_path = "/data/local/tmp/papermc_install.sh"
        print(f"[{device_id}] Pushing installation script...")
        
        result = subprocess.run(
            f'"{ADB}" -s {device_id} push "{script_path}" "{device_temp_path}"',
            shell=True,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        if result.returncode != 0:
            print(f"[{device_id}] [ERROR] Failed to push script: {result.stderr}")
            return f"[{device_id}] Error: Failed to push script"
        
        # Step 4: Make script executable
        print(f"[{device_id}] Setting script permissions...")
        subprocess.run(
            f'"{ADB}" -s {device_id} shell chmod 755 {device_temp_path}',
            shell=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        # Step 5: Grant Termux permissions
        print(f"[{device_id}] Granting Termux permissions...")
        grant_termux_permissions(device_id)
        
        # Step 6: Launch Termux and wait for initialization
        print(f"[{device_id}] Launching Termux...")
        subprocess.run(
            f'"{ADB}" -s {device_id} shell am start -n com.termux/com.termux.app.TermuxActivity',
            shell=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        # Wait for Termux to fully initialize (first launch takes longer)
        print(f"[{device_id}] Waiting for Termux initialization (15 seconds)...")
        time.sleep(15)
        
        # Step 7: Type and execute the installation command
        # Using %s for spaces in adb shell input text
        adb_typed_cmd = "bash%s/data/local/tmp/papermc_install.sh"
        print(f"[{device_id}] Sending installation command...")
        
        subprocess.run(
            f'"{ADB}" -s {device_id} shell input text "{adb_typed_cmd}"',
            shell=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        time.sleep(0.5)
        
        # Press Enter to execute
        subprocess.run(
            f'"{ADB}" -s {device_id} shell input keyevent 66',
            shell=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        print(f"[{device_id}] [OK] PaperMC installation started!")
        print(f"[{device_id}] Server will be available on port 25565 once ready")
        return f"[{device_id}] Success - Installation started"
        
    except Exception as e:
        print(f"[{device_id}] [ERROR] {e}")
        return f"[{device_id}] Error: {e}"


def main():
    """Main execution function"""
    print("=" * 60)
    print("   Minecraft PaperMC Server - One-Click Deployment")
    print("   Dynamic Latest Version | Java 21 | ARM64")
    print("=" * 60)
    print()
    
    if not devices:
        print("[ERROR] No devices found in environment variable 'devices'")
        print("[!] Please select devices in Cellhasher before running this script")
        return
    
    print(f"[*] Target devices: {len(devices)}")
    for idx, device in enumerate(devices, 1):
        print(f"    {idx}. {device}")
    print()
    
    # Create temporary script file
    print("[*] Creating installation script...")
    with tempfile.NamedTemporaryFile(
        mode='w', 
        encoding='utf-8', 
        newline='\n', 
        delete=False, 
        suffix='.sh'
    ) as f:
        f.write(PAPERMC_INSTALL_SCRIPT)
        local_script_path = f.name
    print(f"[OK] Script saved to: {local_script_path}")
    print()
    
    # Phase 1: Check which devices need Termux installed
    print("=" * 60)
    print("[Phase 1] Checking Termux installation status...")
    print("=" * 60)
    
    devices_need_termux = []
    devices_ready = []
    
    for device_id in devices:
        if check_termux_installed(device_id):
            print(f"[{device_id}] [OK] Termux installed")
            devices_ready.append(device_id)
        else:
            print(f"[{device_id}] [!] Termux NOT installed")
            devices_need_termux.append(device_id)
    
    print()
    
    # Phase 2: Install Termux on devices that need it
    if devices_need_termux:
        print("=" * 60)
        print(f"[Phase 2] Installing Termux on {len(devices_need_termux)} device(s)...")
        print("=" * 60)
        
        try:
            # Download Termux APK once
            apk_url, apk_name = get_latest_termux_apk()
            apk_path = download_apk(apk_url, apk_name)
            
            # Install on all devices that need it in parallel
            max_workers = max(1, len(devices_need_termux))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_device = {
                    executor.submit(install_termux_on_device, device_id, apk_path): device_id
                    for device_id in devices_need_termux
                }
                
                for future in as_completed(future_to_device):
                    device_id = future_to_device[future]
                    try:
                        success = future.result()
                        if success:
                            devices_ready.append(device_id)
                    except Exception as exc:
                        print(f"[{device_id}] Installation exception: {exc}")
            
            # Cleanup APK
            if os.path.exists(apk_path):
                os.unlink(apk_path)
                print(f"[OK] Cleaned up temporary APK")
            
            # Wait for Termux to be ready after installation
            print("[*] Waiting 5 seconds for Termux installations to settle...")
            time.sleep(5)
            
        except Exception as e:
            print(f"[ERROR] Failed to download/install Termux: {e}")
            print("[!] Continuing with devices that already have Termux...")
        
        print()
    else:
        print("[OK] All devices already have Termux installed!")
        print()
    
    # Phase 3: Deploy PaperMC server
    if not devices_ready:
        print("[ERROR] No devices available for PaperMC deployment!")
        os.unlink(local_script_path)
        return
    
    print("=" * 60)
    print(f"[Phase 3] Deploying PaperMC server on {len(devices_ready)} device(s)...")
    print("=" * 60)
    print()
    
    max_workers = max(1, len(devices_ready))
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_device = {
            executor.submit(deploy_papermc_server, device_id, local_script_path): device_id
            for device_id in devices_ready
        }
        
        for future in as_completed(future_to_device):
            device_id = future_to_device[future]
            try:
                result = future.result()
                results.append(result)
                print(result)
            except Exception as exc:
                print(f"[{device_id}] Generated an exception: {exc}")
    
    # Cleanup
    print()
    print("[*] Cleaning up temporary files...")
    if os.path.exists(local_script_path):
        os.unlink(local_script_path)
        print("[OK] Removed temporary script file")
    
    # Summary
    print()
    print("=" * 60)
    print("   Deployment Summary")
    print("=" * 60)
    successful = sum(1 for r in results if "Success" in r)
    print(f"[*] Devices processed: {len(devices_ready)}")
    print(f"[*] Successful deployments: {successful}")
    print()
    print("[INFO] The Minecraft server installation is now running on each device.")
    print("[INFO] Installation may take 5-10 minutes to complete.")
    print("[INFO] Once ready, connect to: <device-ip>:25565")
    print()
    print("[TIP] To check server status, open Termux on the device")
    print("[TIP] To restart server: cd ~/mc && java -Xms512M -Xmx1024M -jar paper.jar nogui")
    print("=" * 60)


if __name__ == "__main__":
    main()