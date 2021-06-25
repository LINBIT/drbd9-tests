#!/bin/bash

set -e

die() {
	echo "$1" >&2
	exit 1
}

[ "$#" -ne 3 ] && die "Usage: $0 elasticsearch_url results_file ci_tests_file"

url="$1"
results_file="$2"
ci_tests_file="$3"

[ -z "$CI_JOB_ID" ] && die "Missing \$CI_JOB_ID"
[ -z "$DRBD_VERSION" ] && die "Missing \$DRBD_VERSION"
[ -z "$DRBD_UTILS_VERSION" ] && die "Missing \$DRBD_UTILS_VERSION"
[ -z "$DRBD9_TESTS_VERSION" ] && die "Missing \$DRBD9_TESTS_VERSION"
[ -z "$DRBD9_TESTS_REF" ] && die "Missing \$DRBD9_TESTS_REF"

date="$(cat $results_file | jq -r .time | head -1)"
[ -z "$date" ] && die "No data to insert"

# the index should uniquely identify the test suite run because _id is only
# unique within a test suite run
index="drbd-$(date --date=$date --utc +%Y%m%d%H%M%S)-$CI_JOB_ID"

echo "Using index: '$index'"

index_exists=false
curl -f "$url/$index?pretty" --head && index_exists=true

if [ "$index_exists" = false ]; then
	curl -f "$url/$index?pretty" -XPUT -H 'Content-Type: application/json' --data '
	{
		"mappings": {
			"properties": {
				"job_id": { "type": "keyword" },
				"drbd_version": { "type": "keyword" },
				"drbd_utils_version": { "type": "keyword" },
				"drbd9_tests_version": { "type": "keyword" },
				"drbd9_tests_ref": { "type": "keyword" },
				"time": { "type": "date" },
				"name": { "type": "keyword" },
				"vm_count": { "type": "integer" },
				"variant": { "type": "keyword" },
				"base_images": { "type": "keyword" },
				"status": { "type": "keyword" },
				"score": { "type": "integer" },
				"duration_ns": { "type": "long" },
				"name_count": { "type": "keyword" },
				"ci_enabled": { "type": "boolean" }
			}
		}
	}
	'
fi

ci_tests="$(cat "$ci_tests_file" | rq -t | jq -c '.tests | to_entries | map(.key + "-" + (.value.vms[] | tostring))')"

echo "CI Tests: $ci_tests"

cat "$results_file" | jq -c '
[
	{ index: { _id: .id } },
	(del(.id) |
		(.name + "-" + (.vm_count | tostring)) as $nc |
		. + {
			job_id: "'"$CI_JOB_ID"'",
			drbd_version: "'"$DRBD_VERSION"'",
			drbd_utils_version: "'"$DRBD_UTILS_VERSION"'",
			drbd9_tests_version: "'"$DRBD9_TESTS_VERSION"'",
			drbd9_tests_ref: "'"$DRBD9_TESTS_REF"'",
			name_count: $nc,
			ci_enabled: ('"$ci_tests"' | index($nc) != null),
		}
	)
][]
' | curl -f "$url/$index/_bulk?pretty" -H "Content-Type: application/x-ndjson" -XPOST --data-binary @-
