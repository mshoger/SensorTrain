# Raspberry Pi 5 / RHEL / MicroShift platform notes

SensorTrain v1.0 runs on a Raspberry Pi 5 using genuine Red Hat Enterprise Linux 9.8 userspace and the Red Hat build of MicroShift 4.22, with a custom Raspberry Pi kernel required for hardware support.

This is a working project platform, not a Red Hat-supported Raspberry Pi 5 deployment target.

## Validated software

- RHEL 9.8 userspace
- MicroShift 4.22.7
- Kubernetes 1.35.6
- custom Raspberry Pi Linux 6.18.46-microshift+
- 4 KiB page size
- SELinux enforcing
- cgroups v2 with memory controller enabled

Validated MicroShift build:

```text
4.22.7-202607240848.p0.g47f0f6a.assembly.4.22.7.el9.aarch64
```

## Required repositories

The accepted installation used these RHEL repositories:

```text
rhel-9-for-aarch64-baseos-eus-rpms
rhel-9-for-aarch64-appstream-eus-rpms
rhocp-4.22-for-rhel-9-aarch64-rpms
fast-datapath-for-rhel-9-aarch64-rpms
```

The host package configuration excludes `kernel*` packages so a stock RHEL kernel update does not replace the custom Raspberry Pi kernel.

## Kernel requirements

The custom kernel includes support needed by both Raspberry Pi hardware and MicroShift networking/storage. Key requirements include:

- 4 KiB pages
- Broadcom Raspberry Pi PCIe controller
- built-in NVMe support
- device mapper
- XFS
- Open vSwitch
- Geneve
- SELinux
- audit support

The accepted configuration also uses an empty built-in LSM list and selects SELinux from the kernel command line with `lsm=selinux`.

## Boot configuration

The Raspberry Pi boot filesystem uses:

```text
auto_initramfs=1
kernel=kernel-microshift.img
dtparam=pciex1
```

EEPROM boot order:

```text
BOOT_ORDER=0xf461
```

The accepted kernel command line is conceptually:

```text
console=serial0,115200 console=tty1 root=/dev/mapper/rhel-root rootfstype=xfs rw rootwait rd.lvm.lv=rhel/root lsm=selinux selinux=1
```

Machine-specific details should be checked before reusing this verbatim on another installation.

## Memory cgroup correction

The Raspberry Pi device tree used during development included `cgroup_disable=memory`, which prevents MicroShift from operating correctly. That argument was removed from the Raspberry Pi kernel source device-tree configuration and the DTBs were rebuilt.

After correction, cgroups v2 exposes the memory controller as required.

## NVMe and LVM layout

The accepted 128 GB NVMe device uses approximately:

- 1 GB FAT boot partition mounted at `/boot/firmware`
- remaining space as LVM physical storage
- VG `rhel`
- root LV approximately 48 GB XFS
- approximately 70 GB free in the VG for MicroShift/LVMS

MicroShift LVMS successfully provisions persistent volumes from the remaining volume-group capacity using the default `topolvm-provisioner` StorageClass.

## MicroShift platform health

At v1.0 acceptance:

- node `sensortrain` was Ready
- OVN networking healthy
- DNS healthy
- ingress healthy
- service CA healthy
- CSI healthy
- LVMS healthy
- Geneve and Open vSwitch functional
- no failed host systemd units remained

## Firewall

The accepted installation trusts the MicroShift pod/service networking ranges needed by this system, including the configured cluster network and `169.254.169.1` endpoint used by MicroShift components.

Exact firewall rules should be reviewed against the cluster networking configuration rather than copied blindly to another host.

## Greenboot

RHEL greenboot health and rollback automation was disabled on the accepted Raspberry Pi installation because its assumptions about the standard supported boot layout do not match the custom Raspberry Pi boot arrangement.

This removed otherwise spurious failed units after boot.

## CRI-O pull secret

The MicroShift installation uses an OpenShift pull secret for registry authentication. It is stored locally on the host and must never be committed to this repository.

Do not commit any of the following:

- OpenShift pull secrets
- kubeconfig files
- Red Hat subscription identity/certificates
- Wi-Fi credentials
- GitHub tokens
- private SSH keys

## Clock-related startup note

During bring-up, `rhcd` could report an early certificate failure when the Raspberry Pi booted with an incorrect pre-network clock. Once time was corrected, the condition cleared. If it recurs, verify host time synchronization before treating it as a certificate/configuration defect.

## Support statement

RHEL userspace and the MicroShift packages in this project are genuine Red Hat software. The Raspberry Pi 5 hardware, custom kernel, boot chain, and resulting platform combination are outside the normal Red Hat supported hardware matrix. Treat this repository as a project build record and reproducibility guide, not as an official supported installation procedure.
