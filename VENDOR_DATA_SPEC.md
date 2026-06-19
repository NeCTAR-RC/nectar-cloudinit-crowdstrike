# Vendor Data Specification

## Structure

The CrowdStrike module expects configuration in the following nested structure within `vendor_data2.json`:

```json
{
  "nectar": {
    "nvidia_vgpu": {
      "license_token": "..."
    },
    "crowdstrike": {
      "cid": "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX-XX",
      "installer_url": "https://secure.example.com/falcon/falcon-sensor.deb",
      "enabled": true,
      "fail_if_missing": false
    }
  }
}
```

## Path

**Primary path**: `vendor_data2.nectar.crowdstrike`

**Fallback path**: `vendor_data2.crowdstrike` (backwards compatibility)

## Configuration Schema

### Required Fields

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `cid` | string | `"1234567890ABCDEF-12"` | CrowdStrike Customer ID for sensor registration |
| `installer_url` | string | `"https://example.com/falcon-sensor.deb"` | HTTPS URL to download the Falcon sensor package (.deb or .rpm) |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `true` | Whether to install the sensor (useful for testing/rollback) |
| `fail_if_missing` | boolean | `false` | Halt boot if installation fails (fail-closed behavior) |

## Examples

### Minimal Configuration

```json
{
  "nectar": {
    "crowdstrike": {
      "cid": "1234567890ABCDEF1234567890ABCD-12",
      "installer_url": "https://packages.example.com/falcon-sensor-7.10.0.deb"
    }
  }
}
```

### Full Configuration

```json
{
  "nectar": {
    "crowdstrike": {
      "cid": "1234567890ABCDEF1234567890ABCD-12",
      "installer_url": "https://packages.example.com/falcon-sensor-7.10.0.deb",
      "enabled": true,
      "fail_if_missing": false
    }
  }
}
```

### Disabled Installation

```json
{
  "nectar": {
    "crowdstrike": {
      "cid": "1234567890ABCDEF1234567890ABCD-12",
      "installer_url": "https://packages.example.com/falcon-sensor-7.10.0.deb",
      "enabled": false
    }
  }
}
```

### Fail-Closed Mode

```json
{
  "nectar": {
    "crowdstrike": {
      "cid": "1234567890ABCDEF1234567890ABCD-12",
      "installer_url": "https://packages.example.com/falcon-sensor-7.10.0.deb",
      "enabled": true,
      "fail_if_missing": true
    }
  }
}
```

## Nova-Pollinate Provider Output

The CrowdStrike provider in nova-pollinate should inject configuration at the `nectar.crowdstrike` path:

```python
# Nova-pollinate provider example
def provide_vendor_data(context):
    """Provide CrowdStrike configuration from Vault."""
    az = context.get('availability_zone')

    # Query Vault for secrets
    secrets = vault.read(f'secret/crowdstrike/{az}')

    # Return nested structure
    return {
        'nectar': {
            'crowdstrike': {
                'cid': secrets['cid'],
                'installer_url': secrets['installer_url'],
                'enabled': secrets.get('enabled', True),
                'fail_if_missing': secrets.get('fail_if_missing', False)
            }
        }
    }
```

## Vault Secret Structure

Store secrets in Vault at `secret/crowdstrike/{availability_zone}`:

### Path Examples
- `secret/crowdstrike/melbourne-qh2`
- `secret/crowdstrike/monash-01`
- `secret/crowdstrike/tasmania`

### Secret Format

```json
{
  "cid": "1234567890ABCDEF1234567890ABCD-12",
  "installer_url": "https://packages.internal.nectar.org.au/crowdstrike/falcon-sensor-7.10.0-16003.deb",
  "enabled": true,
  "fail_if_missing": false
}
```

### Setting Secrets via Vault CLI

```bash
# Set CrowdStrike secrets for an availability zone
vault kv put secret/crowdstrike/melbourne-qh2 \
  cid="1234567890ABCDEF1234567890ABCD-12" \
  installer_url="https://packages.internal.nectar.org.au/crowdstrike/falcon-sensor.deb" \
  enabled=true \
  fail_if_missing=false

# Read back to verify
vault kv get secret/crowdstrike/melbourne-qh2
```

## Regional Variation

Different availability zones can have different CIDs and installer URLs:

```bash
# Melbourne zone
vault kv put secret/crowdstrike/melbourne-qh2 \
  cid="MELBOURNE-CID-HERE" \
  installer_url="https://melbourne.packages.nectar.org.au/falcon-sensor.deb"

# Monash zone
vault kv put secret/crowdstrike/monash-01 \
  cid="MONASH-CID-HERE" \
  installer_url="https://monash.packages.nectar.org.au/falcon-sensor.rpm"

# Tasmania zone - disabled for testing
vault kv put secret/crowdstrike/tasmania \
  cid="TASMANIA-CID-HERE" \
  installer_url="https://tas.packages.nectar.org.au/falcon-sensor.deb" \
  enabled=false
```

## Validation

### Check Structure on Instance

```bash
# SSH to instance after boot
ssh ubuntu@instance-ip

# Query vendor_data2
cloud-init query vendor_data2.nectar.crowdstrike

# Expected output:
# {
#   "cid": "...",
#   "installer_url": "...",
#   "enabled": true,
#   "fail_if_missing": false
# }
```

### Validate in Cloud-Init Logs

```bash
# Check if module found configuration
sudo grep "Found CrowdStrike config" /var/log/cloud-init.log

# Should see one of:
# - "Found CrowdStrike config in vendor_data2.nectar"
# - "Found CrowdStrike config in vendor_data2 (top-level)"  # fallback
```

## Backwards Compatibility

The module checks two paths in order:

1. **Primary**: `vendor_data2.nectar.crowdstrike`
2. **Fallback**: `vendor_data2.crowdstrike`

If you need to migrate from the old top-level structure, the module will continue to work during the transition period.

### Old Structure (Still Supported)

```json
{
  "crowdstrike": {
    "cid": "...",
    "installer_url": "..."
  }
}
```

### New Structure (Recommended)

```json
{
  "nectar": {
    "crowdstrike": {
      "cid": "...",
      "installer_url": "..."
    }
  }
}
```

## Troubleshooting

### No Configuration Found

**Symptom**: Log shows "No CrowdStrike config found in vendor_data2"

**Check**:
1. Verify nova-pollinate is configured and running
2. Check Vault has secrets for the AZ
3. Verify vendor_data2 structure on instance:
   ```bash
   cloud-init query vendor_data2 | jq .
   ```

### Configuration at Wrong Path

**Symptom**: Configuration exists but module doesn't find it

**Fix**: Ensure it's at `vendor_data2.nectar.crowdstrike`, not just `vendor_data2.crowdstrike`

**Temporary workaround**: The module supports both paths, but logs will indicate which was used.
