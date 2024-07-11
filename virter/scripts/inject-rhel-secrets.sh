#!/bin/bash

die() {
	echo "$1" >&2
	exit 1
}

source /etc/os-release
if [ "$ID" != "rhel" ]; then
	die "This script is only for RHEL. $ID is not supported."
fi

dist_major_version=$(echo $VERSION_ID | cut -d. -f1)
if [ -z "$dist_major_version" ]; then
	die "Could not determine major version from /etc/os-release."
fi

entitlement_key=$(ls -1 /run/secrets/etc-pki-entitlement/*-key.pem | head -n 1)
entitlement_cert=$(ls -1 /run/secrets/etc-pki-entitlement/*.pem | grep -v '\-key' | head -n 1)
if [ -z "$entitlement_key" ] || [ -z "$entitlement_cert" ]; then
	die "Entitlement key or cert not found."
fi

if command -v dnf > /dev/null; then
	# Has DNF command, so this is RHEL8+ like
	cat > /run/secrets/rhel.repo <<EOF
[rhel-baseos]
name = Red Hat Enterprise Linux \$releasever for x86_64 - BaseOS (RPMs)
baseurl = https://cdn.redhat.com/content/dist/rhel$dist_major_version/\$releasever/x86_64/baseos/os
enabled = 1
gpgcheck = 1
gpgkey = file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release
sslverify = 1
sslcacert = /run/secrets/rhsm/ca/redhat-uep.pem
sslclientkey = $entitlement_key
sslclientcert = $entitlement_cert
metadata_expire = 86400
enabled_metadata = 1
sslverifystatus = 1

[rhel-baseos-eus]
name = Red Hat Enterprise Linux \$releasever for x86_64 - BaseOS - Extended Update Support (RPMs)
baseurl = https://cdn.redhat.com/content/eus/rhel$dist_major_version/\$releasever/x86_64/baseos/os
enabled = 1
gpgcheck = 1
gpgkey = file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release
sslverify = 1
sslcacert = /run/secrets/rhsm/ca/redhat-uep.pem
sslclientkey = $entitlement_key
sslclientcert = $entitlement_cert
metadata_expire = 86400
enabled_metadata = 1
sslverifystatus = 1
skip_if_unavailable = True
priority = 100 # weaker priority than the "normal" baseos repo so that userspace components are not taken from EUS

[rhel-appstream]
name = Red Hat Enterprise Linux \$releasever for x86_64 - AppStream (RPMs)
baseurl = https://cdn.redhat.com/content/dist/rhel$dist_major_version/\$releasever/x86_64/appstream/os
enabled = 1
gpgcheck = 1
gpgkey = file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release
sslverify = 1
sslcacert = /run/secrets/rhsm/ca/redhat-uep.pem
sslclientkey = $entitlement_key
sslclientcert = $entitlement_cert
metadata_expire = 86400
enabled_metadata = 1
sslverifystatus = 1
EOF
else
	# Is RHEL7, renamed the repos so they follow the same scheme as RHEL8+
	cat > /run/secrets/rhel.repo <<EOF
[rhel-baseos]
name = Red Hat Enterprise Linux \$releasever Server (RPMs)
baseurl = https://cdn.redhat.com/content/dist/rhel/server/7/\$releasever/\$basearch/os
enabled = 1
gpgcheck = 1
gpgkey = file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release
sslverify = 1
sslcacert = /run/secrets/rhsm/ca/redhat-uep.pem
sslclientkey = $entitlement_key
sslclientcert = $entitlement_cert
metadata_expire = 86400
enabled_metadata = 1
sslverifystatus = 1

[rhel-appstream]
name = Red Hat Enterprise Linux \$releasever Server - Optional (RPMs)
baseurl = https://cdn.redhat.com/content/dist/rhel/server/7/\$releasever/\$basearch/optional/os
enabled = 1
gpgcheck = 1
gpgkey = file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release
sslverify = 1
sslcacert = /run/secrets/rhsm/ca/redhat-uep.pem
sslclientkey = $entitlement_key
sslclientcert = $entitlement_cert
metadata_expire = 86400
enabled_metadata = 1
sslverifystatus = 1

[rhel-baseos-eus]
name = Red Hat Enterprise Linux 7 Server - Extended Life Cycle Support (RPMs)
baseurl = https://cdn.redhat.com/content/els/rhel/server/7/\$releasever/\$basearch/os
enabled = 1
gpgcheck = 1
gpgkey = file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release
sslverify = 1
sslcacert = /run/secrets/rhsm/ca/redhat-uep.pem
sslclientkey = $entitlement_key
sslclientcert = $entitlement_cert
metadata_expire = 86400
enabled_metadata = 1
sslverifystatus = 1
skip_if_unavailable = True
priority = 100 # weaker priority than the "normal" baseos repo so that userspace components are not taken from EUS

[rhel-server-rhscl-7-rpms]
metadata_expire = 86400
enabled_metadata = 0
sslclientcert = $entitlement_cert
baseurl = https://cdn.redhat.com/content/dist/rhel/server/7/\$releasever/\$basearch/rhscl/1/os
ui_repoid_vars = releasever basearch
sslverify = 1
name = Red Hat Software Collections RPMs for Red Hat Enterprise Linux 7 Server
sslclientkey = $entitlement_key
gpgkey = file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release,file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release
enabled = 1
sslcacert = /run/secrets/rhsm/ca/redhat-uep.pem
gpgcheck = 1
EOF
fi
# The repo file is created in /run (which is a tmpfs) to avoid accidentally
# leaking the secrets with the built base images. Obviously, this means that we
# need to symlink the repo to /etc/... so that dnf finds it.
ln -s /run/secrets/rhel.repo /etc/yum.repos.d/rhel.repo
