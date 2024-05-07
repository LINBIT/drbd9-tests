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
index="$2-g1"

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

curl -XPOST "$url/_reindex?pretty&requests_per_second=1000" -H 'Content-Type: application/json' -d'
{
  "source": {
    "index": "'$index_old'"
  },
  "dest": {
    "index": "'$index'"
  },
  "script": {
    "source": "ctx._source.series = ctx._source.drbd9_tests_ref == \"master\" && ( ctx._source.drbd_version == \"9.0.0.latest\" || ctx._source.drbd_version == \"9.1.0.latest\" || ctx._source.drbd_version == \"9.2.0.latest\" ) && (!ctx._source.containsKey(\"drbd_version_other\") || ctx._source.drbd_version_other == \"\") ? \"stability\" : \"none\""
  }
}
'
