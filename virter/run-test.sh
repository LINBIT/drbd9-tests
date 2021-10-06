#!/bin/bash

set -e

die() {
	echo "$1" >&2
	exit 1
}

[ -z "$DRBD_VERSION" ] && die "Missing \$DRBD_VERSION"
[ -z "$DRBD_UTILS_VERSION" ] && die "Missing \$DRBD_UTILS_VERSION"
[ -z "$DRBD9_TESTS_VERSION" ] && die "Missing \$DRBD9_TESTS_VERSION"

for BASE_IMAGE in $(rq -t < drbd-test-bundle/virter/vms.toml | jq -r '.vms[] | .base_image'); do
	virter image pull $BASE_IMAGE $LINBIT_DOCKER_REGISTRY/vm/drbd9-tests/$BASE_IMAGE:latest
done

mkdir -p packages
cp drbd-test-bundle/target/drbd-test-target.tgz packages/

vmshed										\
	--out-dir "$(readlink -f tests-out)"					\
	--startvm 40								\
	--nvms "${LINBIT_CI_MAX_CPUS:-20}"						\
	--vms drbd-test-bundle/virter/vms.toml					\
	--tests drbd-test-bundle/virter/tests.toml				\
	--set values.TestSuiteImage=$LINBIT_DOCKER_REGISTRY/drbd9-tests:$DRBD9_TESTS_VERSION \
	--set values.DrbdVersion=$DRBD_VERSION					\
	--set values.RepositoryPackages=drbd-utils=$DRBD_UTILS_VERSION		\
	"$@"
