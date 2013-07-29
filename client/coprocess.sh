#! /bin/bash

tmpdir=$(mktemp -dt)
cleanup() {
    rm -rf "$tmpdir"
}
trap cleanup EXIT

# This is similar to bash's coproc command, except that the coproc command only
# allows one coprocess at a time, and even then doesn't really seem to work as
# described.
create_coprocess() {
    local name=$1 in out
    shift

    mkfifo $tmpdir/io-$name $tmpdir/oi-$name
    "$@" > $tmpdir/io-$name < $tmpdir/oi-$name &
    exec {in}< $tmpdir/io-$name {out}> $tmpdir/oi-$name
    eval "${name}_PID=$!; $name=($in $out)"
    rm -f $tmpdir/io-$name $tmpdir/oi-$name
}

close_coprocess() {
    local name=$1 out
    eval "out=$name[1]"
    eval "exec ${!out}>&-"
    eval "wait \$${name}_PID"
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
	eval "exxe $no_stdin -i \"\$@\" >&\${$proc[1]}"
    done
    for proc in "${procs[@]}"; do
	eval "exxe -o <&\${$proc[0]}"
    done
}

create_coprocess LOCAL exxe
create_coprocess X ssh localhost exxe

on LOCAL echo foo
on X echo foo
on LOCAL X echo bar
echo baz | on -i X tr a-z A-Z

close_coprocess LOCAL
close_coprocess X
