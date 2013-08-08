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
create_coprocess() {
    local proc=$1 in out
    shift

    mkfifo $tmpdir/io-$proc $tmpdir/oi-$proc
    "$@" > $tmpdir/io-$proc < $tmpdir/oi-$proc &
    exec {in}< $tmpdir/io-$proc {out}> $tmpdir/oi-$proc
    eval "export ${proc}_PID=$! ${proc}_IN=$in ${proc}_OUT=$out"
    rm -f $tmpdir/io-$proc $tmpdir/oi-$proc
}

close_coprocess() {
    local proc=$1 out
    eval "out=${proc}_OUT"
    eval "exec ${!out}>&-"
    eval "wait \$${proc}_PID"
}

on() {
    local options proc procs var
    while [ "${1:0:1}" = "-" ]; do
	options=("${options[@]}" "$1")
	shift
    done
    while :; do
	var=$1_PID
	[ -n "${!var}" ] || break
	procs[${#procs[@]}]=$1
	shift
    done

    for proc in "${procs[@]}"; do
	eval "exxe "${options[@]}" -i \"\$@\" >&\$${proc}_OUT"
    done
    for proc in "${procs[@]}"; do
	eval "exxe -o --error-prefix=\"\$${proc}_NAME: \" <&\$${proc}_IN"
    done
}

connect_to_nodes() {
    local n=0

    while [ $# -gt 0 ]; do
	create_coprocess NODE$n ssh root@$1 exxe
	eval "export NODE${n}_NAME=\"\$1\""

	on -n -Q NODE$n export PATH="$DRBD_TEST_DATA:\$PATH"
	on -n NODE$n export DRBD_TEST_DATA="$DRBD_TEST_DATA"
	on -n NODE$n export DRBD_TEST_JOB="$DRBD_TEST_JOB"

	if ! on -n NODE$n test -d "$DRBD_TEST_DATA"; then
	    echo "Node $1: Directory $DRBD_TEST_DATA does not exist" >&2
	    exit 1
	fi

	((++n))
	shift
    done
}
