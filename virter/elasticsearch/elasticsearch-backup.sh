#!/bin/bash

# Download an index from Elasticsearch to a local NDJSON file.
#
# The output contains one hit per line, matching the format consumed by
# elasticsearch-reinsert.sh.

set -e

die() {
	echo "$1" >&2
	exit 1
}

[ "$#" -ne 3 ] && die "Usage: $0 elasticsearch_url index output_file"

url="$1"
index="$2"
outfile="$3"

: > "$outfile"

resp="$(curl -sf "$url/$index/_search?scroll=5m&size=1000" \
	-H 'Content-Type: application/json' \
	-d '{"query":{"match_all":{}}}')"
scroll_id="$(printf '%s' "$resp" | jq -r '._scroll_id')"

total="$(printf '%s' "$resp" | jq -r '.hits.total.value')"
echo "Backing up $total documents from '$index' to '$outfile'"

count=0
while :; do
	hits="$(printf '%s' "$resp" | jq -c '.hits.hits[]')"
	[ -z "$hits" ] && break
	printf '%s\n' "$hits" >> "$outfile"
	count=$(( count + $(printf '%s\n' "$hits" | wc -l) ))
	echo "Progress: $count / $total"
	resp="$(curl -sf "$url/_search/scroll" \
		-H 'Content-Type: application/json' \
		-d "{\"scroll\":\"5m\",\"scroll_id\":\"$scroll_id\"}")"
done

curl -sf -XDELETE "$url/_search/scroll" \
	-H 'Content-Type: application/json' \
	-d "{\"scroll_id\":\"$scroll_id\"}" > /dev/null

echo "Done"
