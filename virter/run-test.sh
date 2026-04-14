#!/bin/bash

set -e

die() {
	echo "$1" >&2
	exit 1
}

drbd_tests_absolute_dir="$(dirname "$(dirname "$(readlink -f "$0")")")"

[[ "$drbd_tests_absolute_dir" == "$(pwd)"* ]] || die "Must run from ancestor of drbd9-tests directory"
# Use relative path because test container has the working directory mapped to /virter/workspace/
drbd_tests_root_dir=".${drbd_tests_absolute_dir#"$(pwd)"}"

[ -z "$DRBD_TEST_DOCKER_IMAGE" ] && die "Missing \$DRBD_TEST_DOCKER_IMAGE"
[ -z "$DRBD_VERSION" ] && die "Missing \$DRBD_VERSION"
[ -z "$DRBD_UTILS_VERSION" ] && die "Missing \$DRBD_UTILS_VERSION"

extra_args=()
# We want to default to "--variant tcp". However, vmshed collects all values of
# this option, so if "--variant" is given as an argument we must avoid setting
# it.
variant_set=false
for arg in "${@}"; do
	[[ "$arg" = "--variant" || "$arg" == "--variant="* ]] && variant_set=true
	extra_args+=( "$arg" )
done
[ "$variant_set" = "true" ] || extra_args+=( "--variant" "tcp" "--variant" "raw" "--variant" "zfs" "--variant" "tls")

[ -n "$DRBD_VERSION_OTHER" ] && extra_args+=( "--set" "values.DrbdVersionOther=$DRBD_VERSION_OTHER" )

WINDRBD_VERSION=${WINDRBD_VERSION:-windrbd-1.2-from-gitlab}
extra_args+=( "--set" "values.WinDrbdVersion=$WINDRBD_VERSION" )

# DRBD_TESTS_SUB_DIR is optional. Use default value if empty.
DRBD_TESTS_SUB_DIR="${DRBD_TESTS_SUB_DIR:-tests}"

echo "=== generate vmshed test configuration" >&2
make -C "$drbd_tests_root_dir" virter/tests.toml \
	DRBD_TESTS_SUB_DIR="$DRBD_TESTS_SUB_DIR" \
	VMSHED_TEST_SELECTION="${VMSHED_TEST_SELECTION:-ci}" \
	DRBD_VERSION="$DRBD_VERSION" \
	DRBD_VERSION_OTHER="$DRBD_VERSION_OTHER" \
	VMSHED_TEST_TIMEOUT="$VMSHED_TEST_TIMEOUT"

echo "=== virter version:" >&2
virter version >&2

echo "=== vmshed version:" >&2
vmshed --version >&2

if [ -z "$SKIP_PULL" ]; then
	echo "=== Pull images" >&2

	for BASE_IMAGE in $(rq -t < "$drbd_tests_root_dir/virter/vms.toml" | jq -r '.vms[] | .base_image'); do
		virter image pull $BASE_IMAGE $LINBIT_DOCKER_REGISTRY/vm/drbd9-tests/$BASE_IMAGE:latest
	done
fi

echo "=== Run vmshed with extra args '${extra_args[*]}'" >&2

vmshed										\
	--quiet									\
	--out-dir "$(readlink -f tests-out)"					\
	--startvm 40								\
	--nvms "${LINBIT_CI_MAX_CPUS:-20}"						\
	--vms "$drbd_tests_root_dir/virter/vms.toml"				\
	--tests "$drbd_tests_root_dir/virter/tests.toml"				\
	--set values.TestSuiteImage=$DRBD_TEST_DOCKER_IMAGE \
	--set values.DrbdTestsRootDir="$drbd_tests_root_dir"			\
	--set values.DrbdTestsSubDir="$DRBD_TESTS_SUB_DIR"			\
	--set values.DrbdVersion=$DRBD_VERSION					\
	--set values.DrbdUtilsVersion=$DRBD_UTILS_VERSION			\
	"${extra_args[@]}"
