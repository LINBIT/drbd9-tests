global {
	usage-count no;
}

resource RESOURCE {
m4_foreach(`NODE', `(NODES)',
`	on NODE {
		volume 0 {
			device DEVICE(NODE);
			disk DISK(NODE);
			meta-disk m4_ifelse(META_DISK(NODE), `', `internal', `META_DISK(NODE)');
		}
		node-id NODE_ID(NODE);
		address ADDRESS(NODE);
	}
')m4_dnl
	connection-mesh {
		hosts m4_join(` ', NODES);
	}
}
