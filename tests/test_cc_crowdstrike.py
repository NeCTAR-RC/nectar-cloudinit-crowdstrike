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


class GetElVersionTest(testtools.TestCase):
    @mock.patch.object(
        cc_crowdstrike.util, "get_linux_distro", return_value=("rocky", "9.3", "")
    )
    def test_extracts_major_from_dotted_version(self, m_distro):
        self.assertEqual("9", cc_crowdstrike._get_el_version())

    @mock.patch.object(
        cc_crowdstrike.util, "get_linux_distro", return_value=("redhat", "8", "")
    )
    def test_handles_bare_major_version(self, m_distro):
        self.assertEqual("8", cc_crowdstrike._get_el_version())

    @mock.patch.object(
        cc_crowdstrike.util, "get_linux_distro", return_value=("redhat", "", "")
    )
    def test_returns_none_when_version_empty(self, m_distro):
        self.assertIsNone(cc_crowdstrike._get_el_version())

    @mock.patch.object(
        cc_crowdstrike.util,
        "get_linux_distro",
        return_value=("weird", "rolling", ""),
    )
    def test_returns_none_when_major_not_numeric(self, m_distro):
        self.assertIsNone(cc_crowdstrike._get_el_version())

    @mock.patch.object(
        cc_crowdstrike.util, "get_linux_distro", side_effect=OSError("boom")
    )
    def test_returns_none_on_lookup_error(self, m_distro):
        self.assertIsNone(cc_crowdstrike._get_el_version())


class ResolveElVersionInUrlTest(testtools.TestCase):
    URL_TMPL = "https://x/falcon-sensor-7.36.0-18909.el{el_version}.x86_64.rpm"

    def test_returns_url_unchanged_without_placeholder(self):
        url = "https://x/falcon-sensor_7.36.0-18909_amd64.deb"
        self.assertEqual(url, cc_crowdstrike._resolve_el_version_in_url(url))

    @mock.patch.object(cc_crowdstrike, "_get_el_version", return_value="9")
    def test_substitutes_detected_version(self, m_ver):
        self.assertEqual(
            "https://x/falcon-sensor-7.36.0-18909.el9.x86_64.rpm",
            cc_crowdstrike._resolve_el_version_in_url(self.URL_TMPL),
        )

    @mock.patch.object(cc_crowdstrike, "_get_el_version", return_value=None)
    def test_returns_none_when_version_unresolvable(self, m_ver):
        self.assertIsNone(cc_crowdstrike._resolve_el_version_in_url(self.URL_TMPL))


class IsFalconInstalledTest(testtools.TestCase):
    @mock.patch.object(cc_crowdstrike.os.path, "exists", return_value=True)
    def test_returns_true_when_marker_present(self, m_exists):
        self.assertTrue(cc_crowdstrike._is_falcon_installed())
        m_exists.assert_called_once_with(cc_crowdstrike.FALCON_INSTALLED_MARKER)

    @mock.patch.object(cc_crowdstrike.os.path, "exists", return_value=False)
    def test_returns_false_when_marker_absent(self, m_exists):
        self.assertFalse(cc_crowdstrike._is_falcon_installed())


class ConfigureFalconTest(testtools.TestCase):
    FALCONCTL = cc_crowdstrike.FALCONCTL_PATH

    @mock.patch.object(cc_crowdstrike.os.path, "exists", return_value=False)
    def test_raises_when_falconctl_missing(self, m_exists):
        self.assertRaises(RuntimeError, cc_crowdstrike._configure_falcon, "CID-12")

    @mock.patch.object(cc_crowdstrike.subp, "subp")
    @mock.patch.object(cc_crowdstrike.os.path, "exists", return_value=True)
    def test_sets_cid_only(self, m_exists, m_subp):
        cc_crowdstrike._configure_falcon("CID-12")
        m_subp.assert_called_once_with(
            [self.FALCONCTL, "-s", "--cid=CID-12"], capture=True
        )

    @mock.patch.object(cc_crowdstrike.subp, "subp")
    @mock.patch.object(cc_crowdstrike.os.path, "exists", return_value=True)
    def test_sets_cid_and_token_in_single_call(self, m_exists, m_subp):
        cc_crowdstrike._configure_falcon("CID-12", provisioning_token="TOK-99")
        m_subp.assert_called_once_with(
            [self.FALCONCTL, "-s", "--cid=CID-12", "--provisioning-token=TOK-99"],
            capture=True,
        )

    @mock.patch.object(cc_crowdstrike.subp, "subp")
    @mock.patch.object(cc_crowdstrike.os.path, "exists", return_value=True)
    def test_sets_tags_in_separate_call(self, m_exists, m_subp):
        cc_crowdstrike._configure_falcon("CID-12", tags="Unmanaged_External")
        self.assertEqual(
            [
                mock.call([self.FALCONCTL, "-s", "--cid=CID-12"], capture=True),
                mock.call(
                    [self.FALCONCTL, "-s", "--tags=Unmanaged_External"],
                    capture=True,
                ),
            ],
            m_subp.call_args_list,
        )

    @mock.patch.object(cc_crowdstrike.subp, "subp")
    @mock.patch.object(cc_crowdstrike.os.path, "exists", return_value=True)
    def test_sets_all_options(self, m_exists, m_subp):
        cc_crowdstrike._configure_falcon(
            "CID-12", provisioning_token="TOK-99", tags="Unmanaged_External"
        )
        self.assertEqual(
            [
                mock.call(
                    [
                        self.FALCONCTL,
                        "-s",
                        "--cid=CID-12",
                        "--provisioning-token=TOK-99",
                    ],
                    capture=True,
                ),
                mock.call(
                    [self.FALCONCTL, "-s", "--tags=Unmanaged_External"],
                    capture=True,
                ),
            ],
            m_subp.call_args_list,
        )

    @mock.patch.object(
        cc_crowdstrike.subp,
        "subp",
        side_effect=cc_crowdstrike.subp.ProcessExecutionError(),
    )
    @mock.patch.object(cc_crowdstrike.os.path, "exists", return_value=True)
    def test_raises_runtimeerror_on_subp_failure(self, m_exists, m_subp):
        self.assertRaises(RuntimeError, cc_crowdstrike._configure_falcon, "CID-12")
