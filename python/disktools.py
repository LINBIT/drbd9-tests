from io import StringIO
import json
import uuid


def create_md(node, volume_number, *, max_peers):
    args = ['create-md', '--force', '{}/{}'.format(node.resource.name, volume_number)]
    if node.host.drbd_version_tuple >= (9, 0, 0):
        args.append('--max-peers={}'.format(max_peers))
    node.drbdadm(args)


def create_storage_pool(host, backend, backing_device, thin=False, discard_granularity=None):
    pool = None
    if backend == 'lvm':
        pool = LvmPool(host, backing_device, thin, discard_granularity)
    elif backend == 'raw':
        if thin:
            raise ValueError('raw storage pool does not support thin provisioning')
        pool = RawPool(host, backing_device)
    elif backend == 'zfs':
        pool = ZfsPool(host, backing_device, thin, discard_granularity)
    else:
        raise NotImplementedError('backend "{}" not implemented'.format(backend))

    return pool


def create_disk(host, name, size, *, max_size=None, delay_ms=None, logical_block_size=None):
    disk_volume = host.storage_pool.create_disk(name, size, max_size=max_size)

    if delay_ms is not None:
        disk_volume = DelayVolume(host, name, disk_volume, delay_ms=delay_ms)

    if logical_block_size is not None:
        disk_volume = EmulatedBlockSizeVolume(host, name, disk_volume, logical_block_size=logical_block_size)

    return disk_volume


class LvmPool(object):
    def __init__(self, host, backing_device, thin, discard_granularity):
        self._host = host
        self._backing_device = backing_device
        self._thin = thin
        self._discard_granularity = discard_granularity

        self._host.run(['vgcreate', self._host.volume_group, self._backing_device])
        if self._thin:
            extra_args = []
            if self._discard_granularity:
                extra_args += ['--chunksize', '{}B'.format(self._discard_granularity)]
            self._host.run(['lvcreate', self._host.volume_group, '--thinpool', 'drbdthinpool', '--extents', '100%FREE'] + extra_args)

    def remove(self):
        self._host.run(['vgremove', '-y', self._host.volume_group])

    def create_disk(self, name, size, *, max_size=None):
        return LvmVolume(self._host, name, size=size, thin=self._thin)


class LvmVolume(object):
    def __init__(self, host, name, *, size, thin=False):
        self._host = host
        self._name = name
        self._lv = '/dev/{}/{}'.format(host.volume_group, name)

        if thin:
            lvcreate_args = ['--virtualsize', str(size), '--thin', '{}/drbdthinpool'.format(self._host.volume_group)]
        else:
            lvcreate_args = ['--size', str(size), self._host.volume_group]

        lvcreate_args += ['--wipesignatures', 'y', '--yes']
        self._host.run(['lvcreate', '--name', self._name] + lvcreate_args)

    def volume_path(self):
        return self._lv

    def remove(self):
        self._host.run(['lvremove', '--force', self._lv])

    def resize(self, size):
        self._host.run(['lvresize', '-L', size, self._lv])

    def fill_percentage(self):
        json_str = self._host.run(['lvs', '--reportformat', 'json', self._lv], return_stdout=True)
        lvs_rep = json.loads(json_str)

        return lvs_rep['report'][0]['lv'][0]['data_percent']


class RawPool(object):
    def __init__(self, host, backing_device):
        self._host = host
        self._backing_device = backing_device

    def remove(self):
        self._host.run(['wipefs', '-a', self._backing_device])

    def create_disk(self, name, size, *, max_size=None):
        return RawVolume(self._host, self._backing_device, name, size=size, max_size=max_size)


class RawVolume(object):
    def __init__(self, host, backing_device, name, *, size, max_size=None):
        self._host = host
        self._backing_device = backing_device
        self._guid = uuid.uuid5(uuid.NAMESPACE_URL, name)
        self._device_path = '/dev/disk/by-partuuid/{}'.format(self._guid)

        self._start = "0"
        if max_size:
            # If we expect to grow the volume, ensure we have enough space left over after it by starting at the end
            # and using the maximum size as negative offset from the end.
            self._start = "-" + max_size
        self._host.run(
            [
                'sgdisk',
                '--new=0:{}:+{}'.format(self._start, size),
                '--partition-guid=0:{}'.format(self._guid),
                self._backing_device
            ])
        self._refresh_partitions()
        self._part_number = self._host.run(['partx', '--show', '--output', 'NR', '--noheadings', self._device_path],
                return_stdout=True).strip()

    def volume_path(self):
        return self._device_path

    def remove(self):
        self._host.run(['sgdisk', '--delete={}'.format(self._part_number), self._backing_device])

    def resize(self, size):
        self._host.run([
            'sgdisk',
            '--delete={}'.format(self._part_number),
            '--new={}:{}:+{}'.format(self._part_number, self._start, size),
            '--partition-guid={}:{}'.format(self._part_number, self._guid),
            self._backing_device,
        ], return_stdout=True)
        self._refresh_partitions()

    def fill_percentage(self):
        raise NotImplementedError('raw storage volume does not support fill_percentage')

    def _refresh_partitions(self):
        self._host.run(['partx', '--update', self._backing_device])
        self._host.run(['udevadm', 'trigger'])
        self._host.run(['udevadm', 'settle'])


class ZfsPool(object):
    def __init__(self, host, backing_device, thin, discard_granularity):
        self._host = host
        self._backing_device = backing_device
        self._thin = thin
        self._discard_granularity = discard_granularity

        self._host.run(['zpool', 'create', self._host.volume_group, self._backing_device])

    def remove(self):
        self._host.run(['zpool', 'destroy', self._host.volume_group])

    def create_disk(self, name, size, *, max_size=None):
        return ZfsVolume(self._host, name,
                size=size, thin=self._thin, discard_granularity=self._discard_granularity)


class ZfsVolume(object):
    def __init__(self, host, name, *, size, thin=False, discard_granularity=None):
        self._host = host
        self._dataset_name = '{}/{}'.format(host.volume_group, name)
        self._zvol_path = '/dev/zvol/' + self._dataset_name

        extra_args = ['-s'] if thin else []
        if discard_granularity is not None:
            extra_args += ['-o', 'volblocksize={}'.format(discard_granularity)]
        self._host.run(['zfs', 'create', '-V', str(size), self._dataset_name] + extra_args)
        self._host.run(['udevadm', 'trigger'])
        self._host.run(['udevadm', 'settle'])

    def volume_path(self):
        return self._zvol_path

    def remove(self):
        self._host.run(['zfs', 'destroy', self._dataset_name])

    def resize(self, size):
        self._host.run(['zfs', 'set', 'volsize={}'.format(size), self._dataset_name])

    def fill_percentage(self):
        lines = self._host.run(['zfs', 'get', '-Hp', 'used,volsize', self._dataset_name],
                              return_stdout=True).splitlines()
        used = int(lines[0].split()[2])
        volsize = int(lines[1].split()[2])
        return used / volsize


class DeviceMapperTarget(object):
    def __init__(self, host, name, backing_volume, *, dm_type):
        self._host = host
        self._backing_volume = backing_volume
        self._dm_type = dm_type
        self._device_name = '{}-{}'.format(name, dm_type)
        self._device_path = '/dev/mapper/{}'.format(self._device_name)

        self._sectors = self._host.run(['blockdev', '--getsz', self._backing_volume.volume_path()],
                return_stdout=True)

        self._host.run(['dmsetup', 'create', self._device_name],
                stdin=StringIO(self._table()))

    def volume_path(self):
        return self._device_path

    def remove(self):
        self._host.run(['dmsetup', 'remove', self._device_name])
        self._backing_volume.remove()

    def resize(self, size):
        raise NotImplementedError('delay storage volume does not implement resize')

    def fill_percentage(self):
        return self._backing_volume.fill_percentage()

    def _table_start(self):
        return '0 {} {}'.format(self._sectors, self._dm_type)

class DelayVolume(DeviceMapperTarget):
    def __init__(self, host, name, backing_volume, *, delay_ms):
        self._delay_ms = delay_ms
        super().__init__(host, name, backing_volume, dm_type = 'delay')

    def set_delay_ms(self, delay_ms):
        self._delay_ms = delay_ms
        self._host.run(['dmsetup', 'reload', self._device_name],
                stdin=StringIO(self._table()))
        self._host.run(['dmsetup', 'suspend', self._device_name])
        self._host.run(['dmsetup', 'resume', self._device_name])

    def _table(self):
        return '{} {} 0 {}'.format(self._table_start(), self._backing_volume.volume_path(), self._delay_ms)

class EmulatedBlockSizeVolume(DeviceMapperTarget):
    def __init__(self, host, name, backing_volume, *, logical_block_size):
        self._logical_block_size = logical_block_size
        super().__init__(host, name, backing_volume, dm_type = 'ebs') # EBS = emulated block size

    def _table(self):
        print('{} {} 0 {}'.format(self._table_start(), self._backing_volume.volume_path(), int(self._logical_block_size/512)))
        return '{} {} 0 {}'.format(self._table_start(), self._backing_volume.volume_path(), int(self._logical_block_size/512))
