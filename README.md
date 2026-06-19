# Nectar Cloud-Init CrowdStrike Module

A custom cloud-init module for automatic deployment of CrowdStrike Falcon sensor across the Nectar Research Cloud. This module integrates with OpenStack's `vendor_data2.json` to provide immutable, operator-controlled security agent installation.

## Overview

This package provides an out-of-tree cloud-init module that:

- Installs CrowdStrike Falcon sensor at instance boot time
- Reads configuration from immutable `vendor_data2.json` (not user-overrideable)
- Supports regional variation via Availability Zones
- Works with both Debian/Ubuntu (apt) and RHEL/CentOS (yum) distributions
- Uses distro-packaged cloud-init (no forking required)

## Architecture

```
┌─────────────────┐
│  Nova Compute   │
│                 │
│  Instance Boot  │
└────────┬────────┘
         │
         │ Context: {project_id, az, ...}
         │
┌────────▼────────┐
│ nova-pollinate  │
│                 │
│ CrowdStrike     │
│   Provider      │
└────────┬────────┘
         │
         │ Query: secret/crowdstrike/{az}
         │
┌────────▼────────┐
│  HashiCorp      │
│    Vault        │
│                 │
│  Returns: CID,  │
│   installer_url │
└────────┬────────┘
         │
         │ Inject into vendor_data2.json
         │
┌────────▼────────┐
│   Guest OS      │
│                 │
│  cloud-init     │
│  cc_crowdstrike │
│                 │
│  Downloads &    │
│  Installs       │
│  Falcon Sensor  │
└─────────────────┘
```

## Installation

### For Image Building

Install this package during your base image build process:

```bash
# Install as root
sudo pip install nectar-cloudinit-crowdstrike

# Or from local directory
sudo pip install /path/to/nectar-cloudinit-crowdstrike
```

This will:
1. Install `cc_crowdstrike.py` to `/usr/lib/python3/dist-packages/cloudinit/config/`
2. Install `99_crowdstrike.cfg` to `/etc/cloud/cloud.cfg.d/`

### For Development/Testing

```bash
# Clone the repository
git clone https://github.com/NectarCloud/nectar-cloudinit-crowdstrike.git
cd nectar-cloudinit-crowdstrike

# Install in development mode
sudo pip install -e .
```

### Verify Installation

```bash
# Check if module is installed
ls -l /usr/lib/python3/dist-packages/cloudinit/config/cc_crowdstrike.py

# Check if config is installed
ls -l /etc/cloud/cloud.cfg.d/99_crowdstrike.cfg

# Verify module is recognized by cloud-init
cloud-init query --all | grep crowdstrike
```

## Configuration

### Vendor Data Structure

The module expects configuration via `vendor_data2.json` from nova-pollinate under the `nectar` namespace:

```json
{
  "nectar": {
    "crowdstrike": {
      "cid": "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX-XX",
      "installer_url": "https://secure.example.com/falcon/falcon-sensor-7.10.0-16003.deb",
      "enabled": true,
      "fail_if_missing": false
    }
  }
}
```

The module will also check the top-level `crowdstrike` key for backwards compatibility.

### Configuration Options

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `cid` | string | Yes | - | CrowdStrike Customer ID for sensor registration |
| `installer_url` | string | Yes | - | HTTPS URL to download Falcon sensor package (.deb or .rpm) |
| `enabled` | boolean | No | `true` | Enable/disable installation (for testing/rollback) |
| `fail_if_missing` | boolean | No | `false` | Halt boot if installation fails (fail-closed behavior) |

### Nova-Pollinate Integration

Add to your nova-pollinate configuration (`/etc/nova-pollinate/nova-pollinate.conf`):

```ini
[crowdstrike]
enabled = true
vault_url = https://vault.example.com:8200
vault_token = s.XXXXXXXXXXXXXXXXXXXXXXXXXX
vault_mount_point = secret
vault_path_template = crowdstrike/{availability_zone}
```

The CrowdStrike provider in nova-pollinate will:
1. Receive instance context (including availability_zone)
2. Query Vault at `secret/crowdstrike/{availability_zone}`
3. Inject CID and installer_url into `vendor_data2.json` under the `nectar.crowdstrike` path

## Module Behavior

### Execution Stage

The module runs in the `cloud_final_modules` stage, after:
- Network configuration
- Package repositories are configured
- System is fully initialized

### Execution Frequency

The module runs on **every boot** (`PER_ALWAYS`), but includes logic to skip if already installed:
- Checks for `/opt/CrowdStrike` directory
- Logs "already installed" and skips download/installation

### Installation Steps

1. **Check if already installed** - Exit early if sensor exists
2. **Validate configuration** - Ensure CID and installer_url are present
3. **Detect package type** - Determine .deb vs .rpm based on distro
4. **Download installer** - Fetch from URL with 5 retries, 300s timeout
5. **Install package** - Use dpkg/rpm and fix dependencies
6. **Configure sensor** - Set CID using `/opt/CrowdStrike/falconctl`
7. **Start service** - Enable and start `falcon-sensor.service`
8. **Log results** - All steps logged to `/var/log/cloud-init.log`

### Supported Distributions

- **Debian-based**: Ubuntu, Debian (uses apt/dpkg)
- **RHEL-based**: RHEL, CentOS, Rocky, AlmaLinux, Fedora (uses yum/rpm)

## Testing

### Manual Testing with User-Data

For testing without nova-pollinate, you can provide config via user-data:

```yaml
#cloud-config
crowdstrike:
  cid: "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX-XX"
  installer_url: "https://example.com/falcon-sensor.deb"
  enabled: true
```

**Note**: In production, this should come from `vendor_data2.json` only.

### Running the Module Manually

```bash
# Run just the crowdstrike module
sudo cloud-init single --name crowdstrike --frequency always

# Check logs
sudo tail -f /var/log/cloud-init.log | grep -i crowdstrike

# Verify installation
sudo /opt/CrowdStrike/falconctl -g --cid
sudo systemctl status falcon-sensor
```

### Verifying Vendor Data

```bash
# Check what vendor data was received
sudo cat /run/cloud-init/instance-data.json | jq '.vendor_data2.nectar.crowdstrike'

# Or query with cloud-init
cloud-init query vendor_data2.nectar.crowdstrike

# View the entire nectar namespace
cloud-init query vendor_data2.nectar
```

### Test in a VM

```bash
# Clean cloud-init state for fresh run
sudo cloud-init clean --logs

# Reboot to trigger cloud-init
sudo reboot

# After reboot, check if Falcon is installed
sudo systemctl status falcon-sensor
```

## Troubleshooting

### Module Not Running

**Check if module is registered:**
```bash
cloud-init query --list-all-modules | grep crowdstrike
```

**Check cloud-init configuration:**
```bash
grep -r crowdstrike /etc/cloud/cloud.cfg.d/
```

### Installation Failures

**View detailed logs:**
```bash
sudo cat /var/log/cloud-init.log | grep -A 50 "CrowdStrike"
```

**Common issues:**
- **No vendor_data2**: Module will skip silently (check nova-pollinate)
- **Download failures**: Check URL accessibility, network connectivity
- **Package installation errors**: Check package compatibility with distro
- **falconctl not found**: Verify package installed correctly
- **Service start failures**: Check systemd logs with `journalctl -u falcon-sensor`

### Disable CrowdStrike Installation

**Temporary (via vendor_data2):**
```json
{
  "crowdstrike": {
    "enabled": false
  }
}
```

**Permanent (remove module):**
```bash
sudo pip uninstall nectar-cloudinit-crowdstrike
sudo rm /usr/lib/python3/dist-packages/cloudinit/config/cc_crowdstrike.py
sudo rm /etc/cloud/cloud.cfg.d/99_crowdstrike.cfg
```

## Security Considerations

### Immutability

- Configuration comes from `vendor_data2.json` (operator-controlled)
- Users **cannot override** via `user-data` in production
- Module prioritizes vendor_data2 over user-data

### Fail-Closed Mode

Enable `fail_if_missing: true` to halt boot if installation fails:
```json
{
  "crowdstrike": {
    "fail_if_missing": true
  }
}
```

This ensures no unprotected VMs run in production.

### Credential Management

- CIDs and installer URLs stored in HashiCorp Vault
- Regional isolation (each AZ has separate credentials)
- No hardcoded secrets in code or images

### Audit Trail

All installation steps logged to `/var/log/cloud-init.log`:
- Download attempts and sources
- Installation commands and results
- Configuration changes
- Service status changes

## Development

### Project Structure

```
nectar-cloudinit-crowdstrike/
├── nectar_crowdstrike/
│   └── cc_crowdstrike.py      # Main module implementation
├── config/
│   └── 99_crowdstrike.cfg     # Cloud-init configuration
├── tests/
│   └── (future unit tests)
├── setup.py                    # Package installation config
└── README.md                   # This file
```

### Running Tests

```bash
# Run unit tests (when implemented)
pytest tests/

# Run integration tests in a VM
# (use cloud-init integration test framework)
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test in a VM with cloud-init
5. Submit a pull request

## Deployment Workflow

### Phase 1: Development
1. Develop and test module in test cloud
2. Build test images with `pip install nectar-cloudinit-crowdstrike`
3. Test on Ubuntu, Debian, RHEL base images

### Phase 2: Review
1. Circulate proposal with RC-Ops community
2. Submit to Technical Committee
3. Submit to Steering Committee
4. Submit to Change Advisory Board (CAB)

### Phase 3: Production Deployment
1. Deploy nova-pollinate changes to production
2. Configure Vault secrets per availability zone
3. Build production images with module installed
4. Roll out to production nodes

## License

Apache License 2.0 (or as per Nectar Research Cloud licensing)

## Support

For issues or questions:
- GitHub Issues: https://github.com/NectarCloud/nectar-cloudinit-crowdstrike/issues
- Nectar Research Cloud Support: https://support.nectar.org.au/

## References

- [Cloud-init Documentation](https://cloudinit.readthedocs.io/)
- [Custom Cloud-init Modules](https://cloudinit.readthedocs.io/en/latest/reference/custom_modules/custom_configuration_module.html)
- [CrowdStrike Falcon Documentation](https://falcon.crowdstrike.com/documentation/)
- [OpenStack Vendor Data](https://docs.openstack.org/nova/latest/user/metadata.html#vendordata)
