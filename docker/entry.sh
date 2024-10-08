#!/bin/bash

set -e

[ -n "$TEST_NAME" ] && TEST_PATH="${DRBD_TESTS_DIR:-tests}/$TEST_NAME"

if [ -z "$TEST_PATH" ]; then
    echo "No test specified"
    exit 1
fi

if [ ! -e /virter/workspace/"$TEST_PATH" ]; then
    echo "Unknown test '$TEST_PATH'"
    exit 1
fi

echo "===== Get the FQDN from the test nodes"

# Read TARGETS into array targets without messing up IFS
IFS=, read -a targets <<< "$TARGETS"

nodes=()
for t in "${targets[@]}"; do
    t_host=$(ssh $t hostname -f)
    echo "=== Target $t => $t_host"
    nodes+=( "$t_host" )
done

test_args=( "$@" "--logdir" "/log" )
[ -n "$DRBD_VERSION" ] && test_args+=( "--drbd-version=$DRBD_VERSION" )
[ -n "$DRBD_VERSION_OTHER" ] && test_args+=( "--drbd-version-other=$DRBD_VERSION_OTHER" )
[ -n "$DRBD_OTHER_NODE" ] && test_args+=( "--drbd-other-node=$DRBD_OTHER_NODE" )
[ -n "$SCRATCH_DISK" ] && test_args+=( "--backing-device=$SCRATCH_DISK")
[ -n "$DRBD_TEST_STORAGE" ] && test_args+=( "--storage-backend=$DRBD_TEST_STORAGE" )
[ -n "$DRBD_TEST_TRANSPORT" ] && test_args+=( "--transport=$DRBD_TEST_TRANSPORT" )
[ -n "$DRBD_TEST_TLS" ] && test_args+=( "--tls=$DRBD_TEST_TLS" )

echo "===== Run test '$TEST_PATH' with args '${test_args[*]}' on nodes '${nodes[*]}'"

cd /virter/workspace/
./"$TEST_PATH" "${test_args[@]}" "${nodes[@]}"
