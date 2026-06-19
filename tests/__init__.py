"""Test package for nectar_crowdstrike.

cloud-init ships as a system package and is not published to PyPI, so it
cannot be installed into the tox virtualenv. The module under test imports a
handful of cloudinit symbols at import time, but its testable logic does not
depend on cloud-init internals. We register lightweight stand-ins for the
cloudinit modules here, before any test imports cc_crowdstrike, so the suite
runs without a real cloud-init installation.
"""

import sys
import types
from unittest import mock


def _install_fake_cloudinit():
    if "cloudinit" in sys.modules:
        return

    def get_cfg_option_str(cfg, key, default=None):
        val = cfg.get(key, default)
        return default if val is None else str(val)

    def get_cfg_option_bool(cfg, key, default=False):
        return bool(cfg.get(key, default))

    subp = types.ModuleType("cloudinit.subp")
    subp.ProcessExecutionError = type("ProcessExecutionError", (Exception,), {})
    subp.which = mock.MagicMock()
    subp.subp = mock.MagicMock()

    util = types.ModuleType("cloudinit.util")
    util.get_cfg_option_str = get_cfg_option_str
    util.get_cfg_option_bool = get_cfg_option_bool
    util.write_file = mock.MagicMock()
    util.logexc = mock.MagicMock()

    type_utils = types.ModuleType("cloudinit.type_utils")
    type_utils.obj_name = lambda obj: type(obj).__name__

    cloud_mod = types.ModuleType("cloudinit.cloud")
    cloud_mod.Cloud = type("Cloud", (), {})

    schema_mod = types.ModuleType("cloudinit.config.schema")
    schema_mod.MetaSchema = dict

    distros_mod = types.ModuleType("cloudinit.distros")
    distros_mod.ALL_DISTROS = "all"

    settings_mod = types.ModuleType("cloudinit.settings")
    settings_mod.PER_ALWAYS = "always"

    modules = {
        "cloudinit": types.ModuleType("cloudinit"),
        "cloudinit.subp": subp,
        "cloudinit.util": util,
        "cloudinit.temp_utils": types.ModuleType("cloudinit.temp_utils"),
        "cloudinit.type_utils": type_utils,
        "cloudinit.url_helper": types.ModuleType("cloudinit.url_helper"),
        "cloudinit.cloud": cloud_mod,
        "cloudinit.config": types.ModuleType("cloudinit.config"),
        "cloudinit.config.schema": schema_mod,
        "cloudinit.distros": distros_mod,
        "cloudinit.settings": settings_mod,
    }
    sys.modules.update(modules)


_install_fake_cloudinit()
