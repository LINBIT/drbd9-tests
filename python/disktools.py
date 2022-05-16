class DiskTools(object):
    @staticmethod
    def create_disk(node, name, size, *, thin=False):
        """ Create a volume. """

        if thin:
            lvcreate_args = ['--virtualsize', str(size), '--thin', '{}/drbdthinpool'.format(node.volume_group)]
        else:
            lvcreate_args = ['--size', str(size), node.volume_group]

        node.run(['lvcreate', '--name', name] + lvcreate_args, update_config=False)

        return '/dev/{}/{}'.format(node.volume_group, name)

    @staticmethod
    def remove_disk(node, name):
        node.run(['lvremove', '--force', name])

    @staticmethod
    def create_md(node, volume_number, *, max_peers):
        args = ['create-md', '--force',
            '{}/{}'.format(node.resource.name, volume_number)]
        if node.drbd_version_tuple >= (9, 0, 0):
            args.append('--max-peers={}'.format(max_peers))
        node.drbdadm(args)
