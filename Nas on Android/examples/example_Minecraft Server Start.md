#!/usr/bin/env python3
"""
Minecraft PaperMC Server - Start Script
Pushes a start script to Termux with RAM selection and IP display
Author: Cellhasher Team
Version: 2.0.0
"""

import os
import sys
import time
import subprocess
import tempfile
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
    "id": "minecraft-start-server-v2",
    "name": "Minecraft Server - Start",
    "description": "Starts the PaperMC Minecraft server with RAM selection. Shows device IP and lets you choose memory allocation.",
    "category": "Gaming",
    "type": "python",
    "version": "2.0.0",
    "author": "Cellhasher Team",
    "difficulty": "Easy",
    "estimatedTime": "30 sec",
    "tags": ["minecraft", "server", "papermc", "gaming", "termux", "start"],
    "effects": {
        "power": {"reboot": False, "shutdown": False},
        "security": {"modifiesLockScreen": False}
    },
    "estimatedDurationSec": 30,
    "downloads": 0,
    "rating": 5.0,
    "lastUpdated": "today"
}

# Get environment variables from Cellhasher
ADB = os.environ.get("adb_path", "adb")
devices = os.environ.get("devices", "").split()

# Bash script that runs inside Termux
# Shows IP, asks for RAM, starts server
TERMUX_START_SCRIPT = r'''#!/data/data/com.termux/files/usr/bin/bash

# Colors for pretty output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

clear

echo ""
echo -e "${CYAN}ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ${NC}"
echo -e "${CYAN}â${WHITE}        MINECRAFT PAPERMC SERVER - START MENU             ${CYAN}â${NC}"
echo -e "${CYAN}ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ${NC}"
echo ""

# Get device IP address
DEVICE_IP=$(ip addr show wlan0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)
if [ -z "$DEVICE_IP" ]; then
    DEVICE_IP=$(ip route 2>/dev/null | grep 'src' | awk '{print $NF}' | head -1)
fi
if [ -z "$DEVICE_IP" ]; then
    DEVICE_IP="Unknown"
fi

# Display connection info
echo -e "${GREEN}ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ${NC}"
echo -e "${GREEN}â${WHITE}              SERVER CONNECTION DETAILS                    ${GREEN}â${NC}"
echo -e "${GREEN}â âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ£${NC}"
echo -e "${GREEN}â${NC}  IP Address:  ${YELLOW}${DEVICE_IP}${NC}"
echo -e "${GREEN}â${NC}  Port:        ${YELLOW}25565${NC}"
echo -e "${GREEN}â${NC}  Connect to:  ${CYAN}${DEVICE_IP}:25565${NC}"
echo -e "${GREEN}ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ${NC}"
echo ""

# Check if server directory exists
if [ ! -d ~/mc ]; then
    echo -e "${RED}[ERROR] Server directory ~/mc not found!${NC}"
    echo -e "${YELLOW}Please run the PaperMC installer first.${NC}"
    exit 1
fi

if [ ! -f ~/mc/paper.jar ]; then
    echo -e "${RED}[ERROR] paper.jar not found in ~/mc!${NC}"
    echo -e "${YELLOW}Please run the PaperMC installer first.${NC}"
    exit 1
fi

# RAM Selection
echo -e "${BLUE}ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ${NC}"
echo -e "${BLUE}â${WHITE}                  RAM ALLOCATION                           ${BLUE}â${NC}"
echo -e "${BLUE}â âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ£${NC}"
echo -e "${BLUE}â${NC}  How much RAM to allocate to the server?                   ${BLUE}â${NC}"
echo -e "${BLUE}â${NC}                                                            ${BLUE}â${NC}"
echo -e "${BLUE}â${NC}  Enter a number in GB (e.g., 1, 2, 3)                      ${BLUE}â${NC}"
echo -e "${BLUE}â${NC}  Or press ${GREEN}ENTER${NC} for default (1 GB)                        ${BLUE}â${NC}"
echo -e "${BLUE}ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ${NC}"
echo ""
echo -ne "${WHITE}RAM (GB) [1]: ${NC}"
read -r RAM_INPUT

# Default to 1 GB if empty
if [ -z "$RAM_INPUT" ]; then
    RAM_GB=1
else
    # Validate input is a number
    if [[ "$RAM_INPUT" =~ ^[0-9]+$ ]]; then
        RAM_GB=$RAM_INPUT
    else
        echo -e "${YELLOW}Invalid input, using default (1 GB)${NC}"
        RAM_GB=1
    fi
fi

# Convert GB to MB
RAM_MB=$((RAM_GB * 1024))

# Calculate min RAM (half of max, minimum 512MB)
MIN_RAM_MB=$((RAM_MB / 2))
if [ $MIN_RAM_MB -lt 512 ]; then
    MIN_RAM_MB=512
fi

echo ""
echo -e "${GREEN}ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ${NC}"
echo -e "${GREEN}â${WHITE}                 STARTING SERVER                           ${GREEN}â${NC}"
echo -e "${GREEN}â âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ£${NC}"
echo -e "${GREEN}â${NC}  Memory:      ${YELLOW}-Xms${MIN_RAM_MB}M -Xmx${RAM_MB}M${NC}"
echo -e "${GREEN}â${NC}  Directory:   ${YELLOW}~/mc${NC}"
echo -e "${GREEN}â${NC}  Server:      ${YELLOW}paper.jar${NC}"
echo -e "${GREEN}ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ${NC}"
echo ""
echo -e "${CYAN}Starting Minecraft server in 3 seconds...${NC}"
sleep 1
echo -e "${CYAN}Starting in 2...${NC}"
sleep 1
echo -e "${CYAN}Starting in 1...${NC}"
sleep 1
echo ""
echo -e "${GREEN}[SERVER] Launching PaperMC...${NC}"
echo "============================================================"
echo ""

# Change to server directory and start
cd ~/mc
java -Xms${MIN_RAM_MB}M -Xmx${RAM_MB}M -jar paper.jar nogui
'''


def start_minecraft_server(device_id, script_path):
    """Start the Minecraft server on a device"""
    try:
        print(f"[{device_id}] Preparing to start Minecraft server...")
        
        # Step 1: Force stop Termux if running
        print(f"[{device_id}] Stopping any existing Termux session...")
        subprocess.run(
            [ADB, "-s", device_id, "shell", "am", "force-stop", "com.termux"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        time.sleep(1)
        
        # Step 2: Push the start script to device
        device_temp_path = "/data/local/tmp/mc_start.sh"
        print(f"[{device_id}] Pushing start script...")
        
        result = subprocess.run(
            [ADB, "-s", device_id, "push", script_path, device_temp_path],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        if result.returncode != 0:
            print(f"[{device_id}] [ERROR] Failed to push script: {result.stderr}")
            return f"[{device_id}] Error: Failed to push script"
        
        # Step 3: Make script executable
        print(f"[{device_id}] Setting script permissions...")
        subprocess.run(
            [ADB, "-s", device_id, "shell", "chmod", "755", device_temp_path],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        # Step 4: Launch Termux
        print(f"[{device_id}] Launching Termux...")
        subprocess.run(
            [ADB, "-s", device_id, "shell", "am", "start", "-n", "com.termux/com.termux.app.TermuxActivity"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        # Step 5: Wait for Termux to initialize
        print(f"[{device_id}] Waiting for Termux to initialize (10 seconds)...")
        time.sleep(10)
        
        # Step 6: Type the command to run our script
        run_cmd = "bash%s/data/local/tmp/mc_start.sh"
        print(f"[{device_id}] Running start script...")
        
        subprocess.run(
            [ADB, "-s", device_id, "shell", "input", "text", run_cmd],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        time.sleep(0.3)
        
        # Step 7: Press Enter to execute
        subprocess.run(
            [ADB, "-s", device_id, "shell", "input", "keyevent", "66"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        print(f"[{device_id}] [OK] Start script launched!")
        print(f"[{device_id}] The device will show connection info and ask for RAM allocation.")
        print(f"[{device_id}] Press ENTER on device for default (1GB) or type a number (e.g., 2 for 2GB)")
        
        return f"[{device_id}] Success - Start menu launched on device"
        
    except Exception as e:
        print(f"[{device_id}] [ERROR] {e}")
        return f"[{device_id}] Error: {e}"


def main():
    """Main execution function"""
    print("=" * 60)
    print("   Minecraft PaperMC Server - Start")
    print("   Interactive RAM selection on device")
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
    print("[*] Creating start script...")
    with tempfile.NamedTemporaryFile(
        mode='w', 
        encoding='utf-8', 
        newline='\n', 
        delete=False, 
        suffix='.sh'
    ) as f:
        f.write(TERMUX_START_SCRIPT)
        local_script_path = f.name
    print(f"[OK] Script saved to: {local_script_path}")
    print()
    
    # Start on all devices
    print("=" * 60)
    print(f"[*] Launching start menu on {len(devices)} device(s)...")
    print("=" * 60)
    print()
    
    max_workers = max(1, len(devices))
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_device = {
            executor.submit(start_minecraft_server, device_id, local_script_path): device_id
            for device_id in devices
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
    print("   What to do next:")
    print("=" * 60)
    print()
    print("   On each device, the start menu is now displayed showing:")
    print("   - Server IP address and port")
    print("   - RAM allocation prompt")
    print()
    print("   Press ENTER on device for default (1GB RAM)")
    print("   Or type a number (e.g., 2 for 2GB, 3 for 3GB)")
    print()
    print("   The server will start after you confirm RAM selection!")
    print("=" * 60)


if __name__ == "__main__":
    main()