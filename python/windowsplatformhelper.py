import re
from .drbdtestlogger import log

drbd_config_dir_windows_default = '/cygdrive/c/WinDRBD/var/lib/drbd-test'

class WindowsPlatformHelper(object):
    def __init__(self):
        pass

    def init_host(self, host, storage_backend, backing_device, multi_paths, netns):
        if multi_paths:
            raise RuntimeError("multi_paths not supported on Windows (is {})".format(multi_paths))

        if netns:
            raise RuntimeError("netns not supported on Windows (is {})".format(netns))

        host.storage_backend = "storage-spaces"
        host.backing_device = "scratch"	# see virter/run.toml
        host.drbd_config_dir = drbd_config_dir_windows_default

        host.os_id = "Windows"
        host.os_version_id = host.run(['uname'], return_stdout=True).split("_")[1]

    def read_drbd_version(self, host):
        version_lines = host.run(['drbdadm', '--version'], return_stdout=True).splitlines()
        for l in version_lines:
            a = l.split('=')
            if a[0] == 'DRBD_KERNEL_VERSION':
                host.drbd_version = a[1]
            if a[0] == 'WINDRBD_VERSION':
                host.drbd_git_hash = a[1]
                print("WinDRBD version is {}".format(host.drbd_git_hash))

        version_match = re.match(r'([0-9]+)\.([0-9]+)\.([0-9]+).*', host.drbd_version)
        host.drbd_version_tuple = int(version_match.group(1)), int(version_match.group(2)), int(version_match.group(3))

    # /cygdrive/c/xxx -> C:\xxx
    # but also: /dev/sdc -> \\.\Volume{<guid>}
    #
    def native_filename(self, host, filename):
        return host.run(['cygpath', '-w', filename], return_stdout=True).strip()

    def start_dmesg(self, host):
        host.start_dmesg_with_cmd('echo $$ ; tail -f /cygdrive/c/WinDRBD/windrbd-kernel.log')

    def stop_dmesg(self, host):
        if host.dmesg_process:
            # No sessions on Windows, also ps works completely different
            host.run(['bash', '-c', 'kill {}'.format(
                host.dmesg_pid_trap.first_message.strip())])

    # In theory this could be implemented, the logic is in the
    # WinDRBD installer.
    def rmmod(self, host):
        pass

    def disable_faults(self, host):
        pass

    def cleanup_framework(self, host):
        pass

# Node helpers:

    def init_node(self, node):
        # Create a firewall rule on Windows. Later we will disable it on
        # blocking and reenable it on unblocking.

        node.host.run(['netsh', 'advfirewall', 'firewall', 'add', 'rule', 'name=DRBDTest'+str(node.port), 'protocol=tcp', 'dir=in', 'localport='+str(node.port), 'action=allow'])

    def after_becoming_primary(self, node):
        # Do the online disk and attributes clear readonly magic:
        for v in node.disks:
            v.set_disk_online()

    def block_path(self, node, other_node, net_number=0, jump_to="DROP", for_seconds=None, iptables_filter=[]):
        """Uses netsh to block one network path."""
        log("BLOCKING path #%d from %s to %s" % (net_number, self, other_node))
        if for_seconds is not None:
            raise RuntimeError("for_seconds not implemented")
        node.run(['netsh', 'advfirewall', 'firewall', 'set', 'rule', 'name=DRBDTest'+str(self.port), 'new', 'enable=no'])
        other_node.run(['netsh', 'advfirewall', 'firewall', 'set', 'rule', 'name=DRBDTest'+str(other_node.port), 'new', 'enable=no'])

    def unblock_path(self, node, other_node, net_number=0, jump_to="DROP"):
        """Uses netsh to unblock one network path."""
        log("Unblocking path #%d from %s to %s" % (net_number, self, other_node))
        node.run(['netsh', 'advfirewall', 'firewall', 'set', 'rule', 'name=DRBDTest'+str(self.port), 'new', 'enable=yes'])
        other_node.run(['netsh', 'advfirewall', 'firewall', 'set', 'rule', 'name=DRBDTest'+str(other_node.port), 'new', 'enable=yes'])

    def prepare_auto_promote(self, node):
        log("Promoting WinDRBD resource (there is no auto-promote on WinDRBD) ...")
        while True:
            try:
                node.primary(force=False, wait=False)
                return
            except:
                pass

            log("Promote failed, retrying in 1 second ...")
            time.sleep(1)

    def cleanup_auto_demote(self, node):
        log("Manually demoting WinDRBD resource (there is no auto-promote on WinDRBD) ...")

        while True:
            try:
                node.secondary(force=False, wait=False)
                return
            except:
                pass

            log("Manual demote failed, retrying in 1 second ...")
            time.sleep(1)


# Volume helpers:

    # For use with dd for example:
    def disk_native(self, volume):
        if volume.disk_volume:
            return "\\\\.\\Volume{{{}}}".format(volume.disk_volume.volume_path())
        return None

    # returns a powershell snippet that looks up the WinDRBD disk
    # by minor and assigns the powershell disk object to the $mydisk
    # variable.

    def powershell_get_disk(self, minor):
        return """
            $j = 0
            do {{
                $j = $j+1
                $mydisk = Get-Disk | where {{ $_.Path -like \"*#WinDRBD{{0}}#*\" -f {} }}
                if ( $mydisk ) {{ break }}
                sleep 1
            }} while ( $j -lt 30 )
            if ( ! $mydisk ) {{
                echo \"Disk did not come up within 30 seconds.\"
                exit 42
            }}
        """.format(minor)

    def run_powershell_on_disk(self, volume, command):
        return volume.node.run(['powershell', '-command',
            self.powershell_get_disk(volume.minor)+command], return_stdout=True, timeout=120)

    def device(self, volume):
        # we need to get the disk number via powershell. Then
        # the device is /dev/sda for number 0 /dev/sdb for 1
        # and so on.
        # Also since the device only exists when the resource
        # is primary set the node to primaryfirst. We
        # most likely will start to do I/O on it.

        disk_number = int(self.run_powershell_on_disk(volume, """
            $ProgressPreference = "SilentlyContinue"
            $mydisk.Number
        """).strip())

        if disk_number > 26 or disk_number < 0:
            raise RuntimeError("Disknumber {} out of range".format(disk_number))
        if disk_number == 0:
            raise RuntimeError("Refusing to access system partition")

        return "/dev/sd{}".format(chr(disk_number+ord('a')))

    def device_for_config(self, volume):
        return 'minor %d' % volume.minor

    def set_disk_online(self, volume):
        if not volume.disk_is_online:
            self.run_powershell_on_disk(volume, """
                $ProgressPreference = "SilentlyContinue"
                $mydisk | set-disk -IsOffline $false
                $ProgressPreference = "SilentlyContinue"
                $mydisk | set-disk -IsReadonly $false
            """)

        volume.disk_is_online = True

    def mkfs(self, volume):
        self.run_powershell_on_disk(volume, """
            $ProgressPreference = "SilentlyContinue"
            $mydisk | Initialize-Disk -passthru -PartitionStyle MBR |  New-Partition -UseMaximumSize | format-volume
        """)

    def mount(self, volume, where):
        self.run_powershell_on_disk(volume, """
            $ProgressPreference = "SilentlyContinue"
            $mydisk | Get-Partition | Add-PartitionAccessPath -AccessPath \"{}\"
        """.format(volume.node.host.native_filename(where)))

    def set_disk_offline(self, volume):
        self.run_powershell_on_disk(volume, """
            $ProgressPreference = "SilentlyContinue"
            $mydisk | set-disk -IsOffline $true
        """)
        volume.disk_is_online = False

    def umount(self, volume, where, set_offline = False):
        self.run_powershell_on_disk(volume, """
            $ProgressPreference = "SilentlyContinue"
            $mydisk | Get-Partition | Remove-PartitionAccessPath -AccessPath \"{}\"
        """.format(volume.node.host.native_filename(where)))

        if set_offline:
            volume.set_disk_offline()

    def wipe_ntfs(self, volume):
        volume.node.run(["dd", "if=/dev/zero", "of={}".format(volume.device()), "count=128"])
        volume.set_disk_offline()
        volume.set_disk_online()

