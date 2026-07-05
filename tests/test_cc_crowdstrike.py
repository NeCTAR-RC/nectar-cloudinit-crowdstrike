"""Unit tests for the cc_crowdstrike cloud-init module."""

import contextlib
import copy
from email.mime.multipart import MIMEMultipart
import json
from unittest import mock

import testtools

from nectar_crowdstrike import cc_crowdstrike


class FakeDistro:
    """Minimal stand-in for a cloud-init distro object."""

    def __init__(self, name="ubuntu", osfamily="debian"):
        self.name = name
        self.osfamily = osfamily

    def get_tmp_exec_path(self):
        return "/tmp"


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


class InstallPackageTest(testtools.TestCase):
    PKG = "/tmp/fake-crowdstrike/falcon-sensor.deb"

    @mock.patch.object(cc_crowdstrike.subp, "subp")
    def test_deb_success_uses_dpkg_only(self, m_subp):
        cc_crowdstrike._install_package(FakeDistro(), self.PKG, "deb")
        m_subp.assert_called_once_with(["dpkg", "-i", self.PKG], capture=False)

    @mock.patch.object(cc_crowdstrike.subp, "subp")
    def test_deb_unmet_dependencies_recovered_by_apt(self, m_subp):
        # dpkg -i exits non-zero on unmet dependencies; apt-get install -f
        # must then run to pull them in and complete the configuration.
        m_subp.side_effect = [cc_crowdstrike.subp.ProcessExecutionError(), None]
        cc_crowdstrike._install_package(FakeDistro(), self.PKG, "deb")
        self.assertEqual(
            [
                mock.call(["dpkg", "-i", self.PKG], capture=False),
                mock.call(["apt-get", "install", "-f", "-y"], capture=False),
            ],
            m_subp.call_args_list,
        )

    @mock.patch.object(cc_crowdstrike.subp, "subp")
    def test_deb_raises_when_apt_recovery_fails(self, m_subp):
        m_subp.side_effect = cc_crowdstrike.subp.ProcessExecutionError()
        self.assertRaises(
            RuntimeError,
            cc_crowdstrike._install_package,
            FakeDistro(),
            self.PKG,
            "deb",
        )

    @mock.patch.object(cc_crowdstrike.subp, "subp")
    def test_rpm_success_uses_rpm_only(self, m_subp):
        cc_crowdstrike._install_package(FakeDistro(), self.PKG, "rpm")
        m_subp.assert_called_once_with(["rpm", "-ivh", self.PKG], capture=False)

    @mock.patch.object(cc_crowdstrike.subp, "subp")
    def test_rpm_failure_recovered_by_yum(self, m_subp):
        m_subp.side_effect = [cc_crowdstrike.subp.ProcessExecutionError(), None]
        cc_crowdstrike._install_package(FakeDistro(), self.PKG, "rpm")
        self.assertEqual(
            [
                mock.call(["rpm", "-ivh", self.PKG], capture=False),
                mock.call(["yum", "localinstall", "-y", self.PKG], capture=False),
            ],
            m_subp.call_args_list,
        )

    @mock.patch.object(cc_crowdstrike.subp, "subp")
    def test_rpm_raises_when_yum_recovery_fails(self, m_subp):
        m_subp.side_effect = cc_crowdstrike.subp.ProcessExecutionError()
        self.assertRaises(
            RuntimeError,
            cc_crowdstrike._install_package,
            FakeDistro(),
            self.PKG,
            "rpm",
        )


# --- Fixtures for the vendor_data2 read path and handle() ------------------

# A realistic vendor_data2.json as delivered by Nova dynamic vendordata: the
# nova-pollinate payload keyed under "crowdstrike" and nested by Nova under the
# "nectar" dynamic-vendordata target name.
NECTAR_DOC = {
    "nectar": {
        "crowdstrike": {
            "cid": "CID-123",
            "installer_url_deb": "https://example.com/falcon.deb",
            "installer_url_rpm": "https://example.com/falcon.el{el_version}.rpm",
            "provisioning_token": "TOK-9",
            "tags": "MRC_VM",
            "enabled": True,
            "fail_if_missing": False,
        }
    }
}


class FakeUrlParams:
    def __init__(self, timeout_seconds=5, num_retries=2):
        self.timeout_seconds = timeout_seconds
        self.num_retries = num_retries


class FakeResponse:
    """Stand-in for url_helper.UrlResponse (only .contents is read)."""

    def __init__(self, contents):
        self.contents = contents


class FakeDataSource:
    """Datasource stand-in exposing only what the module reads."""

    def __init__(self, metadata_address="http://169.254.169.254"):
        self.metadata_address = metadata_address

    def get_url_params(self):
        return FakeUrlParams()

    def get_vendordata2(self):
        # cloud-init returns the *processed* vendordata here: a MIME message,
        # never a dict. Present so any regression that reads this instead of
        # the raw JSON is caught (a MIMEMultipart carries no config).
        return MIMEMultipart()


class FakeCloud:
    def __init__(self, datasource=None, distro=None):
        self.datasource = datasource or FakeDataSource()
        self.distro = distro or FakeDistro()


@contextlib.contextmanager
def _fake_tempdir(*args, **kwargs):
    yield "/tmp/fake-crowdstrike"


class FetchVendorData2Test(testtools.TestCase):
    @mock.patch.object(cc_crowdstrike.url_helper, "readurl")
    def test_fetches_and_parses_json(self, m_readurl):
        m_readurl.return_value = FakeResponse(json.dumps(NECTAR_DOC).encode())
        self.assertEqual(NECTAR_DOC, cc_crowdstrike._fetch_vendordata2(FakeCloud()))

    @mock.patch.object(cc_crowdstrike.url_helper, "readurl")
    def test_builds_url_from_datasource_metadata_address(self, m_readurl):
        m_readurl.return_value = FakeResponse(b"{}")
        cloud = FakeCloud(FakeDataSource(metadata_address="http://10.0.0.1:80"))
        cc_crowdstrike._fetch_vendordata2(cloud)
        self.assertEqual(
            "http://10.0.0.1:80/openstack/latest/vendor_data2.json",
            m_readurl.call_args.kwargs["url"],
        )

    @mock.patch.object(cc_crowdstrike.url_helper, "readurl")
    def test_falls_back_to_default_url_when_address_absent(self, m_readurl):
        m_readurl.return_value = FakeResponse(b"{}")
        cloud = FakeCloud(FakeDataSource(metadata_address=None))
        cc_crowdstrike._fetch_vendordata2(cloud)
        self.assertEqual(
            cc_crowdstrike.DEFAULT_METADATA_URL + "/openstack/latest/vendor_data2.json",
            m_readurl.call_args.kwargs["url"],
        )

    @mock.patch.object(
        cc_crowdstrike.url_helper, "readurl", side_effect=Exception("boom")
    )
    def test_returns_empty_on_fetch_error(self, m_readurl):
        self.assertEqual({}, cc_crowdstrike._fetch_vendordata2(FakeCloud()))

    @mock.patch.object(cc_crowdstrike.url_helper, "readurl")
    def test_returns_empty_on_invalid_json(self, m_readurl):
        m_readurl.return_value = FakeResponse(b"not json")
        self.assertEqual({}, cc_crowdstrike._fetch_vendordata2(FakeCloud()))

    @mock.patch.object(cc_crowdstrike.url_helper, "readurl")
    def test_returns_empty_on_non_object_json(self, m_readurl):
        # A JSON array is valid JSON but load_json enforces a dict root.
        m_readurl.return_value = FakeResponse(b"[1, 2, 3]")
        self.assertEqual({}, cc_crowdstrike._fetch_vendordata2(FakeCloud()))


class GetVendorDataConfigTest(testtools.TestCase):
    @mock.patch.object(cc_crowdstrike, "_fetch_vendordata2")
    def test_extracts_nested_nectar_crowdstrike(self, m_fetch):
        m_fetch.return_value = copy.deepcopy(NECTAR_DOC)
        self.assertEqual(
            NECTAR_DOC["nectar"]["crowdstrike"],
            cc_crowdstrike._get_vendor_data_config(FakeCloud()),
        )

    @mock.patch.object(cc_crowdstrike, "_fetch_vendordata2")
    def test_extracts_top_level_crowdstrike(self, m_fetch):
        m_fetch.return_value = {"crowdstrike": {"cid": "X"}}
        self.assertEqual(
            {"cid": "X"},
            cc_crowdstrike._get_vendor_data_config(FakeCloud()),
        )

    @mock.patch.object(cc_crowdstrike, "_fetch_vendordata2")
    def test_returns_empty_when_crowdstrike_absent(self, m_fetch):
        m_fetch.return_value = {"nectar": {"something_else": 1}}
        self.assertEqual({}, cc_crowdstrike._get_vendor_data_config(FakeCloud()))

    @mock.patch.object(cc_crowdstrike, "_fetch_vendordata2")
    def test_returns_empty_when_document_empty(self, m_fetch):
        m_fetch.return_value = {}
        self.assertEqual({}, cc_crowdstrike._get_vendor_data_config(FakeCloud()))

    @mock.patch.object(cc_crowdstrike.url_helper, "readurl")
    def test_config_found_although_get_vendordata2_returns_mime(self, m_readurl):
        # The regression this whole change fixes: the datasource's processed
        # accessor yields a MIME message (not a dict), yet the config is still
        # found because we read the raw metadata document instead.
        m_readurl.return_value = FakeResponse(json.dumps(NECTAR_DOC).encode())
        cloud = FakeCloud()
        self.assertNotIsInstance(cloud.datasource.get_vendordata2(), dict)
        self.assertEqual(
            NECTAR_DOC["nectar"]["crowdstrike"],
            cc_crowdstrike._get_vendor_data_config(cloud),
        )


class HandleTest(testtools.TestCase):
    """End-to-end regression: vendor_data2 document -> install path."""

    def _run_handle(self, doc, distro=None):
        cloud = FakeCloud(distro=distro)
        with (
            mock.patch.object(cc_crowdstrike, "_fetch_vendordata2", return_value=doc),
            mock.patch.object(
                cc_crowdstrike, "_is_falcon_installed", return_value=False
            ),
            mock.patch.object(cc_crowdstrike, "_download_installer") as m_dl,
            mock.patch.object(cc_crowdstrike, "_install_package") as m_inst,
            mock.patch.object(cc_crowdstrike, "_configure_falcon") as m_conf,
            mock.patch.object(cc_crowdstrike, "_start_falcon_service") as m_start,
            mock.patch.object(cc_crowdstrike.temp_utils, "tempdir", _fake_tempdir),
        ):
            cc_crowdstrike.handle("crowdstrike", {}, cloud, [])
        return {
            "download": m_dl,
            "install": m_inst,
            "configure": m_conf,
            "start": m_start,
        }

    def test_installs_and_configures_from_vendordata2(self):
        mocks = self._run_handle(copy.deepcopy(NECTAR_DOC))
        # cid, provisioning token and tags all flow through from the document.
        mocks["configure"].assert_called_once_with("CID-123", "TOK-9", "MRC_VM")
        mocks["start"].assert_called_once()
        # A debian FakeDistro selects the .deb installer URL.
        self.assertEqual(
            "https://example.com/falcon.deb",
            mocks["download"].call_args.args[0],
        )

    @mock.patch.object(cc_crowdstrike, "_get_el_version", return_value="9")
    def test_resolves_el_version_for_rpm_distro(self, m_ver):
        mocks = self._run_handle(
            copy.deepcopy(NECTAR_DOC),
            distro=FakeDistro(name="rocky", osfamily="redhat"),
        )
        self.assertEqual(
            "https://example.com/falcon.el9.rpm",
            mocks["download"].call_args.args[0],
        )

    def test_skips_when_no_config(self):
        mocks = self._run_handle({})
        mocks["download"].assert_not_called()
        mocks["configure"].assert_not_called()
        mocks["start"].assert_not_called()

    def test_skips_when_disabled(self):
        doc = copy.deepcopy(NECTAR_DOC)
        doc["nectar"]["crowdstrike"]["enabled"] = False
        mocks = self._run_handle(doc)
        mocks["configure"].assert_not_called()
        mocks["start"].assert_not_called()
