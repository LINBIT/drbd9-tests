#!/bin/bash

# Delete test runs by ID from a file. This is useful for removing incorrect
# failures from the test results. Example:
#
# # Extract test results archive
# cd tests-out/log/
# grep 'Failed to build image: failed to run container provisioning: failed to extract tar archive:' */test.log | sed 's#/.*##' > to_delete
# ./virter/elasticsearch/elasticsearch-delete-runs.sh https://es01.at.linbit.com drbd-202403 955687 to_delete

set -e

die() {
	echo "$1" >&2
	exit 1
}

[ "$#" -ne 4 ] && die "Usage: $0 elasticsearch_url index job_id delete_ids_file"

url="$1"
index="$2"
job_id="$3"
delete_ids_file="$4"

cat "$delete_ids_file" | jq --raw-input --compact-output '
{ delete : { _id : ("'"$job_id"-'" + .) } }
' | curl -f "$url/$index/_bulk?pretty" -H "Content-Type: application/x-ndjson" -XPOST --data-binary @-
