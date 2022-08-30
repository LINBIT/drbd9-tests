import uuid


class DiskTools(object):
    def __init__(self, node, backend, backing_device):
        if backend not in ('lvm', 'raw', 'zfs'):
            raise NotImplementedError('Unknown backend "{}"'.format(backend))

        self.node = node
        self._backend = backend
        self._backing_device = backing_device

    def create_disk(self, name, size, *, thin=False):
        """ Create a volume. """
        if self._backend == 'lvm':
            if thin:
                lvcreate_args = ['--virtualsize', str(size), '--thin', '{}/drbdthinpool'.format(self.node.volume_group)]
            else:
                lvcreate_args = ['--size', str(size), self.node.volume_group]

            self.node.run(['lvcreate', '--name', name] + lvcreate_args, update_config=False)

            return '/dev/{}/{}'.format(self.node.volume_group, name)
        elif self._backend == 'raw':
            if thin:
                raise ValueError('backend "raw" does not support thin provisioning')

            guid = uuid.uuid5(uuid.NAMESPACE_URL, name)
            self.node.run(
                ['sgdisk', '--new=0:0:+{}'.format(size), '--partition-guid=0:{}'.format(guid), self._backing_device],
                update_config=False)
            return '/dev/disk/by-partuuid/{}'.format(guid)
        elif self._backend == 'zfs':
            extra_args = ['-s'] if thin else []
            self.node.run(['zfs', 'create', '-V', str(size), '{}/{}'.format(self.node.volume_group, name)] + extra_args,
                          update_config=False)
            return '/dev/zvol/{}/{}'.format(self.node.volume_group, name)
        else:
            raise NotImplementedError('backend "{}" not implemented'.format(self._backend))

    def remove_disk(self, name):
        if self._backend == 'lvm':
            self.node.run(['lvremove', '--force', name], update_config=False)
        elif self._backend == 'raw':
            part_number = self.node.run(['partx', '--show', '--output', 'NR', '--noheadings', name], return_stdout=True,
                                        update_config=False).strip()
            self.node.run(['sgdisk', '--delete={}'.format(part_number), self._backing_device], update_config=False)
        elif self._backend == 'zfs':
            dataset_name = name[len("/dev/zvol/"):]
            self.node.run(['zfs', 'destroy', dataset_name], update_config=False)
        else:
            raise NotImplementedError('backend "{}" not implemented'.format(self._backend))

    def resize(self, name, size):
        if self._backend == 'lvm':
            self.node.run(['lvresize', '-L', size, name], update_config=False)
        elif self._backend == 'raw':
            part_number = self.node.run(['partx', '--show', '--output', 'NR', '--noheadings', name], return_stdout=True,
                                        update_config=False).strip()
            start = self.node.run(['partx', '--show', '--output', 'START', '--noheadings', name], return_stdout=True,
                                  update_config=False).strip()
            part_uuid = self.node.run(['partx', '--show', '--output', 'UUID', '--noheadings', name], return_stdout=True,
                                      update_config=False).strip()
            self.node.run([
                'sgdisk',
                '--delete={}'.format(part_number),
                '--new={}:{}:+{}'.format(part_number, start, size),
                '--partition-guid={}:{}'.format(part_number, part_uuid),
                self._backing_device,
            ], return_stdout=True, update_config=False)
            self.node.run(['partx', '--update', self._backing_device], update_config=False)
            self.node.run(['udevadm', 'trigger'], update_config=False)
        elif self._backend == 'zfs':
            dataset_name = name[len("/dev/zvol/"):]
            self.node.run(['zfs', 'set', 'volsize={}'.format(size), dataset_name], update_config=False)
        else:
            raise NotImplementedError('backend "{}" not implemented'.format(self._backend))

    @staticmethod
    def create_md(node, volume_number, *, max_peers):
        args = ['create-md', '--force', '{}/{}'.format(node.resource.name, volume_number)]
        if node.drbd_version_tuple >= (9, 0, 0):
            args.append('--max-peers={}'.format(max_peers))
        node.drbdadm(args)
