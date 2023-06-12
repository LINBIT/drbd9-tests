#!/bin/bash

set -e

die() {
	echo "$1" >&2
	exit 1
}

[ "$#" -ne 2 ] && die "Usage: $0 elasticsearch_url results_file"

url="$1"
results_file="$2"

[ -z "$CI_JOB_ID" ] && die "Missing \$CI_JOB_ID"
[ -z "$DRBD_TESTS_DIR" ] && die "Missing \$DRBD_TESTS_DIR"
[ -z "$DRBD_TEST_SERIES" ] && die "Missing \$DRBD_TEST_SERIES"
[ -z "$DRBD_VERSION" ] && die "Missing \$DRBD_VERSION"
[ -z "$DRBD_UTILS_VERSION" ] && die "Missing \$DRBD_UTILS_VERSION"
[ -z "$DRBD9_TESTS_VERSION" ] && die "Missing \$DRBD9_TESTS_VERSION"
[ -z "$DRBD9_TESTS_REF" ] && die "Missing \$DRBD9_TESTS_REF"

index="drbd-$(date --utc +%Y%m)"

echo "Using index: '$index'"

index_exists=false
curl -f "$url/$index?pretty" --head && index_exists=true

if [ "$index_exists" = false ]; then
	curl -f "$url/$index?pretty" -XPUT -H 'Content-Type: application/json' --data '
	{
		"mappings": {
			"properties": {
				"job_id": { "type": "keyword" },
				"series": { "type": "keyword" },
				"test_run_id": { "type": "keyword" },
				"drbd_version": { "type": "keyword" },
				"drbd_version_other": { "type": "keyword" },
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

ci_tests_config="$(virter/vmshed_tests_generator.py --tests-dir "$DRBD_TESTS_DIR" --selection ci --drbd-version "$DRBD_VERSION")"
ci_tests="$(printf '%s' "$ci_tests_config" | rq -t | jq -c '.tests | to_entries | map(.key + "-" + (.value.vms[] | tostring))')"

echo "CI Tests: $ci_tests"

cat "$results_file" | jq -c '
select( .status != "SKIPPED" and .status != "CANCELED" and .status != "ERROR" ) |
{ index: { _id: ( "'"$CI_JOB_ID-"'" + .id ) } },
(
	(.name + "-" + (.vm_count | tostring)) as $nc |
	del(.id) + {
		job_id: "'"$CI_JOB_ID"'",
		series: "'"$DRBD_TEST_SERIES"'",
		test_run_id: .id,
		drbd_version: "'"$DRBD_VERSION"'",
		drbd_version_other: "'"$DRBD_VERSION_OTHER"'",
		drbd_utils_version: "'"$DRBD_UTILS_VERSION"'",
		drbd9_tests_version: "'"$DRBD9_TESTS_VERSION"'",
		drbd9_tests_ref: "'"$DRBD9_TESTS_REF"'",
		name_count: $nc,
		ci_enabled: ('"$ci_tests"' | index($nc) != null),
	}
)
' | curl -f "$url/$index/_bulk" -H "Content-Type: application/x-ndjson" -XPOST --data-binary @- > /dev/null
