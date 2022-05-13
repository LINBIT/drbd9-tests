#!/bin/bash

# Download the given DRBD version.

set -o pipefail

die() { >&2 printf "\nError: %s\n" "$*"; exit 1; }
log() { >&2 printf "%s\n" "$*"; }

drbd_version="$1"

download_dir="/opt/package-download"

mkdir -p "$download_dir"
cd "$download_dir"

if command -v yum > /dev/null; then
	available=$(yum list available --quiet --showduplicates \
		--disablerepo="*" --enablerepo="drbd" \
		"kmod-drbd-${drbd_version}_*" \
			| grep '^kmod-drbd' \
			| awk '{print "kmod-drbd-" $2}') || die "Failed to list kmods"

	log "Available drbd packages for version $drbd_version:"
	log "$available" | tr ' ' '\n'

	best=$(lbdisttool.py --kmods $available) || die "Failed to choose kmod"
	log "Best kmod: $best"

	yum install -y --downloadonly --downloaddir . "$best" || die "Failed to download package"

	# Provide a link to make the package easy to find
	ln -s "$(find | grep -F "kmod-drbd-${drbd_version}_")" "$drbd_version.rpm" \
		|| die "Failed to link package"
elif command -v apt-get > /dev/null; then
	apt download "drbd-module-$(uname -r)=${drbd_version}-*" || die "Failed to download package"

	# Provide a link to make the package easy to find
	ln -s "$(find | grep -F drbd-module | grep -F "${drbd_version}")" "$drbd_version.deb" \
		|| die "Failed to link package"
else
	die "Unknown package manager"
fi
