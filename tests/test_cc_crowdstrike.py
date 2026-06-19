"""Unit tests for the cc_crowdstrike cloud-init module."""

from unittest import mock

import testtools

from nectar_crowdstrike import cc_crowdstrike


class FakeDistro:
    """Minimal stand-in for a cloud-init distro object."""

    def __init__(self, name="ubuntu", osfamily="debian"):
        self.name = name
        self.osfamily = osfamily


class GetPackageTypeTest(testtools.TestCase):
    def test_debian_osfamily_returns_deb(self):
        distro = FakeDistro(name="ubuntu", osfamily="debian")
        self.assertEqual("deb", cc_crowdstrike._get_package_type(distro))

    def test_redhat_osfamily_returns_rpm(self):
        distro = FakeDistro(name="centos", osfamily="redhat")
        self.assertEqual("rpm", cc_crowdstrike._get_package_type(distro))

    def test_suse_osfamily_returns_rpm(self):
        distro = FakeDistro(name="opensuse", osfamily="suse")
        self.assertEqual("rpm", cc_crowdstrike._get_package_type(distro))

    def test_name_fallback_when_osfamily_unknown(self):
        distro = FakeDistro(name="rocky", osfamily=None)
        self.assertEqual("rpm", cc_crowdstrike._get_package_type(distro))


class SelectInstallerUrlTest(testtools.TestCase):
    def test_prefers_package_specific_url(self):
        cfg = {
            "installer_url": "https://example.com/generic.deb",
            "installer_url_deb": "https://example.com/specific.deb",
        }
        self.assertEqual(
            "https://example.com/specific.deb",
            cc_crowdstrike._select_installer_url(cfg, "deb"),
        )

    def test_falls_back_to_generic_url(self):
        cfg = {"installer_url": "https://example.com/generic.deb"}
        self.assertEqual(
            "https://example.com/generic.deb",
            cc_crowdstrike._select_installer_url(cfg, "rpm"),
        )

    def test_returns_none_when_no_url(self):
        self.assertIsNone(cc_crowdstrike._select_installer_url({}, "deb"))


class IsFalconInstalledTest(testtools.TestCase):
    @mock.patch.object(cc_crowdstrike.os.path, "exists", return_value=True)
    def test_returns_true_when_marker_present(self, m_exists):
        self.assertTrue(cc_crowdstrike._is_falcon_installed())
        m_exists.assert_called_once_with(cc_crowdstrike.FALCON_INSTALLED_MARKER)

    @mock.patch.object(cc_crowdstrike.os.path, "exists", return_value=False)
    def test_returns_false_when_marker_absent(self, m_exists):
        self.assertFalse(cc_crowdstrike._is_falcon_installed())
