#!/bin/bash

set -e

cd "/virter/workspace/$DRBD_TESTS_ROOT_DIR"

[ -n "$TEST_NAME" ] && TEST_PATH="${DRBD_TESTS_SUB_DIR:-tests}/$TEST_NAME"

if [ -z "$TEST_PATH" ]; then
    echo "No test specified"
    exit 1
fi

if [ ! -e "$TEST_PATH" ]; then
    echo "Unknown test '$TEST_PATH' in '$(pwd)'"
    exit 1
fi

echo "===== Get the FQDN from the test nodes"

# Read TARGETS into array targets without messing up IFS
IFS=, read -a targets <<< "$TARGETS"

test_args=( "$@" "--logdir" "/log" )
if [ -f /etc/ssh/ssh_config.virter ] ; then
    test_args+=( "--ssh-config=/etc/ssh/ssh_config.virter" )
fi

nodes=()
for t in "${targets[@]}"; do
    if [ -f /etc/ssh/ssh_config.virter ] ; then
        t_host=$(ssh -F /etc/ssh/ssh_config.virter $t hostname -f)
    else
        t_host=$(ssh $t hostname -f)
    fi
    echo "=== Target $t => $t_host"
    nodes+=( "$t_host" )
done

[ -n "$DRBD_VERSION" ] && test_args+=( "--drbd-version=$DRBD_VERSION" )
[ -n "$DRBD_VERSION_OTHER" ] && test_args+=( "--drbd-version-other=$DRBD_VERSION_OTHER" )
[ -n "$DRBD_OTHER_NODE" ] && test_args+=( "--drbd-other-node=$DRBD_OTHER_NODE" )
[ -n "$SCRATCH_DISK" ] && test_args+=( "--backing-device=$SCRATCH_DISK")
[ -n "$DRBD_TEST_STORAGE" ] && test_args+=( "--storage-backend=$DRBD_TEST_STORAGE" )
[ -n "$DRBD_TEST_TRANSPORT" ] && test_args+=( "--transport=$DRBD_TEST_TRANSPORT" )
[ -n "$DRBD_TEST_TLS" ] && test_args+=( "--tls=$DRBD_TEST_TLS" )
[ "$SELINUX_DEBUG" = "true" ] && test_args+=( "--selinux-debug" )

echo "===== Run test '$TEST_PATH' with args '${test_args[*]}' on nodes '${nodes[*]}'"
./"$TEST_PATH" "${test_args[@]}" "${nodes[@]}"
