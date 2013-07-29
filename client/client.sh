do_debug() {
    if [ -n "$opt_debug" ]; then
	echo -n "#"
	printf " %q" "$@"
	echo
     fi >&2
    "$@"
}

jobdir() {
    echo "$1"
}

run_exxe_on_node() {
    local node=$1

    [ -z "${NODE_IN[$node]}" ] || return 0
    # exxe -n -i export DRBD_TEST_JOB=$DRBD_TEST_JOB
    # exxe -n -i export PATH=...
}

on_node() {
    local node=$1

    run_exxe_on_node "$node"
    # Make sure that the drbd-test scripts are in $PATH on the server
    # Log everything we do here ...
    # FIXME: Pass the job name to the server in the environment
    :
}

on_all_nodes() {
    local node

    for node in "${NODES[@]}"; do
	on_node "$node" "$@"
    done
}
