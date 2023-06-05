#!/bin/bash

set -o pipefail

die() {
	echo "$1" >&2
	exit 1
}

[ "$#" -ne 2 ] && die "Usage: $0 index base_image"

index="$1"
base_image="$2"

[ -z "$LINBIT_DOCKER_REGISTRY" ] && die "Missing \$LINBIT_DOCKER_REGISTRY"

virter_image_name="build-$base_image"
id=$((100 + $index))

build_base_image() {
	virter image rm "$virter_image_name" || die "could not remove image before build"
	make "base_image_$base_image" BASE_IMAGE_NAME="$virter_image_name" VIRTER_BUILD_ID=$id || die "could not build"
	virter image push "$virter_image_name" "$LINBIT_DOCKER_REGISTRY/vm/drbd9-tests/$base_image:latest" || die "could not push"
	virter image rm "$virter_image_name" || die "could not remove image after build"
}

build_base_image 2>&1 | tee "base-image-build-log/$base_image"
