#!/bin/bash

# Delete all results from a job from Elasticsearch.
#
# Example:
# ./virter/elasticsearch/elasticsearch-delete-job.sh https://es01.at.linbit.com drbd-202405 1005752

set -e

die() {
	echo "$1" >&2
	exit 1
}

[ "$#" -ne 3 ] && die "Usage: $0 elasticsearch_url index job_id"

url="$1"
index="$2"
job_id="$3"

curl -f "$url/$index/_delete_by_query?pretty&max_docs=10000" -H 'Content-Type: application/json' -XPOST -d'
{
  "query": {
    "term": {
      "job_id": {
        "value": "'"$job_id"'"
      }
    }
  }
}
'
