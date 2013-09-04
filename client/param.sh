# All the defined nodes
declare -a NODES

# We store all global settings in array[_].
node=_

# Keep track of how many parameter arrays have already been
# defined in param_count[array] (e.g., param_count[DISK] is 2
# if DISK1 and DISK2 have been defined).  We reset param_count
# for each new node so that the global settings can be overridden.

declare -A param_count

new_node() {
    local array

    node=$1
    shift
    NODES=("${NODES[@]}" "$node")
    param_count=()

    # Copy the global settings from array[_] to array[$node]
    for array in "$@"; do
	eval "[ -z \"\${$array[_]+x}\" ] || $array[\$node]=\"\${$array[_]}\""
    done
}

set_node_param() {
    local name=$1 node=$2 value=$3

    declare -g -A "$name"
    eval "$name[\$node]=$value"
}

add_node_param() {
    # Strip leading two dashes, replace dashes with underscores, and convert to
    # uppercase
    local name=${1#--}; name=${name//-/_}; name=${name^^}
    local node=$2 value=$3
    local count=$((++param_count[$name]))

    set_node_param "$name$count" "$node" "$value"
}
