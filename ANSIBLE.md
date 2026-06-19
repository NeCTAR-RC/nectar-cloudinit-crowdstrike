# Ansible Integration Guide

This guide shows how to integrate the CrowdStrike cloud-init module into your Ansible-based image building pipeline.

## Quick Start

### Copy Module to Your Ansible Project

```bash
# In your ansible project
mkdir -p files/
cp -r /path/to/nectar-cloudinit-crowdstrike files/
```

### Include in Your Playbook

```yaml
- name: Build Nectar base image
  hosts: image_build_host
  become: true

  tasks:
    # ... your other image building tasks ...

    - name: Install CrowdStrike cloud-init module
      include_tasks: files/nectar-cloudinit-crowdstrike/ansible-tasks.yml

    # ... more tasks ...
```

## Installation Methods

### Method 1: Install from Local Directory (Recommended for Airgapped Builds)

```yaml
- name: Install from local directory
  ansible.builtin.pip:
    name: "file://{{ playbook_dir }}/files/nectar-cloudinit-crowdstrike"
    state: present
    executable: pip3
  become: true
```

**Pros**: Works offline, version controlled with your playbook
**Cons**: Need to keep local copy up to date

### Method 2: Install from Git Repository

```yaml
- name: Install from git
  ansible.builtin.pip:
    name: "git+https://github.com/NectarCloud/nectar-cloudinit-crowdstrike.git@v1.0.0"
    state: present
    executable: pip3
  become: true
```

**Pros**: Always get latest version, easy updates
**Cons**: Requires internet access during build

### Method 3: Install from Internal PyPI Server

```yaml
- name: Install from internal PyPI
  ansible.builtin.pip:
    name: nectar-cloudinit-crowdstrike
    version: "1.0.0"
    state: present
    executable: pip3
    extra_args: "--index-url https://pypi.internal.example.com/simple"
  become: true
```

**Pros**: Centralized package management, version pinning
**Cons**: Requires internal PyPI setup

## Complete Example Playbook

```yaml
---
- name: Build Nectar base image with CrowdStrike module
  hosts: localhost
  become: true

  vars:
    base_image_name: "nectar-ubuntu-22.04"
    crowdstrike_module_path: "{{ playbook_dir }}/files/nectar-cloudinit-crowdstrike"

  tasks:
    - name: Update package cache
      ansible.builtin.apt:
        update_cache: true
        cache_valid_time: 3600
      when: ansible_os_family == "Debian"

    - name: Install base packages
      ansible.builtin.package:
        name:
          - cloud-init
          - python3-pip
        state: present

    - name: Install CrowdStrike cloud-init module
      ansible.builtin.pip:
        name: "file://{{ crowdstrike_module_path }}"
        state: present
        executable: pip3

    - name: Verify installation
      block:
        - name: Check module file
          ansible.builtin.stat:
            path: /usr/lib/python3/dist-packages/cloudinit/config/cc_crowdstrike.py
          register: module_check

        - name: Check config file
          ansible.builtin.stat:
            path: /etc/cloud/cloud.cfg.d/99_crowdstrike.cfg
          register: config_check

        - name: Assert files exist
          ansible.builtin.assert:
            that:
              - module_check.stat.exists
              - config_check.stat.exists
            fail_msg: "CrowdStrike module installation failed"

        - name: Test import
          ansible.builtin.command: python3 -c "from cloudinit.config import cc_crowdstrike"
          changed_when: false

    - name: Clean cloud-init state for image
      ansible.builtin.command: cloud-init clean --logs --seed
      when: clean_for_image | default(true)

    - name: Create image marker file
      ansible.builtin.copy:
        content: |
          Image: {{ base_image_name }}
          Build date: {{ ansible_date_time.iso8601 }}
          CrowdStrike module: installed
        dest: /etc/nectar-image-info
        mode: '0644'
```

## Integration with Packer

If you're using Packer with Ansible provisioner:

```hcl
# packer.pkr.hcl
source "openstack" "nectar_base" {
  # ... your OpenStack config ...
}

build {
  sources = ["source.openstack.nectar_base"]

  provisioner "ansible" {
    playbook_file = "playbooks/build-image.yml"
    extra_arguments = [
      "--extra-vars",
      "crowdstrike_module_path=${path.root}/files/nectar-cloudinit-crowdstrike"
    ]
  }
}
```

## Handling Multiple Distributions

```yaml
- name: Install CrowdStrike module on multiple distros
  block:
    - name: Set Python site-packages path for Debian/Ubuntu
      ansible.builtin.set_fact:
        python_site_packages: "/usr/lib/python3/dist-packages"
      when: ansible_os_family == "Debian"

    - name: Set Python site-packages path for RHEL/CentOS
      ansible.builtin.set_fact:
        python_site_packages: "/usr/lib/python3.{{ ansible_python.version.minor }}/site-packages"
      when: ansible_os_family == "RedHat"

    - name: Install pip
      ansible.builtin.package:
        name: python3-pip
        state: present

    - name: Install CrowdStrike module
      ansible.builtin.pip:
        name: "file://{{ crowdstrike_module_path }}"
        state: present
        executable: pip3

    - name: Verify module at distro-specific path
      ansible.builtin.stat:
        path: "{{ python_site_packages }}/cloudinit/config/cc_crowdstrike.py"
      register: module_stat
      failed_when: not module_stat.stat.exists
```

## Version Pinning

Create a `requirements.txt` for your image builds:

```txt
# files/python-requirements.txt
nectar-cloudinit-crowdstrike==1.0.0
```

Then in your playbook:

```yaml
- name: Install Python packages from requirements
  ansible.builtin.pip:
    requirements: "{{ playbook_dir }}/files/python-requirements.txt"
    executable: pip3
  become: true
```

## Testing After Installation

```yaml
- name: Run CrowdStrike module tests
  block:
    - name: Test module can be imported
      ansible.builtin.command: |
        python3 -c "
        from cloudinit.config import cc_crowdstrike
        assert cc_crowdstrike.meta['id'] == 'cc_crowdstrike'
        assert 'handle' in dir(cc_crowdstrike)
        print('Module tests passed')
        "
      register: module_test
      changed_when: false

    - name: Test module with cloud-init
      ansible.builtin.command: cloud-init single --name crowdstrike --frequency always
      register: cloudinit_test
      changed_when: false
      # This will fail if no vendor_data, but that's expected
      failed_when: false

    - name: Check test results
      ansible.builtin.debug:
        msg: "Module loaded by cloud-init: {{ 'crowdstrike' in cloudinit_test.stderr }}"
```

## Rollback Strategy

```yaml
- name: Install CrowdStrike module with rollback
  block:
    - name: Backup existing module (if exists)
      ansible.builtin.copy:
        src: /usr/lib/python3/dist-packages/cloudinit/config/cc_crowdstrike.py
        dest: /tmp/cc_crowdstrike.py.backup
        remote_src: true
      failed_when: false

    - name: Install new version
      ansible.builtin.pip:
        name: "file://{{ crowdstrike_module_path }}"
        state: present
        executable: pip3

    - name: Verify installation
      ansible.builtin.command: python3 -c "from cloudinit.config import cc_crowdstrike"
      changed_when: false

  rescue:
    - name: Restore backup on failure
      ansible.builtin.copy:
        src: /tmp/cc_crowdstrike.py.backup
        dest: /usr/lib/python3/dist-packages/cloudinit/config/cc_crowdstrike.py
        remote_src: true
      when: backup.stat.exists | default(false)

    - name: Fail the playbook
      ansible.builtin.fail:
        msg: "CrowdStrike module installation failed and was rolled back"
```

## Environment-Specific Installation

```yaml
- name: Install CrowdStrike module (environment-specific)
  vars:
    module_versions:
      test: "file://{{ playbook_dir }}/files/nectar-cloudinit-crowdstrike"
      staging: "git+https://github.com/NectarCloud/nectar-cloudinit-crowdstrike.git@develop"
      production: "git+https://github.com/NectarCloud/nectar-cloudinit-crowdstrike.git@v1.0.0"

  ansible.builtin.pip:
    name: "{{ module_versions[environment] }}"
    state: present
    executable: pip3
  become: true
```

## Troubleshooting

### Module Not Found After Installation

```yaml
- name: Debug module installation
  ansible.builtin.shell: |
    echo "=== Pip list ==="
    pip3 list | grep crowdstrike
    echo ""
    echo "=== Module location ==="
    python3 -c "import cloudinit.config; print(cloudinit.config.__file__)"
    echo ""
    echo "=== Directory contents ==="
    ls -la /usr/lib/python3/dist-packages/cloudinit/config/cc_crowdstrike.py
  register: debug_output

- name: Display debug info
  ansible.builtin.debug:
    var: debug_output.stdout_lines
```

### Permission Issues

```yaml
- name: Fix permissions if needed
  ansible.builtin.file:
    path: "{{ item }}"
    mode: '0644'
    owner: root
    group: root
  loop:
    - /usr/lib/python3/dist-packages/cloudinit/config/cc_crowdstrike.py
    - /etc/cloud/cloud.cfg.d/99_crowdstrike.cfg
```

## CI/CD Integration

### GitLab CI Example

```yaml
# .gitlab-ci.yml
build_image:
  stage: build
  script:
    - ansible-playbook -i inventory playbooks/build-image.yml
      --extra-vars "crowdstrike_module_path=$CI_PROJECT_DIR/nectar-cloudinit-crowdstrike"
  artifacts:
    paths:
      - builds/*.qcow2
```

### Jenkins Pipeline Example

```groovy
// Jenkinsfile
pipeline {
    agent any

    stages {
        stage('Build Image') {
            steps {
                ansiblePlaybook(
                    playbook: 'playbooks/build-image.yml',
                    inventory: 'inventory',
                    extraVars: [
                        crowdstrike_module_path: "${WORKSPACE}/nectar-cloudinit-crowdstrike"
                    ]
                )
            }
        }
    }
}
```

## Best Practices

1. **Version Control**: Keep the module source in your Ansible repository
2. **Version Pinning**: Use specific versions in production
3. **Verification**: Always verify installation with tests
4. **Idempotency**: Use `state: present` for pip installs
5. **Cleanup**: Clean cloud-init state before imaging with `cloud-init clean`
6. **Documentation**: Document which module version is in each image
7. **Testing**: Test module in dev environment before production images

## Related Files

- [ansible-tasks.yml](ansible-tasks.yml) - Simple task include
- [ansible-example.yml](ansible-example.yml) - Basic example
- [ansible-role-example.yml](ansible-role-example.yml) - Complete role example
