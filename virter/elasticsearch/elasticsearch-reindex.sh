#!/bin/bash

# Warning: This script is not maintained. It is provided as a starting point for development.
#
# Apply changes to documents in Elasticsearch by copying them to a new index.

set -e

die() {
	echo "$1" >&2
	exit 1
}

[ "$#" -ne 2 ] && die "Usage: $0 elasticsearch_url index_old"

url="$1"
index_old="$2"
index="$2-g2"

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
				"ci_enabled": { "type": "boolean" },
				"rdma_ci_enabled": { "type": "boolean" }
			}
		}
	}
	'
fi

rdma_ci_tests_config="$(virter/vmshed_tests_generator.py --selection rdma_ci)"
rdma_ci_tests="$(printf '%s' "$rdma_ci_tests_config" | rq -t | jq -c '.tests | to_entries | map(.key + "-" + (.value.vms[] | tostring))')"

echo "RDMA CI Tests: $rdma_ci_tests"

# Submit the reindex asynchronously to avoid HTTP proxy timeouts on long
# running operations. Elasticsearch returns a task ID which we poll below.
task_id="$(curl -f -XPOST "$url/_reindex?wait_for_completion=false&requests_per_second=1000" -H 'Content-Type: application/json' -d'
{
  "source": {
    "index": "'$index_old'"
  },
  "dest": {
    "index": "'$index'"
  },
  "script": {
    "source": "ctx._source.rdma_ci_enabled = params.rdma_ci_tests.contains(ctx._source.name + \"-\" + ctx._source.vm_count); if (ctx._source.series == \"stability\" && ctx._source.variant == \"rdma\") { ctx._source.series = \"stability-rdma\" }",
    "params": {
      "rdma_ci_tests": '"$rdma_ci_tests"'
    }
  }
}
' | jq -r '.task')"

if [ -z "$task_id" ] || [ "$task_id" = "null" ]; then
	die "Failed to submit reindex task"
fi

echo "Reindex task ID: $task_id"

while true; do
	response="$(curl -f -s "$url/_tasks/$task_id")"
	completed="$(printf '%s' "$response" | jq -r '.completed')"
	status="$(printf '%s' "$response" | jq -c '.task.status')"
	echo "Status: $status"

	if [ "$completed" = "true" ]; then
		failures="$(printf '%s' "$response" | jq -c '.response.failures')"
		if [ "$failures" != "[]" ]; then
			echo "Reindex failures: $failures" >&2
			exit 1
		fi
		echo "Reindex completed"
		break
	fi

	sleep 10
done
