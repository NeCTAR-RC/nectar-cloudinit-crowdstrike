# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2024

### Added
- Initial release of nectar-cloudinit-crowdstrike module
- Support for automatic CrowdStrike Falcon sensor installation via vendor_data2
- Support for Debian/Ubuntu (apt/dpkg) and RHEL/CentOS (yum/rpm) distributions
- Nested vendor_data2 structure: `vendor_data2.nectar.crowdstrike`
- Backwards compatibility with top-level `vendor_data2.crowdstrike`
- Configuration options: cid, installer_url, enabled, fail_if_missing
- Automatic service management (enable and start falcon-sensor)
- Comprehensive logging to cloud-init.log
- Skip logic if sensor already installed
- Download with retries for reliability
- Ansible integration examples and documentation

### Technical Details
- Module ID: `cc_crowdstrike`
- Execution stage: `cloud_final_modules`
- Frequency: `PER_ALWAYS`
- Vendor data path: `vendor_data2.nectar.crowdstrike`
- Fallback path: `vendor_data2.crowdstrike` (backwards compatibility)
