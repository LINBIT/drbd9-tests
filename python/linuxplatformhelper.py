import os
import re
import inspect
from .drbdtestlogger import log

drbd_config_dir_linux_default = '/var/lib/drbd-test'

class LinuxPlatformHelper(object):
    def __init__(self):
        pass

    def init_host(self, host, storage_backend, backing_device, multi_paths, netns):
        host.storage_backend = storage_backend
        host.backing_device = backing_device
        host.drbd_config_dir = drbd_config_dir_linux_default

        host.os_id, host.os_version_id = host.run(
                ['bash', '-c', '. /etc/os-release ; echo $ID ; echo $VERSION_ID'],
                return_stdout=True).splitlines()

        addresses = host.run(['ip', '-oneline', 'addr', 'show'], return_stdout=True)
        log("got all addresses %s", addresses)
        for line in addresses.splitlines():
            m = re.search(r'^\s*\d+:\s+(\w+)\s+inet\s+([\d\.]+)/(\d+)', line)
            if not m:
                continue
            devname = m.group(1)
            addr = m.group(2)
            prefix = m.group(3)
            if addr == "127.0.0.1" or addr == host.addr:
                continue

            host.netdevs[devname] = {
                'address': addr,
                'prefix': prefix,
            }

        if multi_paths:
            if not host.netdevs:
                raise RuntimeError("%s has no additional address", host)

            log("got all addresses %s", addresses)
            for address_info in host.netdevs.values():
                host.addrs.append(address_info['address'])

        init_iptables = ["bash", "--norc", "-xec", inspect.cleandoc('''
                iptables -F drbd-test-input || iptables -N drbd-test-input
                iptables -F drbd-test-output || iptables -N drbd-test-output
                iptables -I INPUT -j drbd-test-input
                iptables -I OUTPUT -j drbd-test-output
                ''')]

        if netns:
            if not host.netdevs:
                raise RuntimeError("%s is missing additional netdevs to namespace", host)

            host.addrs = []
            host.run(['ip', 'netns', 'add', netns])
            for address_info in host.netdevs.values():
                host.addrs.append(address_info['address'])

            if len(host.addrs) < 1:
                raise RuntimeError("%s has namespaced address", host)

            # Also configure IPTABLES in the init_net namespace, some tests might use both
            host.run_quiet(init_iptables)

            # From now on, all run() commands run in <netns> namespace, unless explicitly excluded
            host.netns = netns
            # Now ensure all netdevs are moved to the right namespace
            host.ensure_netdev(netns=netns)

        host.run_quiet(init_iptables)

    def read_drbd_version(self, host):
        # cat > /dev/kmsg so we have it in the dmesg stream,
        # even if the ring buffer wrapped since the module was loaded
        host.run(['bash', '-c', 'cat /proc/drbd > /dev/kmsg || modprobe drbd'])
        proc_drbd_lines = host.run(['cat', '/proc/drbd'], return_stdout=True).splitlines()
        version_line = proc_drbd_lines[0]
        git_hash_line = proc_drbd_lines[1]

        version_line_match = re.match(r'version: ([^ -]+).*', version_line)
        host.drbd_version = version_line_match.group(1)

        # out-of-tree drbd uses "GIT-hash: 0a1b2c3d",
        # in-tree uses "srcversion: 0A1B2C3D"; allow both formats.
        hash_match = re.match(r'(?:srcversion|GIT-hash): ([0-9A-Fa-f]+).*', git_hash_line)
        host.drbd_git_hash = hash_match.group(1).lower()

        version_match = re.match(r'([0-9]+)\.([0-9]+)\.([0-9]+).*', host.drbd_version)
        host.drbd_version_tuple = int(version_match.group(1)), int(version_match.group(2)), int(version_match.group(3))

    def native_filename(self, host, filename):
        return filename

    def cleanup_framework(self, host):
        """
        Clean up changes made for the test framework. This should always be
        run.
        """

        tlshd_log = host.run(["journalctl", "-u", "tlshd", "-b", "0", "-q"], return_stdout=True)
        if tlshd_log:
            with open(os.path.join(host.cluster.logdir, 'tlshd-{}'.format(host.name)), "w") as tlshd_logfile:
                tlshd_logfile.write(tlshd_log)

        cleanup_iptables = ["bash", "--norc", "-xec", inspect.cleandoc('''
            iptables -D INPUT -j drbd-test-input
            iptables -D OUTPUT -j drbd-test-output
            iptables -F drbd-test-input && iptables -X drbd-test-input || true
            iptables -F drbd-test-output && iptables -X drbd-test-output || true
            ''')]

        host.run_quiet(cleanup_iptables)

    def start_dmesg(self, host):
        host.start_dmesg_with_cmd('echo $$ ; dmesg --follow-new --time-format=iso || dmesg --follow')

    def stop_dmesg(self, host):
        if host.dmesg_process:
            # Kill entire remote session
            host.run(['bash', '-c', 'kill $(ps -s {} -o pid=)'.format(
                host.dmesg_pid_trap.first_message.strip())])

    def rmmod(self, host):
        if host.drbd_version_tuple >= (9, 0, 0):
            # might not even be loaded
            try:
                host.run(['rmmod', 'drbd_transport_tcp'])
            except:
                pass
            try:
                host.run(['rmmod', 'drbd_transport_lb-tcp'])
            except:
                pass
            try:
                host.run(['rmmod', 'drbd_transport_rdma'])
            except:
                pass
        try:
            host.run(['rmmod', 'drbd'])
        except:
            pass

    def disable_faults(self, host):
        host.run_helper('disable-faults')

# Node helpers:

    def init_node(self, node):
        pass

    def after_becoming_primary(self, node):
        pass

    def block_path(self, node, other_node, net_number=0, jump_to="DROP", iptables_filter=[]):
        """Uses iptables to block one network path."""
        log("BLOCKING path #%d from %s to %s" % (net_number, node, other_node))
        cmds = node._iptables_cmd(other_node, jump_to, net_number, "-I", iptables_filter)
        for c in cmds:
            node.run(c)

    def unblock_path(self, node, other_node, net_number=0, jump_to="DROP"):
        """Uses iptables to unblock one network path."""
        log("Unblocking path #%d from %s to %s" % (net_number, node, other_node))
        cmds = node._iptables_cmd(other_node, jump_to, net_number, "-D")
        for c in cmds:
            node.run(c)

    def prepare_auto_promote(self, node):
        pass

    def cleanup_auto_demote(self, node):
        pass

# Volume helpers

    def disk_native(self, volume):
        return volume.disk()

    def device(self, volume):
        return '/dev/drbd%d' % volume.minor

    def device_for_config(self, volume):
        return volume.device()

    def set_disk_online(self, volume):
        pass

    def mkfs(self, volume):
        volume.node.run(['mkfs', '-t', 'ext4', volume.device()])

    def mount(self, volume, where):
        volume.node.run(['mount', volume.device(), where])

    def set_disk_offline(self, volume):
        pass

    def umount(self, volume, where, set_offline = False):
        volume.node.run(['umount', where])

    def wipe_ntfs(self, volume):
        pass
