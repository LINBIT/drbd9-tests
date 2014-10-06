export DRBD_TEST_DATA=/usr/share/drbd-test

RSYSLOGD_PORT=5140

declare -a CLEANUP
register_cleanup() {
    CLEANUP[${#CLEANUP[@]}]="$*"
}

cleanup() {
    local cleanup status=$? cleanup_status n file line

    set +e
    for ((n = ${#CLEANUP[@]} - 1; n >= 0; n--)); do
	# Restore the $? variable for each cleanup task
	( exit $status )
	${CLEANUP[n]}
	cleanup_status=$?
	[ $status -ne 0 ] || status=$cleanup_status
    done
}
trap cleanup EXIT

backtrace() {
    local status=$?

    if [ $status -ne 0 ]; then
	( echo
	echo "Backtrace:"
	for ((n = 2; n < ${#BASH_SOURCE[@]}; n++)); do
	    file=${BASH_SOURCE[$n]}
	    line=${BASH_LINENO[$n - 1]}
	    sed -ne "${line}s,^[ \\t]*,  $file:$line: ,p" "$file"
	done ) >&2
    fi
}

tmpdir=$(mktemp -dt)
register_cleanup 'rm -rf "$tmpdir"'

__getopt_level='
    local level=1
    case "$1" in
    -n)
	level=$2
	shift 2
	;;
    -n*)
	level=${1:2}
	shift
	;;
    esac'

verbose() {
    eval "$__getopt_level"
    eval "[ -z \"\$opt_verbose$level\" ]" || echo "$*" >&$stdout_dup
}

debug() {
    eval "$__getopt_level"
    eval "[ -z \"\$opt_debug$level\" ]" || echo "# $*" >&2
}

do_debug() {
    eval "$__getopt_level"
    if eval "[ -n \"\$opt_debug$level\" ]"; then
	echo -n "#"
	printf " %q" "$@"
	echo
     fi >&2
    "$@"
}

mark() {
    local node timestamp where

    timestamp=$(date '+%Y-%m-%dT%H:%M:%S.%N%:z')
    timestamp=${timestamp:0:(-9)}${timestamp:(-6)}
    where=${BASH_SOURCE[1]#*/}:${BASH_LINENO[0]}

    echo "mark $* ($where)" >&$stdout_dup
    for node in "${NODES[@]}"; do
	echo "$timestamp mark $* ($where)" >> $DRBD_LOG_DIR/events-$node
    done
    on "${NODES[@]}" mark "$* ($where)" > /dev/null
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

    verbose -n2 "${procs[*]}: calling $@"
    for proc in "${procs[@]}"; do
	eval "exxe \"\${options[@]}\" -i --logfile=\"\$DRBD_LOG_DIR/exxe-$proc.log\" \"\$@\" >&${COPROC_OUT[$proc]}"
    done
    for proc in "${procs[@]}"; do
	if [ ${#procs[@]} -gt 1 ]; then
	    prefix="--prefix=\"\$proc: \""
	else
	    prefix="--error-prefix=\"\$proc: \""
	fi
	eval "exxe -o $prefix --logfile=\"\$DRBD_LOG_DIR/exxe-$proc.log\" <&${COPROC_IN[$proc]}"
	status=$?
	if [ $status != 0 ]; then
	    verbose "$proc: $1 failed with status code $status"
	    return $status
	fi
    done
}

declare -A NEVER_MATCH

check_node() {
    if [ -z "$1" -o -z "${DEFINED_NODES[$1]}" ]; then
	echo "Unknown node '$1'" >&2
	exit 1
    fi
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
    local -a nodes args=("$@")
    local node have_nodes

    while :; do
	[ "${1:0:1}" != - ] || break
	check_node "$1"
	have_nodes=1
	node=$1
	set -- "$@" \
	    events-$node \
	    --label="$node" \
	    -p .events.pos
	shift
    done
    if [ -n "$have_nodes" ]; then
	verbose "Waiting for event$(printf " %q" "${args[@]}")"
	sync_events node
	do_debug logscan -d $DRBD_LOG_DIR -w \
			 ${opt_silent:+--silent} ${opt_verbose2:+--verbose} \
			 "${NEVER_MATCH[@]/#/-N}" \
			 "$@"
    fi
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
    local -a args=("$@")
    local n1 n2 have_connections

    while :; do
	[ "${1:0:1}" != - ] || break
	n1=${1%%:*}
	n2=${1#*:}
	check_node "$n1"
	check_node "$n2"
	have_connections=1
	set -- "$@" \
	    events-$n1 \
	    --label="$1" \
	    -p .events-connection-$n2.pos \
	    -f "local:[^ :]*:${cfg[$RESOURCE:$1::local]}" \
	    -f "peer:[^ :]*:${cfg[$RESOURCE:$1::peer]}"
	shift
    done
    if [ -n "$have_connections" ]; then
	verbose "Waiting for event$(printf " %q" "${args[@]}")"
	sync_events connection
	do_debug logscan -d $DRBD_LOG_DIR -w \
			 ${opt_silent:+--silent} ${opt_verbose2:+--verbose} \
			 "${NEVER_MATCH[@]/#/-N}" \
			 "$@"
    fi
}

# Match an event on one or more nodes and volumes
#
# USAGE: volume_event {node:volume} [ ... {node:volume} ] {logscan options}
#
volume_event() {
    local -a args=("$@")
    local node volume have_volumes

    while :; do
	[ "${1:0:1}" != - ] || break
	node=${1%:*}
	check_node "$node"
	have_volumes=1
	volume=${1##*:}
	set -- "$@" \
	    events-$node \
	    --label="$1" \
	    -p .events-volume-$volume.pos \
	    -f "volume:$volume"
	shift
    done
    if [ -n "$have_volumes" ]; then
	verbose "Waiting for event$(printf " %q" "${args[@]}")"
	sync_events volume
	do_debug logscan -d $DRBD_LOG_DIR -w \
			 ${opt_silent:+--silent} ${opt_verbose2:+--verbose} \
			 "${NEVER_MATCH[@]/#/-N}" \
			 "$@"
    fi
}

# Match an event on one or more peer devices
#
# Usage: peer_device_event {node1:node2:volume} [ ... {node1:node2:volume} ] {logscan options}
#
peer_device_event() {
    local -a args=("$@")
    local nodes n1 n2 volume have_peer_devices

    while :; do
	[ ${1:0:1} != - ] || break
	nodes=${1%:*}; n1=${nodes%:*}; n2=${nodes#*:}
	check_node "$n1"
	check_node "$n2"
	have_peer_devices=1
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
    if [ -n "$have_peer_devices" ]; then
	verbose "Waiting for event$(printf " %q" "${args[@]}")"
	sync_events peer_device
	do_debug logscan -d $DRBD_LOG_DIR -w \
			 ${opt_silent:+--silent} ${opt_verbose2:+--verbose} \
			 "${NEVER_MATCH[@]/#/-N}" \
			 "$@"
    fi
}

add_forbidden_patterns() {
    local pattern

    for pattern in "$@"; do
	verbose -n3 "Adding forbidden pattern $pattern"
	NEVER_MATCH[$pattern]=$pattern
    done
}

remove_forbidden_patterns() {
    local pattern opt_f

    if [ "$1" = "-f" ]; then
	opt_f=1
	shift
    fi

    for pattern in "$@"; do
	if [ -n "NEVER_MATCH[$pattern]" ]; then
	    verbose -n3 "Removing forbidden pattern $pattern"
	    unset "NEVER_MATCH[$pattern]"
	elif [ -z "$opt_f" ]; then
	    printf "$0: Forbidden pattern '%s' not found\n" "$pattern" >&2
	    exit 2
	fi
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
	( cd $DRBD_LOG_DIR ; do_debug logscan --sync .*.pos )
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
	    DRBD_TEST_VERBOSE=$opt_verbose

	if ! on $node test -d "$DRBD_TEST_DATA"; then
	    echo "Node $node: Directory $DRBD_TEST_DATA does not exist" >&2
	    exit 1
	fi
    done
}

block_connection() {
    local node1=${1%%:*} node2=${1#*:}

    on "$node1" block-connection \
       "${cfg[$RESOURCE:$node1:$node2::local]}" \
       "${cfg[$RESOURCE:$node1:$node2::peer]}"
}

unblock_connection() {
    local node1=${1%%:*} node2=${1#*:}

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

all_connections_except() {
    local connection n
    for connection in "${CONNECTIONS[@]}"; do
	for ((n = 1; n <= $#; n++)); do
	    [ "$connection" != "${!n}" ] || continue 2
	done
	echo "$connection"
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

volumes_on() {
    local node
    for node in "$@"; do
	printf ' %q' ${VOLUMES[$node]}
    done
}

declare _UP_FORBIDDEN=

_up() {
    debug "$FUNCNAME $*"
    # By default, take all nodes up
    [ $# -gt 0 ] || set -- "${NODES[@]}"

    local -a volumes
    local node volume device
    for node in "$@"; do
	# Skip diskless volumes
	for volume in $(volumes_on "$node"); do
	    device=${params[${volume/:/:DISK}]}
	    [ "$device" = none ] || \
		volumes[${#volumes[@]}]=$volume
	done
    done

    on "$@" drbdadm up all
    volume_event ${volumes[@]} -y 'device .* disk:Inconsistent'

    if [ -z "$_UP_FORBIDDEN" ]; then
	# These error states must never occur unless a test case simulates things
	# like node failures, network errors, or disk failures.
	add_forbidden_patterns \
	    'connection:Timeout' \
	    'connection:NetworkFailure' \
	    'connection:ProtocolError' \
	    'connection:BrokenPipe' \
	    'disk:Failed' \
	    'peer-disk:Failed'
	_UP_FORBIDDEN=1
    fi
}

_wait_connected() {
    debug "$FUNCNAME $*"

    # By default, use all connections
    [ $# -ge 1 ] || set -- "${CONNECTIONS[@]}"

    connection_event "$@" -y 'connection .* connection:Connected'
}

_connect() {
    local n1 n2

    debug "$FUNCNAME $*"
    for connection in "$@"; do
	n1=${connection%%:*}
	n2=${connection#*:}
	on "$n1" drbdadm connect $RESOURCE:${params["$n2:FULL_HOSTNAME"]}
	CONNECTIONS["$connection"]=$connection
    done
    connection_event "$@" -y 'connection .* connection:Connecting'
}

_bidir_connect() {
    _connect "$@" $(reverse_connections "$@")
}

_disconnect_nowait() {
    local n1 n2

    debug "$FUNCNAME $*"
    for connection in "$@"; do
	n1=${connection%%:*}
	n2=${connection#*:}
	on "$n1" drbdadm disconnect $RESOURCE:${params["$n2:FULL_HOSTNAME"]}
	unset CONNECTIONS["$connection"]
    done
}

_disconnect() {
    _disconnect_nowait "$@"
    connection_event "$@" -y 'connection .* connection:StandAlone'
}

_force_primary() {
    debug "$FUNCNAME $*"

    # By default, make the first node the primary
    [ $# -ge 1 ] || set -- "${NODES[0]}"

    on "$1" drbdadm primary --force all
    event "$1" -y 'resource .* role:Primary'

    local -a volumes
    local volume device
    # Skip diskless volumes
    for volume in $(volumes_on "$1"); do
	device=${params[${volume/:/:DISK}]}
	[ "$device" = none ] || \
	    volumes[${#volumes[@]}]=$volume
    done
    volume_event ${volumes[@]} -y 'device .* disk:UpToDate'
}

_primary() {
    debug "$FUNCNAME $*"

    # By default, use the first node
    [ $# -ge 1 ] || set -- "${NODES[0]}"

    on "$1" drbdadm primary all
    event "$1" -y 'resource .* role:Primary'
}

_secondary() {
    debug "$FUNCNAME $*"

    # By default, use the first node
    [ $# -ge 1 ] || set -- "${NODES[0]}"

    on "$1" drbdadm secondary all
    event "$1" -y 'resource .* role:Secondary'
}

_initial_resync() {
    debug "$FUNCNAME $*"

    local -a nodes
    # By default, sync from the first node
    [ $# -gt 0 ] || set -- "${NODES[0]}"

    local -a peer_devices
    local node

    # Use unlimited resync bandwidth
    on "${NODES[@]}" drbdadm disk-options --c-min-rate=0 all

    nodes=( $(all_nodes_except "$1") )
    for node in ${NODES[@]}; do
	peer_devices=( "${peer_devices[@]}" ${PEER_DEVICES[$node]} )
    done
    peer_device_event "${peer_devices[@]}" --timeout=300 \
	-y 'peer-device .* peer-disk:UpToDate'
}

_down() {
    debug "$FUNCNAME $*"
    remove_forbidden_patterns -f \
	'connection:Timeout' \
	'connection:BrokenPipe'
    on "${NODES[@]}" drbdadm down all
    event "${NODES[@]}" -y 'destroy resource'
}

_rmmod() {
    debug "$FUNCNAME $*"
    if [ -z "$NO_RMMOD" ]; then
	on "${NODES[@]}" rmmod drbd
    fi
}

_fio() {
    local options=`getopt -o -h --long jobfile:,section: -- "$@"`
    eval set -- "$options"
    local jobfile=$TOP/target/write-verify.fio.in section nodes_volumes
    local node_volume node volume device x job log status

    debug "$FUNCNAME $*"

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
	    job=$DRBD_LOG_DIR/fio-$node${section:+-$section}${x:+-$x}.fio
	    log=$DRBD_LOG_DIR/fio-$node${section:+-$section}${x:+-$x}.log
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
	if [ $status -ne 0 -o -n "$opt_verbose3" ]; then
	    # fio at least sometimes doesn't report errors to standard error ...
	    cat "$log"
	    [ $status -eq 0 ] || exit $status
	fi
    done
}

__devs_mask() {
    local node=$1 devs=0 minor
    for volume in ${cfg[$RESOURCE:$node::volumes]}; do
	minor=${cfg[$RESOURCE:$node:$volume::minor]}
	(( devs |= (1 << minor) ))
    done
    echo $devs
}

declare -A FAULTS_ENABLED

_enable_faults() {
    local node devs

    local options=`getopt -o h --long faults:,rate: -- "$@"`
    eval set -- "$options"
    options=  # reuse
    while :; do
	case "$1" in
	--faults|--rate)
	    options="$options $1=$2"
	    shift
	    ;;
	--)
	    shift
	    break
	    ;;
	esac
    done

    [ $# -gt 0 ] || set -- "${NODES[@]}"

    for node in "$@"; do
	devs=$(__devs_mask "$node")
	on "$node" enable-faults $options --devs=$devs
	FAULTS_ENABLED[node]=1
    done
}

_disable_faults() {
    local node devs

    [ $# -gt 0 ] || set -- "${NODES[@]}"

    for node in "$@"; do
	devs=$(__devs_mask "$node")
	on "$node" disable-faults --devs=$devs
	unset FAULTS_ENABLED[node]
    done
}

cleanup_faults() {
    local node

    for node in "${!FAULTS_ENABLED[@]}"; do
	devs=$(__devs_mask "$node")
	on "$node" disable-faults --devs=$devs
	unset FAULTS_ENABLED[node]
    done
}

register_cleanup cleanup_faults

# Pass the config file generated by setup() through a filter, and update
# the config file on all test nodes.  When called with 'cat' as argument,
# restore the original config file.
change_config() {
    local conf node version

    for conf in $DRBD_LOG_DIR/drbd*.conf; do
	if ! [ -e "$conf.orig" ]; then
	    cp "$conf" "$conf.orig"
	fi
	"$@" < "$conf.orig" > "$conf"
	for node in "${NODES[@]}"; do
	    version=${params["$node:DRBD_MAJOR_VERSION"]}
	    on -p $node install-config < $DRBD_LOG_DIR/drbd${version}.conf
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

    debug "$FUNCNAME $*"

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

# The errexit option is only effective in basic commands, not in boolean
# expressions or conditionals.  Because of that, we cannot simply assert that a
# command fails with "! command" or similar.  This limitation of errexit is by
# design and cannot simply be "fixed" in bash.
#
# The _expect_failure() function can be used as a workaround -- unfortunately,
# this also only works when _expect_failure is used as a basic command.
#
try() {
    set -o errtrace
    trap 'return $?' ERR
    trap 'trap - ERR; set +o errtrace' RETURN
    "$@"
}

_expect_failure() {
    local status errexit_on

    if [ $- != ${-/e} ]; then
	errexit_on=1
	set +o errexit
    fi
    try "$@"
    status=$?
    [ -z "$errexit_on" ] || set -o errexit
    (( !status ))
}

# Create a background process with an open file descriptor to write to that
# process.  Returns the file descriptor number in the variable named $1, and
# the pid of the background process in the variable named $2.  The process
# and its arguments are defined in $3 ...
bg_filter() {
    local wr=$1 pid=$2 fifo n=10 wr_fd

    shift 2
    while :; do
	fifo=$(mktemp -u ${TMPDIR:-/tmp}/${0##*/}.XXXXXXXXXX)
	! mkfifo "$fifo" 2> /dev/null || break
	if ! $((n--));  then
	    ! mkfifo "$fifo" || break
	    exit 1
	fi
    done
    "$@" < $fifo &
    exec {wr_fd}> "$fifo"
    rm -f "$fifo"
    eval "$wr=\$wr_fd; $pid=$!"
}

# Expect a command to fail.
# Prefix standard and error output with '> '.
expect_failure() {
    local status=0 out out_pid
    local errexit_on

    # because writing to the pipe is not line buffered, we will not immediately
    # see the output.  Also, it makes no sense to keep standard output and
    # standard error separated -- the result wouldn't be in a reasonable order.

    [ $- = ${-/e} ] || errexit_on=1
    verbose -n2 "Expecting '$*' to fail"
    bg_filter out out_pid \
	sed -e 's:^:> :'
    set +o errexit
    eval "_expect_failure \"\$@\" >&$out $stdout_dup>&$out 2>&$out"
    status=$?
    eval exec "$out>&-"
    wait $out_pid
    [ -z "$errexit_on" ] || set -o errexit
    (( status ))
}
