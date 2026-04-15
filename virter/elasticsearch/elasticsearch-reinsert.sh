#!/bin/bash

# Warning: This script is not maintained. It is provided as a starting point for development.
#
# Insert documents into Elasticsearch from a local NDJSON backup (as produced
# by elasticsearch-backup.sh), optionally applying changes.

set -e

die() {
	echo "$1" >&2
	exit 1
}

[ "$#" -ne 3 ] && die "Usage: $0 elasticsearch_url source_data target_index"

url="$1"
source_data="$2"
index="$3"

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

# Input is NDJSON: one hit per line, each a {_index, _id, _source, ...} object.
# Transform each hit into a bulk action/document pair. Add any _source
# transformations below as needed.
jq -c '
._index as $src_index |
._id as $id |
{ index: { _id: ( $src_index + "-" + $id ) } },
._source
' "$source_data" | curl -f "$url/$index/_bulk" -H "Content-Type: application/x-ndjson" -XPOST --data-binary @- > /dev/null
