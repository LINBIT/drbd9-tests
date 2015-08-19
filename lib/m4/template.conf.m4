global {
	usage-count no;
}

resource RESOURCE {
m4_foreachq(`NODE', m4_quote(NODES),
`	on HOSTNAME(NODE) {
m4_foreachq(`VOLUME', m4_quote(VOLUMES),
`m4_dnl
m4_define(`a_disk',DISK(NODE))m4_dnl
m4_define(`a_meta',META(NODE))m4_dnl
		volume VOLUME {
			device DEVICE(NODE);
			disk a_disk;
m4_ifelse(a_disk, `none', `',
`			meta-disk m4_default(a_meta,`internal');
')m4_dnl
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
	net {
		NET
	}
}
