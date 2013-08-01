export DRBD_TEST_DATA=/usr/share/drbd-test

tmpdir=$(mktemp -dt)
cleanup() {
    rm -rf "$tmpdir"
}
trap cleanup EXIT

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

# This is similar to bash's coproc command, except that the coproc command only
# allows one coprocess at a time, and even then doesn't really seem to work as
# described.
create_coprocess() {
    local proc=$1 in out
    shift

    mkfifo $tmpdir/io-$proc $tmpdir/oi-$proc
    "$@" > $tmpdir/io-$proc < $tmpdir/oi-$proc &
    exec {in}< $tmpdir/io-$proc {out}> $tmpdir/oi-$proc
    eval "export ${proc}_PID=$!; ${proc}_IN=$in ${proc}_OUT=$out"
    rm -f $tmpdir/io-$proc $tmpdir/oi-$proc
}

close_coprocess() {
    local proc=$1 out
    eval "out=${proc}_OUT"
    eval "exec ${!out}>&-"
    eval "wait \$${proc}_PID"
}

on() {
    local no_stdin=-n proc procs var
    if [ "$1" = "-i" ]; then
	no_stdin=
	shift
    fi
    while :; do
	var=$1_PID
	[ -n "${!var}" ] || break
	procs[${#procs[@]}]=$1
	shift
    done

    for proc in "${procs[@]}"; do
	eval "exxe $no_stdin -i \"\$@\" >&\$${proc}_OUT"
    done
    for proc in "${procs[@]}"; do
	eval "exxe -o <&\$${proc}_IN"
    done
}
