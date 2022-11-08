import json
import uuid


def create_md(node, volume_number, *, max_peers):
    args = ['create-md', '--force', '{}/{}'.format(node.resource.name, volume_number)]
    if node.drbd_version_tuple >= (9, 0, 0):
        args.append('--max-peers={}'.format(max_peers))
    node.drbdadm(args)


def create_storage_pool(node, backend, backing_device, thin=False, discard_granularity=None):
    pool = None
    if backend == 'lvm':
        pool = LvmPool(node, backing_device, thin, discard_granularity)
    elif backend == 'raw':
        if thin:
            raise ValueError('raw storage pool does not support thin provisioning')
        pool = RawPool(node, backing_device)
    elif backend == 'zfs':
        pool = ZfsPool(node, backing_device, thin, discard_granularity)
    else:
        raise NotImplementedError('backend "{}" not implemented'.format(backend))

    pool.create()
    return pool


class LvmPool(object):
    def __init__(self, node, backing_device, thin, discard_granularity):
        self._node = node
        self._backing_device = backing_device
        self._thin = thin
        self._discard_granularity = discard_granularity

    def create(self):
        self._node.run(['vgcreate', self._node.volume_group, self._backing_device])
        if self._thin:
            extra_args = []
            if self._discard_granularity:
                extra_args += ['--chunksize', '{}B'.format(self._discard_granularity)]
            self._node.run(['lvcreate', self._node.volume_group, '--thinpool', 'drbdthinpool', '--extents', '100%FREE'] + extra_args)

    def remove(self):
        self._node.run(['vgremove', '-y', self._node.volume_group])

    def create_disk(self, name, size, *, max_size=None):
        if self._thin:
            lvcreate_args = ['--virtualsize', str(size), '--thin', '{}/drbdthinpool'.format(self._node.volume_group)]
        else:
            lvcreate_args = ['--size', str(size), self._node.volume_group]

        lvcreate_args += ['--wipesignatures', 'y', '--yes']
        self._node.run(['lvcreate', '--name', name] + lvcreate_args, update_config=False)

        return '/dev/{}/{}'.format(self._node.volume_group, name)

    def remove_disk(self, name):
        self._node.run(['lvremove', '--force', name], update_config=False)

    def resize(self, name, size):
        self._node.run(['lvresize', '-L', size, name], update_config=False)

    def fill_percentage(self, name):
        json_str = self._node.run(['lvs', '--reportformat', 'json', name], return_stdout=True, update_config=False)
        lvs_rep = json.loads(json_str)

        return lvs_rep['report'][0]['lv'][0]['data_percent']


class RawPool(object):
    def __init__(self, node, backing_device):
        self._node = node
        self._backing_device = backing_device

    def create(self):
        # Nothing to do
        pass

    def remove(self):
        self._node.run(['wipefs', '-a', self._backing_device])

    def create_disk(self, name, size, *, max_size=None):
        guid = uuid.uuid5(uuid.NAMESPACE_URL, name)
        start = "0"
        if max_size:
            # If we expect to grow the volume, ensure we have enough space left over after it by starting at the end
            # and using the maximum size as negative offset from the end.
            start = "-" + max_size
        self._node.run(
            [
                'sgdisk',
                '--new=0:{}:+{}'.format(start, size),
                '--partition-guid=0:{}'.format(guid),
                self._backing_device
            ],
            update_config=False)
        return '/dev/disk/by-partuuid/{}'.format(guid)

    def remove_disk(self, name):
        part_number = self._node.run(['partx', '--show', '--output', 'NR', '--noheadings', name], return_stdout=True,
                                    update_config=False).strip()
        self._node.run(['sgdisk', '--delete={}'.format(part_number), self._backing_device], update_config=False)

    def resize(self, name, size):
        part_number = self._node.run(['partx', '--show', '--output', 'NR', '--noheadings', name], return_stdout=True,
                                    update_config=False).strip()
        start = self._node.run(['partx', '--show', '--output', 'START', '--noheadings', name], return_stdout=True,
                              update_config=False).strip()
        part_uuid = self._node.run(['partx', '--show', '--output', 'UUID', '--noheadings', name], return_stdout=True,
                                  update_config=False).strip()
        self._node.run([
            'sgdisk',
            '--delete={}'.format(part_number),
            '--new={}:{}:+{}'.format(part_number, start, size),
            '--partition-guid={}:{}'.format(part_number, part_uuid),
            self._backing_device,
        ], return_stdout=True, update_config=False)
        self._node.run(['partx', '--update', self._backing_device], update_config=False)
        self._node.run(['udevadm', 'trigger'], update_config=False)
        self._node.run(['udevadm', 'settle'], update_config=False)

    def fill_percentage(self, name):
        raise NotImplementedError('raw storage pool deos not support fill_percentage')


class ZfsPool(object):
    def __init__(self, node, backing_device, thin, discard_granularity):
        self._node = node
        self._backing_device = backing_device
        self._thin = thin
        self._discard_granularity = discard_granularity

    def create(self):
        self._node.run(['zpool', 'create', self._node.volume_group, self._backing_device])

    def remove(self):
        self._node.run(['zpool', 'destroy', self._node.volume_group])

    def create_disk(self, name, size, *, max_size=None):
        extra_args = ['-s'] if self._thin else []
        if self._discard_granularity is not None:
            extra_args += ['-o', 'volblocksize={}'.format(self._discard_granularity)]
        self._node.run(['zfs', 'create', '-V', str(size), '{}/{}'.format(self._node.volume_group, name)] + extra_args,
                      update_config=False)
        self._node.run(['udevadm', 'trigger'], update_config=False)
        self._node.run(['udevadm', 'settle'], update_config=False)
        return '/dev/zvol/{}/{}'.format(self._node.volume_group, name)

    def remove_disk(self, name):
        dataset_name = name[len("/dev/zvol/"):]
        self._node.run(['zfs', 'destroy', dataset_name], update_config=False)

    def resize(self, name, size):
        dataset_name = name[len("/dev/zvol/"):]
        self._node.run(['zfs', 'set', 'volsize={}'.format(size), dataset_name], update_config=False)

    def fill_percentage(self, name):
        dataset = name[len("/dev/zvol/"):]
        lines = self._node.run(['zfs', 'get', '-Hp', 'used,volsize', dataset],
                              return_stdout=True, update_config=False).splitlines()
        used = int(lines[0].split()[2])
        volsize = int(lines[1].split()[2])
        return used / volsize
