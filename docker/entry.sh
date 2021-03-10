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

nodes=()

IFS=,; for t in $TARGETS; do
    t_host=$(ssh $t hostname -f)
    echo "=== Target $t => $t_host"
    nodes+=( "$t_host" )
done

echo "===== Run test '$TEST_NAME' with nodes: ${nodes[@]}"

tests/$TEST_NAME --no-syslog --logdir /log ${nodes[@]}
