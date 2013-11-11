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

event() {
    local -a nodes logfiles
    local node

    while :; do
	[ -n "${COPROC_PID[$1]}" ] || break
	nodes[${#nodes[@]}]=$1
	shift
    done
    for node in "${nodes[@]}"; do
	set -- "$@" --label=$node $DRBD_TEST_JOB/events-$node
    done
    logscan ${opt_verbose+--verbose} -p $DRBD_TEST_JOB/events.pos "$@"
}

connection_event() {
    local -a connections
    local connection n1 n2 logfile posfile filter

    while :; do
	[ -n "${CONNECTIONS[$1]}" ] || break
	connections[${#connections[@]}]=$1
	shift
    done
    for connection in "${connections[@]}"; do
	n1=${connection%%:*}
	n2=${connection#*:}
	logfile=${connection/:/:}:$DRBD_TEST_JOB/events-$n1
	posfile=$DRBD_TEST_JOB/events-$connection.pos
	filter=conn-name:${params["$n2:FULL_HOSTNAMES"]}
	logscan ${opt_verbose+--verbose} -p "$posfile" -f "$filter" "$@" \
		--label="$connection" $DRBD_TEST_JOB/events-$n1
    done
}

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
    # Use unlimited resync bandwidth
    on "${NODES[@]}" drbdadm disk-options --c-min-rate=0 all

    for node in "${NODES[@]}"; do
	if [ "$node" != "${NODES[0]}" ]; then
	    event "$node" --timeout=300 -y ' device .* disk:UpToDate'
	fi
    done
}

_down() {
    on "${NODES[@]}" drbdadm down all
}

_rmmod() {
    on "${NODES[@]}" rmmod drbd
}
