# All the defined nodes
declare -a NODES

# We store all global settings in array[_].
node=_

# Keep track of how many parameter arrays have already been
# defined in param_count[array] (e.g., param_count[DISK] is 2
# if DISK1 and DISK2 have been defined).  We reset param_count
# for each new node so that the global settings can be overridden.

declare -A params
declare -A param_count

new_node() {
    local name

    node=$1
    NODES=("${NODES[@]}" "$node")
    param_count=()

    # Copy the global settings from params[_:*] to params[$node:*]
    for name in "${!params[@]}"; do
	case "$name" in
	_:*)
	    params["$node:${name#_:}"]="${params["$name"]}"
	    ;;
	esac
    done
}

set_node_param() {
    # Strip leading two dashes, replace dashes with underscores, and convert to
    # uppercase
    local name=${1#--}; name=${name//-/_}; name=${name^^}
    local node=$2 value=$3
    params["$node:$name"]="$value"
}

add_node_param() {
    # Strip leading two dashes, replace dashes with underscores, and convert to
    # uppercase
    local name=${1#--}; name=${name//-/_}; name=${name^^}
    local node=$2 value=$3
    local count=$((++param_count[$name]))
    params["$node:$name$count"]="$value"
}
