#!/bin/bash

# Install the packages provided as arguments.

die() { >&2 printf "\nError: %s\n" "$*"; exit 1; }

if command -v yum > /dev/null; then
	no_initramfs=1 yum install -y "$@" || die "Failed to install"
elif command -v apt-get > /dev/null; then
	DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends "$@" || die "Failed to install"
else
	die "Unknown package manager"
fi
