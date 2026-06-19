"""Setup configuration for nectar-cloudinit-crowdstrike package.

This package provides a cloud-init module for automatic installation of
CrowdStrike Falcon sensor on Nectar Research Cloud instances.
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="nectar-cloudinit-crowdstrike",
    version="1.0.0",
    author="Nectar Research Cloud",
    description="Cloud-init module for CrowdStrike Falcon sensor deployment",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/NectarCloud/nectar-cloudinit-crowdstrike",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: System Administrators",
        "Topic :: System :: Installation/Setup",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: POSIX :: Linux",
    ],
    python_requires=">=3.6",
    install_requires=[
        # No additional dependencies - uses cloud-init's built-in libraries
    ],
    data_files=[
        # Install the module into cloud-init's config directory
        (
            "/usr/lib/python3/dist-packages/cloudinit/config",
            ["nectar_crowdstrike/cc_crowdstrike.py"],
        ),
        # Install the cloud-init configuration snippet
        (
            "/etc/cloud/cloud.cfg.d",
            ["config/99_crowdstrike.cfg"],
        ),
    ],
    include_package_data=True,
    zip_safe=False,
    keywords="cloud-init crowdstrike falcon security openstack nectar",
)
