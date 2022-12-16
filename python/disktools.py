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

    return pool


class LvmPool(object):
    def __init__(self, node, backing_device, thin, discard_granularity):
        self._node = node
        self._backing_device = backing_device
        self._thin = thin
        self._discard_granularity = discard_granularity

        self._node.run(['vgcreate', self._node.volume_group, self._backing_device])
        if self._thin:
            extra_args = []
            if self._discard_granularity:
                extra_args += ['--chunksize', '{}B'.format(self._discard_granularity)]
            self._node.run(['lvcreate', self._node.volume_group, '--thinpool', 'drbdthinpool', '--extents', '100%FREE'] + extra_args)

    def remove(self):
        self._node.run(['vgremove', '-y', self._node.volume_group])

    def create_disk(self, name, size, *, max_size=None):
        return LvmVolume(self._node, name, size=size, thin=self._thin)


class LvmVolume(object):
    def __init__(self, node, name, *, size, thin=False):
        self._node = node
        self._name = name
        self._lv = '/dev/{}/{}'.format(node.volume_group, name)

        if thin:
            lvcreate_args = ['--virtualsize', str(size), '--thin', '{}/drbdthinpool'.format(self._node.volume_group)]
        else:
            lvcreate_args = ['--size', str(size), self._node.volume_group]

        lvcreate_args += ['--wipesignatures', 'y', '--yes']
        self._node.run(['lvcreate', '--name', self._name] + lvcreate_args, update_config=False)

    def volume_path(self):
        return self._lv

    def remove(self):
        self._node.run(['lvremove', '--force', self._lv], update_config=False)

    def resize(self, size):
        self._node.run(['lvresize', '-L', size, self._lv], update_config=False)

    def fill_percentage(self):
        json_str = self._node.run(['lvs', '--reportformat', 'json', self._lv], return_stdout=True, update_config=False)
        lvs_rep = json.loads(json_str)

        return lvs_rep['report'][0]['lv'][0]['data_percent']


class RawPool(object):
    def __init__(self, node, backing_device):
        self._node = node
        self._backing_device = backing_device

    def remove(self):
        self._node.run(['wipefs', '-a', self._backing_device])

    def create_disk(self, name, size, *, max_size=None):
        return RawVolume(self._node, self._backing_device, name, size=size, max_size=max_size)


class RawVolume(object):
    def __init__(self, node, backing_device, name, *, size, max_size=None):
        self._node = node
        self._backing_device = backing_device
        self._guid = uuid.uuid5(uuid.NAMESPACE_URL, name)
        self._device_path = '/dev/disk/by-partuuid/{}'.format(self._guid)

        self._start = "0"
        if max_size:
            # If we expect to grow the volume, ensure we have enough space left over after it by starting at the end
            # and using the maximum size as negative offset from the end.
            self._start = "-" + max_size
        self._node.run(
            [
                'sgdisk',
                '--new=0:{}:+{}'.format(self._start, size),
                '--partition-guid=0:{}'.format(self._guid),
                self._backing_device
            ],
            update_config=False)
        self._refresh_partitions()
        self._part_number = self._node.run(['partx', '--show', '--output', 'NR', '--noheadings', self._device_path], return_stdout=True,
                                    update_config=False).strip()

    def volume_path(self):
        return self._device_path

    def remove(self):
        self._node.run(['sgdisk', '--delete={}'.format(self._part_number), self._backing_device], update_config=False)

    def resize(self, size):
        self._node.run([
            'sgdisk',
            '--delete={}'.format(self._part_number),
            '--new={}:{}:+{}'.format(self._part_number, self._start, size),
            '--partition-guid={}:{}'.format(self._part_number, self._guid),
            self._backing_device,
        ], return_stdout=True, update_config=False)
        self._refresh_partitions()

    def fill_percentage(self):
        raise NotImplementedError('raw storage volume does not support fill_percentage')

    def _refresh_partitions(self):
        self._node.run(['partx', '--update', self._backing_device], update_config=False)
        self._node.run(['udevadm', 'trigger'], update_config=False)
        self._node.run(['udevadm', 'settle'], update_config=False)


class ZfsPool(object):
    def __init__(self, node, backing_device, thin, discard_granularity):
        self._node = node
        self._backing_device = backing_device
        self._thin = thin
        self._discard_granularity = discard_granularity

        self._node.run(['zpool', 'create', self._node.volume_group, self._backing_device])

    def remove(self):
        self._node.run(['zpool', 'destroy', self._node.volume_group])

    def create_disk(self, name, size, *, max_size=None):
        return ZfsVolume(self._node, name,
                size=size, thin=self._thin, discard_granularity=self._discard_granularity)


class ZfsVolume(object):
    def __init__(self, node, name, *, size, thin=False, discard_granularity=None):
        self._node = node
        self._dataset_name = '{}/{}'.format(node.volume_group, name)
        self._zvol_path = '/dev/zvol/' + self._dataset_name

        extra_args = ['-s'] if thin else []
        if discard_granularity is not None:
            extra_args += ['-o', 'volblocksize={}'.format(discard_granularity)]
        self._node.run(['zfs', 'create', '-V', str(size), self._dataset_name] + extra_args,
                      update_config=False)
        self._node.run(['udevadm', 'trigger'], update_config=False)
        self._node.run(['udevadm', 'settle'], update_config=False)

    def volume_path(self):
        return self._zvol_path

    def remove(self):
        self._node.run(['zfs', 'destroy', self._dataset_name], update_config=False)

    def resize(self, size):
        self._node.run(['zfs', 'set', 'volsize={}'.format(size), self._dataset_name], update_config=False)

    def fill_percentage(self):
        lines = self._node.run(['zfs', 'get', '-Hp', 'used,volsize', self._dataset_name],
                              return_stdout=True, update_config=False).splitlines()
        used = int(lines[0].split()[2])
        volsize = int(lines[1].split()[2])
        return used / volsize
