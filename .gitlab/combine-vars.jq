# Combine an array of objects into an array of entries with .key and .value.
# The keys of the input objects become the .key values in the output.
# The values are combined according to the key, so that there is one entry in
# the output for each distinct key in the input.

# Combine an array of entries with .key and .value into one entry.
# .key in the output is from the first entry.
# .value in the output is combined according to the name of the key.
def combine_same_key: {key: .[0].key, values: map(.value)} |
    {key: .key, value: (if .key == "VMSHED_ARGS"
        then .values | join(" ")
        else .values[-1]
        end)};

map(to_entries) |
    flatten(1) |
    group_by(.key) |
    map(combine_same_key)
