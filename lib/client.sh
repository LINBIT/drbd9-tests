export DRBD_TEST_DATA=/usr/share/drbd-test

RSYSLOGD_PORT=5140

declare -a CLEANUP
register_cleanup() {
    CLEANUP[${#CLEANUP[@]}]="$*"
}

cleanup() {
    local cleanup status=$? cleanup_status n file line

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
	cleanup_status=$?
	[ $status -ne 0 ] || status=$cleanup_status
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
    local proc status prefix

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
	if [ ${#procs[@]} -gt 1 ]; then
	    prefix="--prefix=\"\$proc: \""
	else
	    prefix="--error-prefix=\"\$proc: \""
	fi
	eval "exxe -o $prefix --logfile=\"\$DRBD_TEST_JOB/exxe-$proc.log\" <&${COPROC_IN[$proc]}"
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
	    -f "local:[^ :]*:${cfg[$RESOURCE:$1::local]}" \
	    -f "peer:[^ :]*:${cfg[$RESOURCE:$1::peer]}"
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
	    -f "local:[^ :]*:${cfg[$RESOURCE:$nodes::local]}" \
	    -f "peer:[^ :]*:${cfg[$RESOURCE:$nodes::peer]}" \
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
	    EXXE_IDENT="exxe/$DRBD_TEST_JOB" \
	    ${opt_verbose:+DRBD_TEST_VERBOSE=1}

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

all_nodes_except() {
    local node n
    for node in "${NODES[@]}"; do
	for ((n = 1; n <= $#; n++)); do
	    [ "$node" != "${!n}" ] || continue 2
	done
	echo "$node"
    done
}

all_volumes_except() {
    local volume n
    for volume in "${VOLUMES[@]}"; do
	for ((n = 1; n <= $#; n++)); do
	    [ "$volume" != "${!n}" ] || continue 2
	done
	echo "$volume"
    done
}

all_connections_from() {
    local connection

    for connection in "${CONNECTIONS[@]}"; do
	[ "${connection%%:*}" != "$1" ] || echo "$connection"
    done
}

all_connections_to() {
    local connection

    for connection in "${CONNECTIONS[@]}"; do
	[ "${connection#*:}" != "$1" ] || echo "$connection"
    done
}

reverse_connections() {
    local n1 n2
    for connection in "$@"; do
	n1=${connection%%:*}
	n2=${connection#*:}
	echo "$n2:$n1"
    done
}

declare _UP_FORBIDDEN=

_up() {
    # By default, take all nodes up
    [ $# -gt 0 ] || set -- "${NODES[@]}"

    local volumes
    for node in "$@"; do
	volumes=( "${volumes[@]}" ${VOLUMES[$node]} )
    done

    on "$@" drbdadm up all
    volume_event ${volumes[@]} -y 'device .* disk:Inconsistent'

    if [ -z "$_UP_FORBIDDEN" ]; then
	# These error states must never occur unless a test case simulates things
	# like node failures, network errors, or disk failures.
	push_forbidden_patterns \
	    'connection:Timeout' \
	    'connection:BrokenPipe' \
	    'connection:NetworkFailure' \
	    'connection:ProtocolError' \
	    'disk:Failed' \
	    'peer-disk:Failed'
	_UP_FORBIDDEN=1
    fi
}

_wait_connected() {
    connection_event "${CONNECTIONS[@]}" -y 'connection .* connection:Connected'
}

_connect() {
    local n1 n2

    for connection in "$@"; do
	n1=${connection%%:*}
	n2=${connection#*:}
	on "$n1" drbdadm connect $RESOURCE:${param[$n2:FULL_HOSTNAME]}
	CONNECTIONS["$connection"]=$connection
    done
    connection_event "$@" -y 'connection .* connection:Connecting'
}

_disconnect() {
    local n1 n2

    for connection in "$@"; do
	n1=${connection%%:*}
	n2=${connection#*:}
	on "$n1" drbdadm disconnect $RESOURCE:${param[$n2:FULL_HOSTNAME]}
	unset CONNECTIONS["$connection"]
    done
    connection_event "$@" -y 'connection .* connection:StandAlone'
}

_force_primary() {
    # By default, make the first node the primary
    [ $# -ge 1 ] || set -- "${NODES[0]}"

    on "$1" drbdadm primary --force all
    event "$1" -y 'resource .* role:Primary'
    volume_event ${VOLUMES[$1]} -y 'device .* disk:UpToDate'
}

_initial_resync() {
    # By default, sync from the first node
    [ $# -gt 0 ] || set -- "${NODES[0]}"

    local -a volumes
    local node

    # Use unlimited resync bandwidth
    on "${NODES[@]}" drbdadm disk-options --c-min-rate=0 all

    for node in $(all_nodes_except "$1"); do
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
    if [ -z "$NO_RMMOD" ]; then
	on "${NODES[@]}" rmmod drbd
    fi
}

_fio() {
    local options=`getopt -o -h --long jobfile:,section: -- "$@"`
    eval set -- "$options"
    local jobfile=target/write-verify.fio.in section nodes_volumes
    local node_volume node volume device x job log status

    while :; do
	case "$1" in
	--jobfile)
	    jobfile=$2
	    shift
	    ;;
	--section)
	    section=$2
	    shift
	    ;;
	--)
	    shift
	    break
	    ;;
	*)
	    nodes_volumes[${#nodes_volumes[@]}]=$1
	    ;;
	esac
	shift
    done

    for node_volume in "${nodes_volumes[@]}"; do
	node=${node_volume%%:*}
	volume=${node_volume#*:}
	device=${cfg[$RESOURCE:$node_volume::device]}

	x=
	while :; do
	    job=$DRBD_TEST_JOB/fio-$node${section:+-$section}${x:+-$x}.fio
	    log=$DRBD_TEST_JOB/fio-$node${section:+-$section}${x:+-$x}.log
	    [ -e "$job" -o -e "$log" ] || break
	    ((++x))
	done

	# TODO: Without auto-promote, we would need to switch to primary on
	# each node first.  With auto-promote, since auto-promote allows
	# parallel reading, we could start read jobs on multiple nodes in
	# parallel.

	sed -e "s:@device@:$device:g" "$jobfile" > "$job"
	status=0
	on -p "$node" fio ${section:+--section=$section} - \
	    < "$job" > "$log" \
	    || status=$?
	if [ $status -ne 0 -o -n "$opt_verbose" ]; then
	    # fio at least sometimes doesn't report errors to standard error ...
	    cat "$log"
	    [ $status -eq 0 ] || exit $status
	fi
    done
}

# Pass the config file generated by setup() through a filter, and update
# the config file on all test nodes.  When called with 'cat' as argument,
# restore the original config file.
change_config() {
    local conf node version

    for conf in $DRBD_TEST_JOB/drbd*.conf; do
	if ! [ -e "$conf.orig" ]; then
	    cp "$conf" "$conf.orig"
	fi
	"$@" < "$conf.orig" > "$conf"
	for node in "${NODES[@]}"; do
	    version=${params["$node:DRBD_MAJOR_VERSION"]}
	    on -p $node install-config < $DRBD_TEST_JOB/drbd${version}.conf
	done
    done
}

# Hide one or more volumes from config files.  When no volumes are specified,
# restores the original config file.
#
# USAGE: hide_volumes [ {node:volume} ... ]
#
declare -A VOLUMES_ORIG
hide_volumes() {
    local node node_volume volume volumes

    local -A hide
    for node_volume in "$@"; do
	hide["$node_volume"]=1
    done

    local -a fullnames_volumes
    for node_volume in "$@"; do
	node=${node_volume%%:*}
	volume=${node_volume#*:}
	fullnames_volumes[${#fullnames_volumes[@]}]="${params["$node:FULL_HOSTNAME"]}:$volume"
    done

    if [ ${#VOLUMES_ORIG[@]} -eq 0 ]; then
	for node in "${!VOLUMES[@]}"; do
	    VOLUMES_ORIG[$node]=${VOLUMES[$node]}
	done
    fi
    for node in "${!VOLUMES_ORIG[@]}"; do
	set -- $(
	    for node_volume in ${VOLUMES_ORIG[$node]}; do
		if [ -z "${hide["$node_volume"]}" ]; then
		    echo $node_volume
		fi
	    done
	)
	VOLUMES["$node"]="$*"
    done

    change_config awk '
	BEGIN {
	    for (n = 1; n < ARGC; n++) {
		hide[ARGV[n]] = 1
		delete ARGV[n]
	    }
	    ARGV[1] = "-"
	}
	$1 == "on" {
	    fullname = $2
	}
	$1 == "volume" && fullname ":" $2 in hide {
	    eat = 1
	}
	eat && /\}/ {
	    eat = 0
	    next
	}
	! eat {
	    print
	}
	' "${fullnames_volumes[@]}"
}
