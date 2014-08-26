global {
	usage-count no;
}

resource RESOURCE {
m4_foreachq(`NODE', m4_quote(NODES),
`	on HOSTNAME(NODE) {
m4_foreachq(`VOLUME', m4_quote(VOLUMES),
`		volume VOLUME {
			device DEVICE(NODE);
			disk DISK(NODE);
			meta-disk m4_default(META(NODE),`internal');
		}
')m4_dnl
m4_ifelse(DRBD_MAJOR_VERSION, `8', `',
`		node-id NODE_ID(NODE);
')m4_dnl
		address ADDRESS(NODE);
	}
')m4_dnl
m4_ifelse(DRBD_MAJOR_VERSION, `8', `',
`	connection-mesh {
		hosts m4_join(` ', NODES);
	}
')m4_dnl
}
