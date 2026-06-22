"""CrowdStrike Falcon Sensor Installation Module

This module installs and configures the CrowdStrike Falcon sensor based on
configuration provided via vendor_data2.json. The sensor is automatically
registered with the appropriate CID (Customer ID) for the availability zone.

**Vendor Data Structure:**

The module expects configuration in vendor_data2.json under the nectar namespace:

.. code-block:: json

    {
      "nectar": {
        "crowdstrike": {
          "cid": "XXXXXXXXXXXXXXXXXXXXXXXXXXXX-XX",
          "provisioning_token": "XXXXXXXX",
          "tags": "Unmanaged_External",
          "installer_url": "https://example.com/path/to/falcon-sensor.deb",
          "enabled": true,
          "fail_if_missing": false
        }
      }
    }

**Configuration Keys:**

- ``cid``: CrowdStrike Customer ID (required)
- ``installer_url``: URL to download the Falcon sensor package (required)
- ``installer_url_deb`` / ``installer_url_rpm``: package-type-specific URLs,
  preferred over ``installer_url`` when present. An ``installer_url_rpm`` may
  contain the ``{el_version}`` placeholder, which is replaced with the host's
  Enterprise Linux major version (e.g. ``el9``) so one URL covers el8/el9/el10.
- ``provisioning_token``: Provisioning token for registration (optional)
- ``tags``: Comma-separated sensor grouping tags, e.g. ``Unmanaged_External``
  (optional)
- ``enabled``: Whether to install the sensor (default: true)
- ``fail_if_missing``: Halt boot if installation fails (default: false)

**Installation Process:**

1. Check if sensor is already installed
2. Download installer from provided URL
3. Install package using appropriate package manager (apt/yum)
4. Configure sensor with CID using falconctl
5. Start the falcon-sensor service
6. Log all steps to /var/log/cloud-init.log

**Module Behavior:**

- Runs in the cloud_final_modules stage
- Executes on every boot (PER_ALWAYS)
- Supports Ubuntu, Debian, RHEL, CentOS, and derivatives
- Always activated (``activate_by_schema_keys`` is empty); the handler reads
  vendor_data2 directly and returns early when no config is present. It cannot
  be gated on the ``crowdstrike`` schema key because the production config is
  nested under ``nectar.crowdstrike`` in vendor_data2, not a top-level key.

**Security Notes:**

- Configuration comes from immutable vendor_data2.json
- Users cannot override this configuration
- All downloads use HTTPS with retries for reliability
- Installation failures are logged but don't halt boot by default
"""

import logging
import os

from cloudinit import subp, temp_utils, type_utils, url_helper, util
from cloudinit.cloud import Cloud
from cloudinit.config.schema import MetaSchema
from cloudinit.distros import ALL_DISTROS
from cloudinit.settings import PER_ALWAYS

LOG = logging.getLogger(__name__)

# Module metadata
#
# ``activate_by_schema_keys`` is intentionally empty so the module ALWAYS runs.
# Cloud-init's activation gate (cloudinit/config/modules.py:_is_active) only
# matches activation keys against the *top-level* keys of the merged cloud
# config (``cfg.keys()``). Our production config lives in vendor_data2 under
# ``nectar.crowdstrike`` (nested, and not merged into ``cfg`` as a top-level
# ``crowdstrike`` key), so a ``["crowdstrike"]`` gate would never match and the
# module would silently never run in production. We instead always activate and
# let ``handle()`` read vendor_data2 directly and return early when there is no
# config. Do NOT re-add ``crowdstrike`` here.
meta: MetaSchema = {
    "id": "cc_crowdstrike",
    "distros": [ALL_DISTROS],
    "frequency": PER_ALWAYS,
    "activate_by_schema_keys": [],
}

# Constants
FALCON_SERVICE_NAME = "falcon-sensor"
FALCONCTL_PATH = "/opt/CrowdStrike/falconctl"
FALCON_INSTALLED_MARKER = "/opt/CrowdStrike"

# Placeholder operators may use in an RPM installer URL to have the module
# substitute the host's Enterprise Linux major version (e.g. el9). Lets a
# single installer_url_rpm cover el8/el9/el10 without per-version config.
EL_VERSION_PLACEHOLDER = "{el_version}"


def _is_falcon_installed() -> bool:
    """Check if CrowdStrike Falcon is already installed.

    Returns:
        True if Falcon is installed, False otherwise
    """
    return os.path.exists(FALCON_INSTALLED_MARKER)


def _get_package_type(distro) -> str:
    """Determine package type based on distro OS family.

    Uses cloud-init's canonical ``distro.osfamily`` as the primary signal
    (the same attribute cloud-init uses for its own package decisions), then
    falls back to the distro name and finally to probing for a package
    manager.

    Args:
        distro: Cloud-init distro object

    Returns:
        'deb' for Debian-based distros, 'rpm' for RHEL/SUSE-based

    Raises:
        RuntimeError: If distro is not supported
    """
    osfamily = getattr(distro, "osfamily", None)
    if osfamily == "debian":
        return "deb"
    elif osfamily in ["redhat", "suse"]:
        return "rpm"

    # Fall back to the distro name for older cloud-init or odd distros
    if distro.name in ["debian", "ubuntu"]:
        return "deb"
    elif distro.name in ["rhel", "centos", "fedora", "rocky", "almalinux"]:
        return "rpm"

    # Last resort: detect by checking for package managers
    try:
        subp.which("apt-get")
        return "deb"
    except subp.ProcessExecutionError:
        pass

    try:
        subp.which("yum")
        return "rpm"
    except subp.ProcessExecutionError:
        pass

    raise RuntimeError(
        f"Unsupported distro '{distro.name}' (osfamily '{osfamily}') "
        "for CrowdStrike installation"
    )


def _select_installer_url(cs_cfg: dict, package_type: str) -> str:
    """Pick the installer URL that matches the detected package type.

    Prefers the package-type-specific URL provided by nova-pollinate
    (``installer_url_deb`` / ``installer_url_rpm``) and falls back to the
    generic ``installer_url`` for backwards compatibility.

    Args:
        cs_cfg: CrowdStrike configuration dict
        package_type: Detected package type ('deb' or 'rpm')

    Returns:
        The selected installer URL, or None if none is available
    """
    specific = cs_cfg.get(f"installer_url_{package_type}")
    if specific:
        return specific
    return util.get_cfg_option_str(cs_cfg, "installer_url", None)


def _get_el_version() -> str:
    """Return the Enterprise Linux major version (e.g. '9') for this host.

    Reads ``VERSION_ID`` from ``/etc/os-release`` via cloud-init's
    ``get_linux_distro`` and returns the leading major-version component.

    Returns:
        The EL major version as a string, or None if it cannot be determined
    """
    try:
        _name, version, _flavor = util.get_linux_distro()
    except Exception as e:
        LOG.warning("Could not determine Linux distro version: %s", e)
        return None

    if not version:
        return None

    major = version.split(".")[0].strip()
    return major if major.isdigit() else None


def _resolve_el_version_in_url(url: str) -> str:
    """Substitute the EL-version placeholder in an installer URL.

    Args:
        url: Installer URL, possibly containing ``{el_version}``

    Returns:
        - The URL unchanged if it has no placeholder
        - The URL with ``{el_version}`` replaced by the detected EL major
          version
        - None if the placeholder is present but the EL version cannot be
          determined (caller should skip installation)
    """
    if EL_VERSION_PLACEHOLDER not in url:
        return url

    el_version = _get_el_version()
    if not el_version:
        return None

    return url.replace(EL_VERSION_PLACEHOLDER, el_version)


def _download_installer(url: str, dest_path: str) -> None:
    """Download the Falcon installer from the provided URL.

    Args:
        url: URL to download from
        dest_path: Destination file path

    Raises:
        RuntimeError: If download fails after retries
    """
    LOG.debug("Downloading CrowdStrike installer from: %s", url)

    try:
        response = url_helper.readurl(url=url, retries=5, timeout=300)
        util.write_file(dest_path, response.contents, mode=0o644, omode="wb")
        LOG.info("Successfully downloaded installer to: %s", dest_path)
    except Exception as e:
        msg = f"Failed to download CrowdStrike installer from {url}: {e}"
        util.logexc(LOG, msg)
        raise RuntimeError(msg) from e


def _install_package(distro, package_path: str, package_type: str) -> None:
    """Install the Falcon sensor package.

    Args:
        distro: Cloud-init distro object
        package_path: Path to the downloaded package
        package_type: Package type ('deb' or 'rpm')

    Raises:
        RuntimeError: If installation fails
    """
    LOG.info("Installing CrowdStrike Falcon sensor package: %s", package_path)

    try:
        if package_type == "deb":
            # Use dpkg for direct package installation
            cmd = ["dpkg", "-i", package_path]
            subp.subp(cmd, capture=False)

            # Fix any dependency issues
            try:
                subp.subp(["apt-get", "install", "-f", "-y"], capture=False)
            except subp.ProcessExecutionError as e:
                LOG.warning("apt-get install -f returned non-zero: %s", e)

        elif package_type == "rpm":
            # Use rpm or yum for installation
            try:
                cmd = ["rpm", "-ivh", package_path]
                subp.subp(cmd, capture=False)
            except subp.ProcessExecutionError:
                # If rpm fails, try yum localinstall
                LOG.debug("rpm installation failed, trying yum localinstall")
                cmd = ["yum", "localinstall", "-y", package_path]
                subp.subp(cmd, capture=False)

        LOG.info("Successfully installed CrowdStrike Falcon sensor")

    except subp.ProcessExecutionError as e:
        msg = f"Failed to install CrowdStrike package: {e}"
        util.logexc(LOG, msg)
        raise RuntimeError(msg) from e


def _configure_falcon(
    cid: str, provisioning_token: str = None, tags: str = None
) -> None:
    """Configure Falcon sensor with the provided CID.

    Registers the sensor with the CID (and provisioning token, if supplied)
    in a single ``falconctl`` call, mirroring the provider's documented
    process. Tags, when supplied, are applied in a separate call.

    Args:
        cid: CrowdStrike Customer ID
        provisioning_token: Provisioning token for registration (optional)
        tags: Sensor grouping tags, comma-separated (optional)

    Raises:
        RuntimeError: If configuration fails
    """
    if not os.path.exists(FALCONCTL_PATH):
        raise RuntimeError(
            f"falconctl not found at {FALCONCTL_PATH} after installation"
        )

    LOG.info("Configuring CrowdStrike Falcon with CID")

    try:
        # Set the CID, and the provisioning token in the same call when present
        cmd = [FALCONCTL_PATH, "-s", f"--cid={cid}"]
        if provisioning_token:
            cmd.append(f"--provisioning-token={provisioning_token}")
        subp.subp(cmd, capture=True)
        LOG.debug(
            "Successfully set CID%s",
            " and provisioning token" if provisioning_token else "",
        )

        # Apply tags in a separate call (provider documents this separately)
        if tags:
            subp.subp([FALCONCTL_PATH, "-s", f"--tags={tags}"], capture=True)
            LOG.debug("Successfully set tags: %s", tags)

    except subp.ProcessExecutionError as e:
        msg = f"Failed to configure CrowdStrike Falcon: {e}"
        util.logexc(LOG, msg)
        raise RuntimeError(msg) from e


def _start_falcon_service(distro) -> None:
    """Start and enable the Falcon sensor service.

    Args:
        distro: Cloud-init distro object

    Raises:
        RuntimeError: If service management fails
    """
    LOG.info("Starting CrowdStrike Falcon service")

    try:
        # Enable service to start on boot
        distro.manage_service("enable", FALCON_SERVICE_NAME)
        LOG.debug("Enabled falcon-sensor service")

        # Start the service now
        distro.manage_service("start", FALCON_SERVICE_NAME)
        LOG.info("Successfully started falcon-sensor service")

    except subp.ProcessExecutionError as e:
        msg = f"Failed to start CrowdStrike service: {e}"
        util.logexc(LOG, msg)
        raise RuntimeError(msg) from e


def _get_vendor_data_config(cloud: Cloud) -> dict:
    """Extract CrowdStrike config from vendor_data2.nectar.crowdstrike.

    Args:
        cloud: Cloud-init cloud object

    Returns:
        Dictionary with CrowdStrike configuration, or empty dict if not found
    """
    try:
        # Access vendor_data2 from the datasource
        vendor_data = cloud.datasource.get_vendordata2()

        if vendor_data and isinstance(vendor_data, dict):
            # Check nested structure: vendor_data2.nectar.crowdstrike
            nectar_data = vendor_data.get("nectar", {})
            if nectar_data and isinstance(nectar_data, dict):
                crowdstrike_cfg = nectar_data.get("crowdstrike", {})
                if crowdstrike_cfg:
                    LOG.debug("Found CrowdStrike config in vendor_data2.nectar")
                    return crowdstrike_cfg

            # Fallback: check top-level for backwards compatibility
            crowdstrike_cfg = vendor_data.get("crowdstrike", {})
            if crowdstrike_cfg:
                LOG.debug("Found CrowdStrike config in vendor_data2 (top-level)")
                return crowdstrike_cfg

        LOG.debug("No CrowdStrike config found in vendor_data2")
        return {}

    except Exception as e:
        LOG.warning("Failed to retrieve vendor_data2: %s", e)
        return {}


def handle(name: str, cfg: dict, cloud: Cloud, args: list) -> None:
    """Main handler for CrowdStrike Falcon installation.

    This function is called by cloud-init during the cloud_final_modules stage.
    It reads configuration from vendor_data2.json, downloads the Falcon sensor,
    and installs/configures it with the appropriate CID.

    Args:
        name: Module name
        cfg: Configuration dictionary (user-data config)
        cloud: Cloud object providing access to distro and datasource
        args: Additional arguments (unused)
    """
    LOG.debug("CrowdStrike module handler called")

    # Priority 1: Check vendor_data2 (immutable, operator-controlled)
    cs_cfg = _get_vendor_data_config(cloud)

    # Priority 2: Fall back to user-provided config (for testing)
    # In production, vendor_data2 should be the only source
    if not cs_cfg and "crowdstrike" in cfg:
        cs_cfg = cfg["crowdstrike"]
        LOG.warning(
            "Using CrowdStrike config from user-data. "
            "Production deployments should use vendor_data2"
        )

    # If no config found anywhere, skip silently
    if not cs_cfg:
        LOG.debug(
            "Skipping module %s, no 'crowdstrike' key in vendor_data2 or config", name
        )
        return

    # Validate config type
    if not isinstance(cs_cfg, dict):
        raise RuntimeError(
            f"'crowdstrike' key exists but is not a dictionary, "
            f"is a {type_utils.obj_name(cs_cfg)} instead"
        )

    # Check if installation is enabled
    enabled = util.get_cfg_option_bool(cs_cfg, "enabled", default=True)
    if not enabled:
        LOG.info("CrowdStrike installation disabled by config")
        return

    # Check if already installed
    if _is_falcon_installed():
        LOG.info(
            "CrowdStrike Falcon already installed at %s, skipping installation",
            FALCON_INSTALLED_MARKER,
        )
        return

    # Extract required configuration
    cid = util.get_cfg_option_str(cs_cfg, "cid", None)
    provisioning_token = util.get_cfg_option_str(cs_cfg, "provisioning_token", None)
    tags = util.get_cfg_option_str(cs_cfg, "tags", None)
    fail_if_missing = util.get_cfg_option_bool(cs_cfg, "fail_if_missing", default=False)

    # An installer URL may be supplied generically (installer_url) or as
    # package-type-specific variants (installer_url_deb / installer_url_rpm).
    has_installer_url = bool(
        cs_cfg.get("installer_url")
        or cs_cfg.get("installer_url_deb")
        or cs_cfg.get("installer_url_rpm")
    )

    # Validate required fields
    if not cid or not has_installer_url:
        msg = (
            "CrowdStrike configuration missing required fields. "
            f"cid={'present' if cid else 'MISSING'}, "
            f"installer_url={'present' if has_installer_url else 'MISSING'}"
        )

        if fail_if_missing:
            LOG.error(msg)
            raise RuntimeError(msg)
        else:
            LOG.warning(msg + " - Skipping installation")
            return

    LOG.info(
        "Starting CrowdStrike Falcon installation for CID: %s",
        cid[:8] + "..." if len(cid) > 8 else cid,
    )

    try:
        # Determine package type and select the matching installer URL
        package_type = _get_package_type(cloud.distro)
        installer_url = _select_installer_url(cs_cfg, package_type)
        if not installer_url:
            raise RuntimeError(
                "No CrowdStrike installer URL available for package type "
                f"'{package_type}'"
            )

        # Resolve any {el_version} placeholder (RPM installs on EL hosts).
        # An unresolvable EL version is always non-fatal: skip with a warning
        # even when fail_if_missing is set.
        resolved_url = _resolve_el_version_in_url(installer_url)
        if resolved_url is None:
            LOG.warning(
                "CrowdStrike installer URL '%s' requires an EL version that "
                "could not be determined for this host - skipping installation",
                installer_url,
            )
            return
        installer_url = resolved_url

        LOG.debug(
            "Detected package type: %s, using installer URL: %s",
            package_type,
            installer_url,
        )

        # Create temporary directory for download
        with temp_utils.tempdir(dir=cloud.distro.get_tmp_exec_path()) as tmpd:
            # Download installer
            package_ext = "deb" if package_type == "deb" else "rpm"
            installer_path = os.path.join(tmpd, f"falcon-sensor.{package_ext}")
            _download_installer(installer_url, installer_path)

            # Install package
            _install_package(cloud.distro, installer_path, package_type)

        # Configure with CID (plus provisioning token and tags when provided)
        _configure_falcon(cid, provisioning_token, tags)

        # Start the service
        _start_falcon_service(cloud.distro)

        LOG.info("CrowdStrike Falcon installation completed successfully")

    except Exception as e:
        msg = f"CrowdStrike Falcon installation failed: {e}"
        util.logexc(LOG, msg)

        if fail_if_missing:
            raise RuntimeError(msg) from e
        else:
            LOG.warning(msg + " - Continuing boot process")
