#! /bin/bash

# FIXME: Check for ntp on the test nodes and the client

HERE=${0%/*}
. $HERE/param.sh
. $HERE/client.sh
set -e

# All the defined connections
declare -A CONNECTIONS

instantiate_template() {
    local I=("${INSTANTIATE[@]}") option n
    local node_name node name

    for node in "${NODES[@]}"; do
	I[${#I[@]}]=--node=${params["$node:FULL_HOSTNAME"]}
	for node_name in "${!params[@]}"; do
	    node2=${node_name%%:*}
	    name=${node_name#*:}
	    [ "$node2" = "$node" ] || continue
	    case "$name" in
	    FULL_HOSTNAME | CONSOLE)
		;;
	    *)
		option=${name//[0-9]}; option=${option//_/-}; option=${option,,}
		I[${#I[@]}]="--$option=${params[$node_name]}"
		;;
	    esac
	done
    done
    I[${#I[@]}]=$opt_template
    do_debug $HERE/instantiate-template "${I[@]}"
}

cleanup_events() {
    local -a pids

    shopt -s nullglob
    set -- run/events-*.pid run/console-*.pid
    if [ $# -gt 0 ]; then
	pids=( $(cat "$@") )
	kill "${pids[@]}" 2> /dev/null
	# FIXME: got "kill: (27979) - No such process" here once --
	# how did this happen?
	# FIXME: kill and wait sometimes spit out job control messages like
	# "$PID Terminated ..." even in a non-interactive shell.
	wait "${pids[@]}" 2> /dev/null
	rm -f "$@""$@"
    fi
}

kill_rsyslogd() {
    kill $(cat run/rsyslogd.pid)
}

listen_to_events() {
    local resource=$1
    shift
    for node in "$@"; do
	mkdir -p $DRBD_TEST_JOB
	ssh -q root@$node drbdsetup events "$resource" \
		--statistics \
		--timestamps \
		> $DRBD_TEST_JOB/events-$node &
	echo $! > run/events-$node.pid
    done

    register_cleanup cleanup_events
}

write_status_file() {
    local status=$?

    if [ $status = 0 ]; then
	touch $DRBD_TEST_JOB/test.ok
    else
	echo $status > $DRBD_TEST_JOB/test.failed
    fi
}

setup_usage() {
    [ $1 -eq 0 ] || exec >&2
    cat <<EOF
USAGE: ${0##*/} [options] ...
EOF
    exit $1
}

declare opt_debug= opt_verbose= opt_cleanup=always stdout_dup

setup() {
    local options

    options=`getopt -o -vh --long job:,volume-group:,resource:,node:,device:,disk:,meta:,node-id:,address:,no-create-md,debug,port:,template:,cleanup:,min-nodes:,console:,vconsole,only-setup,help,verbose -- "$@"` || setup_usage 1
    eval set -- "$options"

    declare opt_resource= opt_create_md=1 opt_job= opt_volume_group=scratch
    declare opt_min_nodes=2 opt_only_setup= opt_vconsole= job_symlink=
    declare opt_template=m4/template.conf.m4
    declare -a INSTANTIATE
    local logfile

    while :; do
	case "$1" in
	--port)
	    INSTANTIATE=("${INSTANTIATE[@]}" "$1=$2")
	    ;;
	esac

	case "$1" in
	-h|--help)
	    setup_usage 0
	    ;;
	--debug)
	    opt_debug=1
	    ;;
	-v|--verbose)
	    opt_verbose=1
	    ;;
	--job)
	    opt_job=$2
	    shift
	    ;;
	--volume-group)
	    opt_volume_group=$2
	    shift
	    ;;
	--resource)
	    opt_resource=$2
	    shift
	    ;;
	--template)
	    opt_template=$2
	    ;;
	--node)
	    new_node "$2"
	    shift
	    ;;
	--disk|--meta)
	    add_node_param "$1-size" "$node" "$2"
	    shift
	    ;;
	--device)
	    add_node_param "$1" "$node" "$2"
	    shift
	    ;;
	--node-id|--address|--volume-group)
	    set_node_param "$1" "$node" "$2"
	    shift
	    ;;
	--port)
	    shift
	    ;;
	--no-create-md)
	    opt_create_md=
	    ;;
	--cleanup)
	    case "$2" in
	    always|never|success)
		opt_cleanup=$2
		;;
	    *)
		setup_usage 1
		;;
	    esac
	    shift
	    ;;
	--min-nodes)
	    opt_min_nodes=$2
	    shift
	    ;;
	--only-setup)
	    opt_only_setup=1
	    opt_cleanup=never
	    ;;
	--console)
	    set_node_param "$1" "$node" "$2"
	    shift
	    ;;
	--vconsole)
	    opt_vconsole=1
	    ;;
	--)
	    shift
	    break
	    ;;
	*)
	    new_node "$1"
	    ;;
	esac
	shift
    done

    unset_all_node_params

    if [ -n "$opt_vconsole" ]; then
	for node in "${NODES[@]}"; do
	    [ -z "${params[$node:CONSOLE]}" ] || continue
	    # FIXME: sudo doesn't seem right here ...
	    set -- $(sudo virsh ttyconsole "$node")
	    if [ -n "$1" ]; then
		sudo chmod g+r "$1"
		params[$node:CONSOLE]="$1"
	    fi
	done
    fi

    if [ -n "$opt_min_nodes" ]; then
	[ ${#NODES[@]} -ge $opt_min_nodes ] ||
	    skip_test "Test case requires $opt_min_nodes or more nodes"
    fi

    if [ -z "$opt_job" ]; then
	opt_job=${0##*test-}-$(date '+%Y%m%d-%H%M%S')
	job_symlink=${0##*test-}-latest
    fi
    [ ${#NODES} -gt 0 ] || setup_usage 1
    if [ -z "$opt_resource" ]; then
	opt_resource=$opt_job
    fi
    INSTANTIATE=("${INSTANTIATE[@]}" "--resource=$opt_resource")
    export DRBD_TEST_JOB=$opt_job
    export EXXE_TIMEOUT=30
    export LOGSCAN_TIMEOUT=30

    echo "Logging to directory $DRBD_TEST_JOB"
    mkdir -p "$DRBD_TEST_JOB"
    rm -f $DRBD_TEST_JOB/*.pos $DRBD_TEST_JOB/test.log
    if [ -n "$job_symlink" ]; then
	rm -f "$job_symlink"
	ln -s "$DRBD_TEST_JOB" "$job_symlink"
    fi

    register_cleanup write_status_file

    exec > >(tee -a $DRBD_TEST_JOB/test.log)
    register_cleanup kill $!
    exec 2> >(tee -a $DRBD_TEST_JOB/test.log >&2)
    register_cleanup kill $!

    # Duplicate stdout so that we can write to it even when file descriptor
    # one has been redirected
    exec {stdout_dup}>&1

    local console
    for node_name in "${!params[@]}"; do
	node=${node_name%%:*}
	name=${node_name#*:}
	case "$name" in
	CONSOLE)
	    console=${params["$node_name"]}
	    if ! [ -r "$console" ]; then
		echo "Cannot read from console $console of node $node" >&2
		exit 1
	    fi
	    verbose "$node: capturing console $console"
	    cat "$console" > $DRBD_TEST_JOB/console-$node.log &
	    echo $! > run/console-$node.pid
	    ;;
	esac
    done

    connect_to_nodes "${NODES[@]}"

    if [ -n "$EXXE_TIMEOUT" ]; then
	on "${NODES[@]}" timeout $EXXE_TIMEOUT
    fi
    if [ "$opt_cleanup" = "always" ]; then
	on "${NODES[@]}" onexit cleanup
    fi

    mkdir -p run

    listen_to_events "$opt_resource" "${NODES[@]}"

    for node in "${NODES[@]}"; do
	logfile=$DRBD_TEST_JOB/$node.log
	rm -f $logfile
    done

    local hostname=$(hostname -f)

    sed -e "s:@PORT@:$RSYSLOGD_PORT:g" \
	-e "s:@SYSLOG_DIR@:$PWD/$DRBD_TEST_JOB:g" \
	-e "s:@SERVER@:${hostname%%.*}:g" \
	rsyslog.conf.in \
	> run/rsyslog.conf
    rsyslogd -c5 -i $PWD/run/rsyslogd.pid -f $PWD/run/rsyslog.conf
    register_cleanup kill_rsyslogd

    for node in "${NODES[@]}"; do
	on $node rsyslogd $hostname $RSYSLOGD_PORT $node
	on $node logger "Setting up test job $DRBD_TEST_JOB"
    done

    for node in "${NODES[@]}"; do
	# FIXME: If the hostname on the remote host does not match
	# the name used here, we will loop here forever.  Fix this
	# by configuring rsyslog on the node to use the right name?
	logfile=$DRBD_TEST_JOB/$node.log
	i=0
	while :; do
	    (( ++i % 10 )) || echo "Waiting for $logfile to appear ..."
	    [ -e $logfile ] && break
	    sleep 0.2
	done
    done

    # Replace the node names we were passed with the names under which the nodes
    # know themselves: drbd depends on this in its config files.
    for node in "${NODES[@]}"; do
	hostname=$(on $node hostname -f)
	if [ "$hostname" != "$node" ]; then
	    echo "$node: full hostname = $hostname"
	fi
	params["$node:FULL_HOSTNAME"]="$hostname"
    done

    # FIXME: The disks could be created in parallel ...
    local disk device have_disks
    for node_name in "${!params[@]}"; do
	node=${node_name%%:*}
	name=${node_name#*:}
	case "$name" in
	DISK_SIZE*|META_SIZE*)
	    size=${params["$node_name"]}
	    disk=${name/_SIZE}
	    device=$(on $node create-disk \
		--job=$opt_job \
		--volume-group=$opt_volume_group \
		--size=$size $DRBD_TEST_JOB-${disk,,})
	    verbose "$node: disk $device created ($size)"
	    params["$node:$disk"]="$device"
	    have_disks=1
	    unset params["$node_name"]
	    ;;
	esac
    done

    instantiate_template > $DRBD_TEST_JOB/drbd.conf

    for node in "${NODES[@]}"; do
	on -p $node install-config < $DRBD_TEST_JOB/drbd.conf
    done
    on "${NODES[@]}" register-cleanup -t drbdsetup down "$DRBD_TEST_JOB"

    if [ -n "$opt_create_md" -a -n "$have_disks" ]; then
	for node in "${NODES[@]}"; do
	    msg=$(on $node drbdadm -- --force create-md "$opt_resource" 2>&1) || status=$?
	    if [ -n "$status" ]; then
		echo "$msg" >&2
		exit $status
	    fi
	done
    fi

    for n1 in "${NODES[@]}"; do
	for n2 in "${NODES[@]}"; do
	    [ "$n1" != "$n2" ] || continue
	    CONNECTIONS["$n1:$n2"]="$n1:$n2"
	done
    done

    [ -z "$opt_only_setup" ] || exit 0
    #if [ "$opt_cleanup" = "success" ]; then
    #	on "${NODES[@]}" cleanup
    #fi
}
