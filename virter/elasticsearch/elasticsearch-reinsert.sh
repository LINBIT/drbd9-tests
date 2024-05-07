#!/bin/bash

# Warning: This script is not maintained. It is provided as a starting point for development.
#
# Insert documents extracted from Elasticsearch back into Elasticsearch, applying changes.

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
				"test_run_id": { "type": "keyword" },
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

cat "$source_data" | jq -c '
.hits.hits[] |
._index as $index |
._id as $id |
._source |
{ index: { _id: ( $index + "-" + $id ) } },
(
	(.name + "-" + (.vm_count | tostring)) as $nc |
	del(.variant) + {
		test_run_id: $id,
		variant: "tcp",
	}
)
' | curl -f "$url/$index/_bulk" -H "Content-Type: application/x-ndjson" -XPOST --data-binary @- > /dev/null
