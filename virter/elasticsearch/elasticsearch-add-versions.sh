#!/bin/bash

set -e

die() {
	echo "$1" >&2
	exit 1
}

[ "$#" -ne 2 ] && die "Usage: $0 elasticsearch_url index"

url="$1"
index="$2"

[ -z "$DRBD_VERSION" ] && die "Missing \$DRBD_VERSION"
[ -z "$DRBD_UTILS_VERSION" ] && die "Missing \$DRBD_UTILS_VERSION"
[ -z "$DRBD9_TESTS_VERSION" ] && die "Missing \$DRBD9_TESTS_VERSION"

curl -f "$url/$index/_mapping?pretty" -XPUT -H 'Content-Type: application/json' --data '
{
	"properties": {
		"drbd_version": { "type": "constant_keyword", "value": "'"$DRBD_VERSION"'" },
		"drbd_utils_version": { "type": "constant_keyword", "value": "'"$DRBD_UTILS_VERSION"'" },
		"drbd9_tests_version": { "type": "constant_keyword", "value": "'"$DRBD9_TESTS_VERSION"'" }
	}
}
'
