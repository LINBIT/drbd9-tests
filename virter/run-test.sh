#!/bin/bash

set -e

die() {
	echo "$1" >&2
	exit 1
}

[ -z "$DRBD_VERSION" ] && die "Missing \$DRBD_VERSION"
[ -z "$DRBD_UTILS_VERSION" ] && die "Missing \$DRBD_UTILS_VERSION"
[ -z "$DRBD9_TESTS_VERSION" ] && die "Missing \$DRBD9_TESTS_VERSION"

extra_args=()
# We want to default to "--variant tcp". However, vmshed collects all values of
# this option, so if "--variant" is given as an argument we must avoid setting
# it.
variant_set=false
for arg in "${@}"; do
	[[ "$arg" = "--variant" || "$arg" == "--variant="* ]] && variant_set=true
	extra_args+=( "$arg" )
done
[ "$variant_set" = "true" ] || extra_args+=( "--variant" "tcp" "--variant" "raw" "--variant" "zfs" )

[ -n "$DRBD_VERSION_OTHER" ] && extra_args+=( "--set" "values.DrbdVersionOther=$DRBD_VERSION_OTHER" )

echo "=== generate vmshed test configuration" >&2
make virter/tests.toml \
	VMSHED_TEST_SELECTION="${VMSHED_TEST_SELECTION:-ci}" \
	DRBD_VERSION="$DRBD_VERSION" \
	DRBD_VERSION_OTHER="$DRBD_VERSION_OTHER"

echo "=== virter version:" >&2
virter version >&2

echo "=== vmshed version:" >&2
vmshed --version >&2

echo "=== Pull images" >&2

for BASE_IMAGE in $(rq -t < virter/vms.toml | jq -r '.vms[] | .base_image'); do
	virter image pull $BASE_IMAGE $LINBIT_DOCKER_REGISTRY/vm/drbd9-tests/$BASE_IMAGE:latest
done

echo "=== Run vmshed with extra args '${extra_args[*]}'" >&2

vmshed										\
	--out-dir "$(readlink -f tests-out)"					\
	--startvm 40								\
	--nvms "${LINBIT_CI_MAX_CPUS:-20}"						\
	--vms virter/vms.toml					\
	--tests virter/tests.toml				\
	--set values.TestSuiteImage=$LINBIT_DOCKER_REGISTRY/drbd9-tests:$DRBD9_TESTS_VERSION \
	--set values.DrbdVersion=$DRBD_VERSION					\
	--set values.RepositoryPackages=drbd-utils=$DRBD_UTILS_VERSION		\
	"${extra_args[@]}"
