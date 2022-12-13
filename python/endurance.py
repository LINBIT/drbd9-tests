import time
import typing

from . import busywrite, datatools, trafficcontrol
from .drbdtest import log, peer_devices


# 67 AL extents cover 268MiB. Use a bit more to test the activity log.
size_mb = 280
data_size = '{}M'.format(size_mb)

# Endurance tests run with a timeout of 10m. The test suite does not know what
# timeout applies, so hard code a runtime of 9m to ensure that we finish within
# the timeout.
test_runtime = 9 * 60


class EnduranceConfig(object):
    protocol: typing.Optional[str]
    network_rate: typing.Optional[str]
    disk_delay_ms: typing.Optional[int]
    diskless_primary: bool

    def __init__(self):
        self.protocol = None
        self.network_rate = None
        self.disk_delay_ms = None
        self.diskless_primary = False

    def __repr__(self):
        return 'EnduranceConfig(protocol={}, network_rate={}, disk_delay_ms={}, diskless_primary={})'.format(
                repr(self.protocol), repr(self.network_rate), repr(self.disk_delay_ms), repr(self.diskless_primary))


def run(resource, config):
    primary_n = resource.nodes[0]
    diskful_nodes = resource.nodes[1:] if config.diskless_primary else resource.nodes

    primary_tc = trafficcontrol.TrafficControl(resource.nodes[0], resource.nodes)

    setup(resource, config, primary_n, diskful_nodes)

    if config.network_rate:
        for node in resource.nodes[1:]:
            primary_tc.slow_down(node, speed=config.network_rate)

    if config.disk_delay_ms:
        for node in diskful_nodes:
            node.volumes[0].disk_volume.set_delay_ms(config.disk_delay_ms)

    if config.protocol:
        writer = busywrite.BusyWrite(primary_n.volumes[0])
        start_fio(writer, test_runtime)

        log('* Waiting {}s for endurance run'.format(test_runtime))
        # timeout is longer than the expected wait time to allow fio some time to start and stop
        writer.wait(timeout=test_runtime + 10)
    else:
        log('* Doing nothing for {}s'.format(test_runtime))
        time.sleep(test_runtime)

    if config.disk_delay_ms:
        for node in diskful_nodes:
            node.volumes[0].disk_volume.set_delay_ms(0)

    teardown(resource, primary_n, diskful_nodes)
    primary_tc.reset()


def run_resync(resource, config):
    primary_n = resource.nodes[0]
    diskful_nodes = resource.nodes[1:] if config.diskless_primary else resource.nodes
    source_n, target_n = diskful_nodes[:2]

    setup(resource, config, primary_n, diskful_nodes)

    writer = busywrite.BusyWrite(primary_n.volumes[0])

    fio_rates = ['1M', '4M', '16M', '64M', '256M', '1G']
    count = 0

    traffic_controls = []

    if config.network_rate:
        for from_n in resource.nodes:
            tc = trafficcontrol.TrafficControl(from_n, resource.nodes)
            traffic_controls.append(tc)
            for to_n in resource.nodes:
                if to_n != from_n:
                    tc.slow_down(to_n, speed=config.network_rate)

    if config.disk_delay_ms:
        for node in diskful_nodes:
            node.volumes[0].disk_volume.set_delay_ms(config.disk_delay_ms)

    start = time.time()
    while time.time() - start < test_runtime:
        fio_rate = fio_rates[count % len(fio_rates)]
        # We wait up to 30s for the resync to complete. Perform IO for longer
        # than this to ensure that IO is active for the entire resync.
        start_fio(writer, 60, '--rate={}'.format(fio_rate))

        # Let fio start.
        time.sleep(0.5)

        source_n.drbdadm(['invalidate-remote', '{}:{}'.format(resource.name, target_n.name)])
        peer_devices(source_n, target_n).event(r'peer-device .* replication:SyncSource')
        peer_devices(target_n, source_n).event(r'peer-device .* replication:SyncTarget')
        peer_devices(source_n, target_n).event(r'peer-device .* replication:Established')
        peer_devices(target_n, source_n).event(r'peer-device .* replication:Established')

        writer.stop()

        count += 1

    if config.disk_delay_ms:
        for node in diskful_nodes:
            node.volumes[0].disk_volume.set_delay_ms(0)

    teardown(resource, primary_n, diskful_nodes)

    for tc in traffic_controls:
        tc.reset()


def setup(resource, config, primary_n, diskful_nodes):
    resource.disk_options = 'al-extents 67; c-max-rate 1G; c-min-rate 0;'
    resource.net_options = 'protocol {};'.format(config.protocol if config.protocol else 'C')

    resource.add_disk('300M', diskful_nodes=diskful_nodes,
            delay_ms=0 if config.disk_delay_ms else None)

    resource.up_wait()

    log('* Make up-to-date data available.')
    resource.skip_initial_sync()

    primary_n.primary()

    primary_n.write(direct=1, size=data_size, bs='1M')


def start_fio(writer, runtime, fio_arg_str=''):
        writer.start('--runtime={} --size={} --numjobs=2 '.format(runtime, data_size) +
                '--norandommap=1 --randrepeat=0 ' +
                # Use a heavily skewed IO pattern to trigger bugs which occur
                # with repeated IO to the same sectors.
                '--rw=randrw --rwmixwrite=70 --percentage_random=50 --random_distribution=zipf:2.0 ' +
                '--blocksize_range=4k-64k ' +
                fio_arg_str)


def teardown(resource, primary_n, diskful_nodes):
    primary_n.secondary()

    datatools.verify_data(diskful_nodes, size_mb=size_mb, backing_disk=True)

    log('* Shut down and clean up.')
    resource.down()
    resource.teardown()
