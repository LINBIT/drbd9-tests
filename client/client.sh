export DRBD_TEST_DATA=/usr/share/drbd-test

RSYSLOGD_PORT=5140

declare -a CLEANUP
register_cleanup() {
    CLEANUP[${#CLEANUP[@]}]="$*"
}
cleanup() {
    local cleanup

    for cleanup in "${CLEANUP[@]}"; do
	$cleanup || :
    done
}
trap cleanup EXIT

tmpdir=$(mktemp -dt)
register_cleanup 'rm -rf "$tmpdir"'

verbose() {
    [ -z "$opt_verbose" ] || echo "$@"
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
    eval "exec ${!out}>&-"
    wait $pid
}

on() {
    local options proc procs

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
	eval "exxe \"\${options[@]}\" -i \"\$@\" >&${COPROC_OUT[$proc]}"
    done
    for proc in "${procs[@]}"; do
	eval "exxe -o --error-prefix=\"\$proc: \" <&${COPROC_IN[$proc]}"
    done
}

event() {
    local node nodes logfiles

    while :; do
	[ -n "${COPROC_PID[$1]}" ] || break
	nodes[${#nodes[@]}]=$1
	shift
    done
    for node in "${nodes[@]}"; do
	logfiles[${#logfiles[@]}]=$node:$DRBD_TEST_JOB/events-$node
    done
    logscan ${opt_verbose+--verbose} -p $DRBD_TEST_JOB/pos "$@" "${logfiles[@]}"
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
