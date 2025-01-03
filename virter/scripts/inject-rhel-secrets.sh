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

ln -snf /run/secrets/etc-pki-entitlement /etc/pki/entitlement-host
ln -snf /run/secrets/rhsm /etc/rhsm-host

if command -v dnf > /dev/null; then
	sed -i 's/^enabled=0/enabled=1/' /etc/dnf/plugins/subscription-manager.conf
else
	sed -i 's/^enabled=0/enabled=1/' /etc/yum/pluginconf.d/subscription-manager.conf
fi

if [ "$dist_major_version" -eq 7 ]; then
  # RHEL 7 has python3 in the SCL repos
  yum-config-manager --enable rhel-server-rhscl-7-rpms
fi

if [ "$dist_major_version" -eq 10 ]; then
  # gdisk package is no longer available from upstream RHEL 10, use EPEL instead
  dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-10.noarch.rpm
  # EPEL does not yet support minor versions
  sed -e 's/${releasever_minor:+.$releasever_minor}//' -i /etc/yum.repos.d/epel.repo
fi