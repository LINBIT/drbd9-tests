#!/bin/sh

die() {
	echo "$1" >&2
	exit 1
}

[ -z "$DRBD_VERSION" ] && die "Missing \$DRBD_VERSION"
[ -z "$DRBD_UTILS_VERSION" ] && die "Missing \$DRBD_UTILS_VERSION"
[ -z "$DRBD9_TESTS_VERSION" ] && die "Missing \$DRBD9_TESTS_VERSION"

repeats=$1
testsfile=$2

[ -z "$repeats" ] && repeats=1
[ -z "$testsfile" ] && testsfile="drbd-test-bundle/virter/tests.toml"

for BASE_IMAGE in $(rq -t < drbd-test-bundle/virter/vms.toml | jq -r '.vms[] | .base_image'); do
	if ! virsh vol-info --pool default $BASE_IMAGE; then
		virter image pull --url $LINBIT_REGISTRY_URL/repository/vm-image/$BASE_IMAGE $BASE_IMAGE
	fi
done

mkdir -p packages
cp drbd-test-bundle/target/drbd-test-target.tgz packages/

vmshed										\
	--out-dir "$(readlink -f tests-out)"					\
	--startvm 40								\
	--nvms 20								\
	--vms drbd-test-bundle/virter/vms.toml					\
	--tests "$testsfile"							\
	--set values.TestSuiteImage=$LINBIT_DOCKER_REGISTRY/drbd9-tests:$DRBD9_TESTS_VERSION \
	--set values.DrbdVersion=$DRBD_VERSION					\
	--set '"""values.RepositoryPackages=exxe\,drbd-utils='$DRBD_UTILS_VERSION'"""' \
	--repeats $repeats
