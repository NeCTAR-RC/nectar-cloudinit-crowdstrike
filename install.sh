#!/bin/bash
# Quick installation script for nectar-cloudinit-crowdstrike module
# This script should be run as root during image building

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

echo "=== Installing Nectar CrowdStrike Cloud-Init Module ==="
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script must be run as root"
    exit 1
fi

# Check if cloud-init is installed
if ! command -v cloud-init &> /dev/null; then
    echo "WARNING: cloud-init not found. This module requires cloud-init to be installed."
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
echo "Python version: $PYTHON_VERSION"

if ! command -v pip &> /dev/null && ! command -v pip3 &> /dev/null; then
    echo "ERROR: pip/pip3 not found. Please install python3-pip first."
    exit 1
fi

# Determine pip command
if command -v pip3 &> /dev/null; then
    PIP_CMD="pip3"
else
    PIP_CMD="pip"
fi

echo "Using pip command: $PIP_CMD"
echo

# Install the module
echo "Installing nectar-cloudinit-crowdstrike..."
cd "$SCRIPT_DIR"
$PIP_CMD install .

echo
echo "=== Installation Complete ==="
echo

# Verify installation
echo "Verifying installation..."
echo

if [ -f "/usr/lib/python3/dist-packages/cloudinit/config/cc_crowdstrike.py" ]; then
    echo "✓ Module installed: /usr/lib/python3/dist-packages/cloudinit/config/cc_crowdstrike.py"
else
    echo "✗ Module NOT found at expected location"
    exit 1
fi

if [ -f "/etc/cloud/cloud.cfg.d/99_crowdstrike.cfg" ]; then
    echo "✓ Config installed: /etc/cloud/cloud.cfg.d/99_crowdstrike.cfg"
else
    echo "✗ Config NOT found at expected location"
    exit 1
fi

# Test import
if python3 -c "from cloudinit.config import cc_crowdstrike" 2>/dev/null; then
    echo "✓ Module can be imported successfully"
else
    echo "✗ Module import failed"
    exit 1
fi

echo
echo "=== Installation Verified ==="
echo
echo "Next steps:"
echo "1. Ensure nova-pollinate is configured with CrowdStrike provider"
echo "2. Ensure Vault contains CrowdStrike credentials for your AZs"
echo "3. Test with: sudo cloud-init single --name crowdstrike --frequency always"
echo
echo "See TESTING.md for detailed testing instructions"
