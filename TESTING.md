# Testing Guide for Nectar CrowdStrike Module

This guide provides instructions for testing the CrowdStrike cloud-init module in various environments.

## Quick Start Testing

### 1. Install the Module

```bash
# From the project directory
cd nectar-cloudinit-crowdstrike
sudo pip install -e .
```

### 2. Verify Installation

```bash
# Check module file exists
ls -l /usr/lib/python3/dist-packages/cloudinit/config/cc_crowdstrike.py

# Check config exists
cat /etc/cloud/cloud.cfg.d/99_crowdstrike.cfg

# Verify cloud-init recognizes it
cloud-init query --list-all-modules | grep crowdstrike
```

### 3. Test with User-Data (Development Only)

```bash
# Create test user-data (replace with real CID and URL)
cat > /tmp/user-data.yaml <<'EOF'
#cloud-config
crowdstrike:
  cid: "YOUR-REAL-CID-HERE"
  installer_url: "https://your-download-url/falcon-sensor.deb"
  enabled: true
  fail_if_missing: false
EOF

# Clean cloud-init state
sudo cloud-init clean --logs --seed

# Run cloud-init with test data
sudo cloud-init init --local
sudo cloud-init init
sudo cloud-init modules --mode=config
sudo cloud-init modules --mode=final

# Check logs
sudo tail -100 /var/log/cloud-init.log | grep -i crowdstrike
```

### 4. Manual Module Execution

```bash
# Run just the CrowdStrike module
sudo cloud-init single --name crowdstrike --frequency always

# Watch logs in real-time
sudo tail -f /var/log/cloud-init.log
```

### 5. Verify Installation

```bash
# Check if Falcon is installed
ls -la /opt/CrowdStrike/

# Check CID configuration
sudo /opt/CrowdStrike/falconctl -g --cid

# Check service status
sudo systemctl status falcon-sensor

# Check if sensor is communicating
sudo /opt/CrowdStrike/falconctl -g --aid
```

## Testing with Vendor Data

### Simulating Vendor Data (without nova-pollinate)

```bash
# Create instance-data.json with vendor_data2
sudo mkdir -p /run/cloud-init

sudo cat > /run/cloud-init/instance-data.json <<'EOF'
{
  "vendor_data2": {
    "nectar": {
      "crowdstrike": {
        "cid": "YOUR-REAL-CID-HERE",
        "installer_url": "https://your-url/falcon-sensor.deb",
        "enabled": true
      }
    }
  }
}
EOF

# Clean and re-run cloud-init
sudo cloud-init clean --logs
sudo cloud-init init --local
sudo cloud-init modules --mode=final
```

## Testing in a VM

### Ubuntu/Debian VM

```bash
# 1. Launch a test VM
openstack server create \
  --image ubuntu-22.04 \
  --flavor m3.small \
  --key-name your-key \
  --user-data tests/test_user_data.yaml \
  test-crowdstrike-vm

# 2. SSH into VM after boot
ssh ubuntu@<vm-ip>

# 3. Check cloud-init logs
sudo cat /var/log/cloud-init.log | grep -i crowdstrike

# 4. Verify Falcon installation
sudo systemctl status falcon-sensor
sudo /opt/CrowdStrike/falconctl -g --cid
```

### RHEL/CentOS VM

```bash
# Same process, use RHEL image and RPM installer URL
openstack server create \
  --image centos-stream-9 \
  --flavor m3.small \
  --key-name your-key \
  --user-data tests/test_user_data.yaml \
  test-crowdstrike-rhel
```

## Testing Different Scenarios

### Test 1: Normal Installation

```yaml
crowdstrike:
  cid: "VALID-CID"
  installer_url: "https://valid-url/falcon-sensor.deb"
  enabled: true
```

**Expected**: Module installs Falcon successfully, service starts.

### Test 2: Disabled Installation

```yaml
crowdstrike:
  enabled: false
```

**Expected**: Module logs "CrowdStrike installation disabled" and exits.

### Test 3: Already Installed

```bash
# Install Falcon manually first
sudo dpkg -i /path/to/falcon-sensor.deb
sudo /opt/CrowdStrike/falconctl -s --cid=YOUR-CID

# Then run cloud-init
sudo cloud-init single --name crowdstrike --frequency always
```

**Expected**: Module detects existing installation and skips.

### Test 4: Missing Configuration

```yaml
# No crowdstrike key at all
```

**Expected**: Module logs "Skipping module, no crowdstrike key" and exits.

### Test 5: Invalid URL

```yaml
crowdstrike:
  cid: "VALID-CID"
  installer_url: "https://invalid-url/does-not-exist.deb"
  enabled: true
```

**Expected**: Module logs download failure, exits gracefully (unless fail_if_missing).

### Test 6: Fail-Closed Mode

```yaml
crowdstrike:
  cid: "VALID-CID"
  installer_url: "https://invalid-url/does-not-exist.deb"
  enabled: true
  fail_if_missing: true
```

**Expected**: Module raises RuntimeError, cloud-init reports failure.

## Debugging

### Enable Debug Logging

```bash
# Add to /etc/cloud/cloud.cfg.d/99_debug.cfg
sudo tee /etc/cloud/cloud.cfg.d/99_debug.cfg > /dev/null <<EOF
#cloud-config
debug:
  verbose: true
EOF

# Clean and re-run
sudo cloud-init clean --logs
sudo reboot
```

### Check Module Import

```bash
# Try to import the module directly
sudo python3 -c "from cloudinit.config import cc_crowdstrike; print(cc_crowdstrike.meta)"
```

### Check Module Registration

```bash
# List all available modules
cloud-init query --list-all-modules

# Check module metadata
cloud-init schema --annotate --config-file tests/test_user_data.yaml
```

### Manual Download Test

```bash
# Test if URL is accessible
curl -I https://your-url/falcon-sensor.deb

# Test manual download
wget https://your-url/falcon-sensor.deb

# Test manual installation
sudo dpkg -i falcon-sensor.deb
```

## Integration Testing

### With nova-pollinate (Full Stack)

1. **Configure Vault** with test secrets:
```bash
vault kv put secret/crowdstrike/test \
  cid="YOUR-CID" \
  installer_url="https://your-url/falcon-sensor.deb"
```

2. **Configure nova-pollinate** on compute node:
```ini
[crowdstrike]
enabled = true
vault_url = https://vault.example.com:8200
vault_token = s.XXXXXX
vault_path_template = crowdstrike/{availability_zone}
```

3. **Launch instance** in test AZ:
```bash
openstack server create \
  --image nectar-ubuntu-22.04-with-crowdstrike-module \
  --flavor m3.small \
  --availability-zone test \
  test-full-stack
```

4. **Verify vendor_data2** on instance:
```bash
ssh ubuntu@<ip>
cloud-init query vendor_data2.nectar.crowdstrike
```

## Performance Testing

### Measure Installation Time

```bash
# Add timestamp logging
sudo cloud-init single --name crowdstrike --frequency always 2>&1 | ts

# Or check cloud-init timing
cloud-init analyze show
cloud-init analyze blame
```

## Clean Up After Testing

```bash
# Remove Falcon sensor
sudo systemctl stop falcon-sensor
sudo apt-get remove -y falcon-sensor  # or: yum remove falcon-sensor
sudo rm -rf /opt/CrowdStrike

# Clean cloud-init state
sudo cloud-init clean --logs --seed

# Reboot for fresh test
sudo reboot
```

## Uninstall Module

```bash
# Remove via pip
sudo pip uninstall nectar-cloudinit-crowdstrike

# Or manually remove files
sudo rm /usr/lib/python3/dist-packages/cloudinit/config/cc_crowdstrike.py
sudo rm /etc/cloud/cloud.cfg.d/99_crowdstrike.cfg
sudo rm -rf /usr/lib/python3/dist-packages/nectar_crowdstrike*
```

## Common Issues

### Module Not Running

**Symptom**: No CrowdStrike logs in cloud-init.log

**Check**:
```bash
# Is module installed?
ls -l /usr/lib/python3/dist-packages/cloudinit/config/cc_crowdstrike.py

# Is it registered?
grep crowdstrike /etc/cloud/cloud.cfg.d/99_crowdstrike.cfg

# Can it be imported?
python3 -c "from cloudinit.config import cc_crowdstrike"
```

### Download Failures

**Symptom**: "Failed to download CrowdStrike installer"

**Check**:
```bash
# Network connectivity
curl -v https://your-url/falcon-sensor.deb

# DNS resolution
nslookup your-download-host

# Firewall rules
sudo iptables -L -n
```

### Installation Failures

**Symptom**: "Failed to install CrowdStrike package"

**Check**:
```bash
# Manual installation
sudo dpkg -i /path/to/falcon-sensor.deb

# Check dependencies
sudo apt-get install -f

# Check disk space
df -h
```

### Service Not Starting

**Symptom**: "Failed to start CrowdStrike service"

**Check**:
```bash
# Service logs
sudo journalctl -u falcon-sensor -n 100

# Manual start
sudo systemctl start falcon-sensor

# Check CID
sudo /opt/CrowdStrike/falconctl -g --cid
```

## CI/CD Integration

### Testing in CI Pipeline

```bash
#!/bin/bash
# ci-test.sh

set -e

# Install module
sudo pip install .

# Verify files
test -f /usr/lib/python3/dist-packages/cloudinit/config/cc_crowdstrike.py
test -f /etc/cloud/cloud.cfg.d/99_crowdstrike.cfg

# Import test
python3 -c "from cloudinit.config import cc_crowdstrike"

# Syntax check
python3 -m py_compile /usr/lib/python3/dist-packages/cloudinit/config/cc_crowdstrike.py

echo "All tests passed!"
```
