export DRBD_TEST_DATA=/usr/share/drbd-test

RSYSLOGD_PORT=5140

declare -a CLEANUP
register_cleanup() {
    CLEANUP[${#CLEANUP[@]}]="$*"
}

cleanup() {
    local cleanup status=$? n file line

    if [ $status -ne 0 ]; then
	( echo
	echo "Backtrace:"
	for ((n = 2; n < ${#BASH_SOURCE[@]}; n++)); do
	    file=${BASH_SOURCE[$n]}
	    line=${BASH_LINENO[$n - 1]}
	    sed -ne "${line}s,^[ \\t]*,  $file:$line: ,p" "$file"
	done ) >&2
    fi
    set +e
    for cleanup in "${CLEANUP[@]}"; do
	# Restore the $? variable for each cleanup task
	( exit $status )
	$cleanup
    done
}
trap cleanup EXIT

tmpdir=$(mktemp -dt)
register_cleanup 'rm -rf "$tmpdir"'

verbose() {
    [ -z "$opt_verbose" ] || echo "$@" >&$stdout_dup
}

do_debug() {
    if [ -n "$opt_debug" ]; then
	echo -n "#"
	printf " %q" "$@"
	echo
     fi >&2
    "$@"
}

# This is similar to bash's coproc command, except that the coproc command only
# allows one coprocess at a time, and even then doesn't really seem to work as
# described.
declare -A COPROC_PID COPROC_IN COPROC_OUT
create_coprocess() {
    local proc=$1 in out
    shift

    mkfifo $tmpdir/io-$proc $tmpdir/oi-$proc
    "$@" > $tmpdir/io-$proc < $tmpdir/oi-$proc &
    exec {in}< $tmpdir/io-$proc {out}> $tmpdir/oi-$proc
    COPROC_PID[$proc]=$!
    COPROC_IN[$proc]=$in
    COPROC_OUT[$proc]=$out
    rm -f $tmpdir/io-$proc $tmpdir/oi-$proc
}

close_coprocess() {
    local pid=${COPROC_PID[$1]} out=${COPROC_OUT[$1]}
    eval "exec $out>&-"
    wait $pid
}

on() {
    local -a options procs
    local proc status

    while [ "${1:0:1}" = "-" ]; do
	options=("${options[@]}" "$1")
	shift
    done
    while :; do
	[ -n "${COPROC_PID[$1]}" ] || break
	procs[${#procs[@]}]=$1
	shift
    done

    verbose "${procs[*]}: calling $@"
    for proc in "${procs[@]}"; do
	eval "exxe \"\${options[@]}\" -i --logfile=\"\$DRBD_TEST_JOB/exxe-$proc.log\" \"\$@\" >&${COPROC_OUT[$proc]}"
    done
    for proc in "${procs[@]}"; do
	eval "exxe -o --error-prefix=\"\$proc: \" --logfile=\"\$DRBD_TEST_JOB/exxe-$proc.log\" <&${COPROC_IN[$proc]}"
	status=$?
	if [ $status != 0 ]; then
	    verbose "$proc: $1 failed with status code $status"
	    return $status
	fi
    done
}

declare -a NEVER_MATCH

# Match an event on one or more nodes
#
# USAGE: event {node} [... {node}] {logscan options}
#
# This function keeps track of the current position in the event logs
# independently for each node.  (The setup function sets the NODES array to a
# list of defined nodes; use this to iterate over all nodes.)
#
event() {
    local -a nodes
    local node

    verbose "Waiting for event$(printf " %q" "$@")"
    sync_events node
    while :; do
	[ -n "${COPROC_PID[$1]}" ] || break
	node=$1
	set -- "$@" \
	    events-$node \
	    --label="$node" \
	    -p .events.pos
	shift
    done
    do_debug logscan -d $DRBD_TEST_JOB -w \
		     --silent ${opt_verbose:+--verbose} \
		     "${NEVER_MATCH[@]/#/-N}" \
		     "$@"
}

# Match an event on one or more nodes
#
# USAGE: connection_event {node1:node2} [... {node1:node2}] {logscan options}
#
# This function keeps track of the current position in the event logs
# independently for each connection.  (The setup function sets the CONNECTIONS
# array to a list of defined connections; use this to iterate over all
# connections.)
#
connection_event() {
    local n1 n2

    verbose "Waiting for event$(printf " %q" "$@")"
    sync_events connection
    while :; do
	[ -n "${CONNECTIONS[$1]}" ] || break
	n1=${1%%:*}
	n2=${1#*:}
	set -- "$@" \
	    events-$n1 \
	    --label="$1" \
	    -p .events-connection-$n2.pos \
	    -f "conn-name:${params["$n2:FULL_HOSTNAME"]}"
	shift
    done
    do_debug logscan -d $DRBD_TEST_JOB -w \
		     --silent ${opt_verbose:+--verbose} \
		     "${NEVER_MATCH[@]/#/-N}" \
		     "$@"
}

# Match an event on one or more nodes and volumes
#
# USAGE: volume_event {node:volume} [ ... {node:volume} ] {logscan options}
#
volume_event() {
    local node volume

    verbose "Waiting for event$(printf " %q" "$@")"
    sync_events volume
    while :; do
	[ -n "${DEFINED_NODES[${1%:*}]}" ] || break
	node=${1%:*}
	volume=${1##*:}
	set -- "$@" \
	    events-$node \
	    --label="$1" \
	    -p .events-volume-$volume.pos \
	    -f "volume:$volume"
	shift
    done
    do_debug logscan -d $DRBD_TEST_JOB -w \
		     --silent ${opt_verbose:+--verbose} \
		     "${NEVER_MATCH[@]/#/-N}" \
		     "$@"
}

# Match an event on one or more peer devices
#
# Usage: peer_device_event {node1:node2:volume} [ ... {node1:node2:volume} ] {logscan options}
#
peer_device_event() {
    local nodes n1 n2 volume

    verbose "Waiting for event$(printf " %q" "$@")"
    sync_events peer_device
    while :; do
	nodes=${1%:*}; n1=${nodes%:*}; n2=${nodes#*:}
	[ -n "${DEFINED_NODES[$n1]}" -a -n "${DEFINED_NODES[$n2]}" ] || break
	volume=${1##*:}
	set -- "$@" \
	    events-$n1 \
	    --label="$1" \
	    -p .events-peer-device-$n2:$volume.pos \
	    -f "conn-name:${params["$n2:FULL_HOSTNAME"]}" \
	    -f "volume:$volume"
	shift
    done
    do_debug logscan -d $DRBD_TEST_JOB -w \
		     --silent ${opt_verbose:+--verbose} \
		     "${NEVER_MATCH[@]/#/-N}" \
		     "$@"
}

push_forbidden_patterns() {
    NEVER_MATCH=("${NEVER_MATCH[@]}" "$@")
}

pop_forbidden_patterns() {
    local n=$((${#NEVER_MATCH[@]} - 1))
    local opt_f

    if [ "$1" = "-f" ]; then
	opt_f=1
	shift
    fi

    while [ $# -gt 0 ]; do
	if [ "${NEVER_MATCH[$n]}" = "$1" ]; then
	    unset "NEVER_MATCH[$n]"
	    (( n-- ))
	elif [ -z "$opt_f" ]; then
	    printf "$0: The last pattern on the stack is '%s', not '%s'\n" \
		   "${NEVER_MATCH[$n]}" "$1" >&2
	    exit 2
	fi
	shift
    done
}

clear_forbidden_patterns() {
    NEVER_MATCH=()
}

# Synchronize between global and per-connection matching
#
# The event and connection_event functions keep track of the current position
# in the event log independently: globally (event), and separately for each
# connection (connection_event).  The sync_events function synchronizes the
# current positions of event and connection_event.
#
# This function is called internally whenever switching between different
# types of matches (event, connection_event, volume_event, peer_device_event).
#
declare LAST_EVENT_CLASS

sync_events() {
    local -a file data

    shopt -s nullglob

    if [ "${1:-node}" != "$LAST_EVENT_CLASS" ]; then
	LAST_EVENT_CLASS=${1:-node}
	do_debug logscan -d $DRBD_TEST_JOB --sync .*.pos
	( cd $DRBD_TEST_JOB ; do_debug logscan --sync .*.pos )
    fi
}

connect_to_nodes() {
    local node

    for node in "$@"; do
	create_coprocess $node ssh root@$node exxe --syslog
	on -Q $node export \
	    PATH="$DRBD_TEST_DATA:\$PATH"
	on $node export \
	    DRBD_TEST_DATA="$DRBD_TEST_DATA" \
	    DRBD_TEST_JOB="$DRBD_TEST_JOB" \
	    EXXE_IDENT="exxe/$DRBD_TEST_JOB"

	if ! on $node test -d "$DRBD_TEST_DATA"; then
	    echo "Node $node: Directory $DRBD_TEST_DATA does not exist" >&2
	    exit 1
	fi
    done
}

block_connection() {
    local node1=$1 node2=$2

    on "$node1" block-connection \
       "${cfg[$RESOURCE:$node1:$node2::local]}" \
       "${cfg[$RESOURCE:$node1:$node2::peer]}"
}

unblock_connection() {
    local node1=$1 node2=$2

    on "$node1" unblock-connection \
       "${cfg[$RESOURCE:$node1:$node2::local]}" \
       "${cfg[$RESOURCE:$node1:$node2::peer]}"
}

skip_test() {
    echo "${0##*/}:" "$@" >&2
    exit 100
}

_up() {
    on "${NODES[@]}" drbdadm up all
    volume_event ${VOLUMES[@]} -y 'device .* disk:Inconsistent'

    # These error states must never occur unless a test case simulates things
    # like node failures, network errors, or disk failures.
    push_forbidden_patterns \
	'connection:Timeout' \
	'connection:BrokenPipe' \
	'connection:NetworkFailure' \
	'connection:ProtocolError' \
	'disk:Failed' \
	'peer-disk:Failed'
}

_wait_connected() {
    connection_event "${CONNECTIONS[@]}" -y 'connection .* connection:Connected'
}

_force_primary() {
    local first_node="${NODES[0]}"

    on "$first_node" drbdadm primary --force all
    event "$first_node" -y 'resource .* role:Primary'
    volume_event ${VOLUMES[$first_node]} -y 'device .* disk:UpToDate'
}

_initial_resync() {
    local -a volumes
    local node

    # Use unlimited resync bandwidth
    on "${NODES[@]}" drbdadm disk-options --c-min-rate=0 all

    for node in $(all_nodes_except "${NODES[0]}"); do
	volumes=( "${volumes[@]}" ${VOLUMES[$node]} )
    done
    volume_event "${volumes[@]}" --timeout=300 -y 'device .* disk:UpToDate'
}

_down() {
    pop_forbidden_patterns -f 'peer-disk:Failed' 'disk:Failed'
    on "${NODES[@]}" drbdadm down all
    event "${NODES[@]}" -y 'destroy resource'
}

_rmmod() {
    on "${NODES[@]}" rmmod drbd
}
