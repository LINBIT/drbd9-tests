#!/bin/bash

set -e

if [ -z "$TEST_NAME" ]; then
    echo "No test specified"
    exit 1
fi

if [ ! -e tests/"$TEST_NAME" ]; then
    echo "Unknown test '$TEST_NAME'"
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

test_args=( "--logdir" "/log" )
[ "$DRBD_TEST_RDMA" = "true" ] && test_args+=( "--rdma" )

echo "===== Run test '$TEST_NAME' with args '${test_args[*]}' on nodes '${nodes[*]}'"

tests/"$TEST_NAME" "${test_args[@]}" "${nodes[@]}"
