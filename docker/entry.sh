#!/bin/bash

set -e

[ -n "$TEST_NAME" ] && TEST_PATH="tests/$TEST_NAME"

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
[ "$DRBD_TEST_RDMA" = "true" ] && test_args+=( "--rdma" )

echo "===== Run test '$TEST_PATH' with args '${test_args[*]}' on nodes '${nodes[*]}'"

/virter/workspace/"$TEST_PATH" "${test_args[@]}" "${nodes[@]}"
