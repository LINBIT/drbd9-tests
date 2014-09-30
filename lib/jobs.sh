analyze_job() {
    local job=$1 result status

    result=$(
	bash -c '
	# Ignore unknown commands here
	command_not_found_handle() {
	    :
	}
	want_nodes=
	source "'"$job"'"
	echo "want_nodes=$want_nodes"
	' "$job"
    )
    status=${PIPESTATUS[0]}
    [ $status != 0 ] || eval "$result"
    return $status
}

run_job() {
    local job=$1 want_nodes=$2 n status
    local -a nodes

    for ((n = 0; n < want_nodes; n++)); do
	nodes[${#nodes[@]}]=${NODES[n]}
    done

    echo -n "Running job $job on $want_nodes nodes - "
    err=$(bash -c '
	export PATH='"$TOP/tests"':$PATH
	source "'"$job"'"
	' "$job" "${pass_through[@]}" --logdir=$LOG_DIR/${job##*/} "${nodes[@]}" > /dev/null 2>&1)
    status=${PIPESTATUS[0]}
    [ -z "$err" ] || echo "$err" > $LOG_DIR/${job##*/}/test.err
    if [ $status = 0 ]; then
	echo "succeeded"
    else
	echo "FAILED"
    fi
    return $status
}
