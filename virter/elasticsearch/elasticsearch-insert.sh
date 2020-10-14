#!/bin/bash

set -e

if [ "$#" -ne 3 ]; then
	echo "Usage: $0 elasticsearch_url results_file ci_tests_file"; exit 1
fi

url="$1"
results_file="$2"
ci_tests_file="$3"

date="$(cat $results_file | jq -r .time | head -1)"

if [ -z "$date" ]; then
	echo "No data to insert"; exit 1
fi

# the index should uniquely identify the test suite run because _id is only
# unique within a test suite run
index="drbd-$(date --date=$date --utc +%Y%m%d%H%M%S)"

echo "Using index: '$index'"

index_exists=false
curl -f "$url/$index?pretty" --head && index_exists=true

if [ "$index_exists" = false ]; then
	curl -f "$url/$index?pretty" -XPUT -H 'Content-Type: application/json' --data '
	{
		"mappings": {
			"properties": {
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
		.name_count = $nc |
		.ci_enabled = ('"$ci_tests"' | index($nc) != null))
][]
' | curl -f "$url/$index/_bulk?pretty" -H "Content-Type: application/x-ndjson" -XPOST --data-binary @-
