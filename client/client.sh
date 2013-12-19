export DRBD_TEST_DATA=/usr/share/drbd-test

RSYSLOGD_PORT=5140

declare -a CLEANUP
register_cleanup() {
    CLEANUP[${#CLEANUP[@]}]="$*"
}

cleanup() {
    local cleanup status=$?

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

    for proc in "${procs[@]}"; do
	verbose "$proc: calling $@"
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

    sync_events node
    while :; do
	[ -n "${COPROC_PID[$1]}" ] || break
	nodes[${#nodes[@]}]=$1
	shift
    done
    for node in "${nodes[@]}"; do
	set -- "$@" --label=$node $DRBD_TEST_JOB/events-$node
    done
    logscan ${opt_verbose+--verbose} -p $DRBD_TEST_JOB/node-event.pos "$@"
}

# Match an event on one or more nodes
#
# USAGE: connection_event {connection} [... {connection}] {logscan options}
#
# This function keeps track of the current position in the event logs
# independently for each connection.  (The setup function sets the CONNECTIONS
# array to a list of defined connections; use this to iterate over all
# connections.)
#
connection_event() {
    local -a connections
    local connection n1 n2 posfile filter

    sync_events connection
    while :; do
	[ -n "${CONNECTIONS[$1]}" ] || break
	connections[${#connections[@]}]=$1
	shift
    done
    for connection in "${connections[@]}"; do
	n1=${connection%%:*}
	n2=${connection#*:}
	posfile=$DRBD_TEST_JOB/connection-event-$connection.pos
	filter=" conn-name:${params["$n2:FULL_HOSTNAME"]} "
	logscan ${opt_verbose+--verbose} -p "$posfile" -f "$filter" "$@" \
		--label="$connection" $DRBD_TEST_JOB/events-$n1
    done
}

# Match an event on one or more nodes and volumes
volume_event() {
    local -a nodes_volumes
    local node_volume node posfile filter

    sync_events volume
    while :; do
	[ -n "${DEFINED_NODES[${1%:*}]}" ] || break
	nodes_volumes[${#nodes_volumes[@]}]=$1
	shift
    done
    for node_volume in "${nodes_volumes[@]}"; do
	node=${node_volume%:*}
	posfile=$DRBD_TEST_JOB/volume-event-$node_volume.pos
	filter=" volume:${node_volume##*:} "
	logscan ${opt_verbose+--verbose} -p "$posfile" -f "$filter" "$@" \
		--label="$node_volume" $DRBD_TEST_JOB/events-$node
    done
}

# Synchronize between global and per-connection matching
#
# The event and connection_event functions keep track of the current position
# in the event log independently: globally (event), and separately for each
# connection (connection_event).  The sync_events function synchronizes the
# current positions of event and connection_event.
#
# This function is called internally whenever switching between different
# types of matches (event, connection_event, volume_event).
#
declare LAST_EVENT_CLASS

sync_events() {(
    local -a file data

    shopt -s nullglob

    if [ "${1:-node}" != "$LAST_EVENT_CLASS" ]; then
	LAST_EVENT_CLASS=${1:-node}

	data="$(
	    for file in $DRBD_TEST_JOB/*.pos; do
		cat "$file"
	    done \
	    | sort -t ' ' -k 2,2 -r \
	    | sort -t ' ' -k 3,3 -u)"
	for file in $DRBD_TEST_JOB/*.pos; do
	    echo "$data" > "$file"
	done
    fi
)}

connect_to_nodes() {
    local node

    for node in "$@"; do
	create_coprocess $node ssh root@$node exxe --syslog
	on -Q $node export PATH="$DRBD_TEST_DATA:\$PATH"
	on $node export DRBD_TEST_DATA="$DRBD_TEST_DATA"
	on $node export DRBD_TEST_JOB="$DRBD_TEST_JOB"
	on $node export EXXE_IDENT="exxe/$DRBD_TEST_JOB"

	if ! on $node test -d "$DRBD_TEST_DATA"; then
	    echo "Node $node: Directory $DRBD_TEST_DATA does not exist" >&2
	    exit 1
	fi
    done
}

skip_test() {
    echo "${0##*/}:" "$@" >&2
    exit 100
}

_up() {
    on "${NODES[@]}" drbdadm up all
    for node in "${NODES[@]}"; do
	event "$node" -y ' device .* disk:Inconsistent'
    done
}

_force_primary() {
    on "${NODES[0]}" drbdadm primary --force all
    event "${NODES[0]}" -y ' resource .* role:Primary' -y ' device .* disk:UpToDate'
}

_initial_resync() {
    local node volume

    # Use unlimited resync bandwidth
    on "${NODES[@]}" drbdadm disk-options --c-min-rate=0 all

    for node in "${NODES[@]}"; do
	if [ "$node" != "${NODES[0]}" ]; then
	    for volume in ${VOLUMES[$node]}; do
		volume_event "$volume" --timeout=300 -y ' device .* disk:UpToDate'
	    done
	fi
    done
}

_down() {
    on "${NODES[@]}" drbdadm down all
}

_rmmod() {
    on "${NODES[@]}" rmmod drbd
}
