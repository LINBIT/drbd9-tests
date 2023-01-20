#!/bin/bash

# Download the given DRBD version.

set -o pipefail

die() { >&2 printf "\nError: %s\n" "$*"; exit 1; }
log() { >&2 printf "%s\n" "$*"; }

drbd_version="$1"

download_dir="/opt/package-download"

mkdir -p "$download_dir"
cd "$download_dir"

find_pattern() {
	find . -maxdepth 1 -name "$1" -exec basename \{\} \; | sort
}

if command -v yum > /dev/null; then
	available=$(yum list available --quiet --showduplicates \
		"kmod-drbd-${drbd_version}_*" \
			| grep '^kmod-drbd' \
			| awk '{print "kmod-drbd-" $2}') || die "Failed to list kmods"

	log "Available drbd packages for version $drbd_version:"
	log "$available" | tr ' ' '\n'

	best=$(lbdisttool.py --kmods $available) || die "Failed to choose kmod"
	log "Best kmod: $best"

	pkgs_before=$(find_pattern '*.rpm')
	yum install -y --downloadonly --downloaddir . "$best" || die "Failed to download package"
	pkgs_after=$(find_pattern '*.rpm')

	new_pkg=$(comm -13 <(echo "$pkgs_before") <(echo "$pkgs_after") | grep '^kmod-drbd' | head -n1)
	# Provide a mapping file to make the package easy to find
	printf "%s:%s\n" "$drbd_version" "$new_pkg" \
		>> pkgs.map
elif command -v apt-get > /dev/null; then
	pkgs_before=$(find_pattern '*.deb')
	apt download "drbd-module-$(uname -r)=${drbd_version}-*" || die "Failed to download package"
	pkgs_after=$(find_pattern '*.deb')

	new_pkg=$(comm -13 <(echo "$pkgs_before") <(echo "$pkgs_after") | grep '^drbd-module' | head -n1)

	# Provide a mapping file to make the package easy to find
	printf "%s:%s\n" "$drbd_version" "$new_pkg" \
		>> pkgs.map
else
	die "Unknown package manager"
fi
