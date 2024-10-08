# FIXME: Check for synchronized time on the test nodes.

# FIXME: For test cases with multiple resources, we only need to capture the
# consoles, dmesg logs, and event logs once. We need to prefix the .pos file names
# and the log messages with the resource name.

import os
import errno
import sys
import re
from enum import Flag, auto
import inspect
import json
import time
import pipes
import threading
import traceback
import socket
import argparse
import subprocess
import select
import signal
from subprocess import CalledProcessError
import atexit
from .ordered_set import OrderedSet
from . import disktools, tls
import io
import fnmatch

from io import StringIO

from lbpytest.controlmaster import SSH
from lbpytest.logscan import Logscan, InputStream


#Contants for set_fault_injection
DF_META_WRITE = 1
DF_META_READ = 2
DF_RESYNC_WRITE = 4
DF_RESYNC_READ = 8
DF_DATA_WRITE = 16
DF_DATA_READ = 32
DF_DATA_READ_AHEAD = 64
DF_BITMAP_ALLOC = 128
DF_PEERREQ_ALLOC = 256
DF_RECEIVE_CURRUPT = 512

#DRBD's packet types for block_packet_type()
P_DATA                = 0x00
P_DATA_REPLY	      = 0x01
P_RS_DATA_REPLY	      = 0x02
P_BARRIER	      = 0x03
P_BITMAP	      = 0x04
P_BECOME_SYNC_TARGET  = 0x05
P_BECOME_SYNC_SOURCE  = 0x06
P_UNPLUG_REMOTE	      = 0x07
P_DATA_REQUEST	      = 0x08
P_RS_DATA_REQUEST     = 0x09
P_SYNC_PARAM	      = 0x0a
P_PROTOCOL	      = 0x0b
P_UUIDS		      = 0x0c
P_SIZES		      = 0x0d
P_STATE		      = 0x0e
P_SYNC_UUID	      = 0x0f
P_AUTH_CHALLENGE      = 0x10
P_AUTH_RESPONSE	      = 0x11
P_STATE_CHG_REQ	      = 0x12
P_PING		      = 0x13
P_PING_ACK	      = 0x14
P_RECV_ACK	      = 0x15
P_WRITE_ACK	      = 0x16
P_RS_WRITE_ACK	      = 0x17
P_SUPERSEDED	      = 0x18
P_NEG_ACK	      = 0x19
P_NEG_DREPLY	      = 0x1a
P_NEG_RS_DREPLY	      = 0x1b
P_BARRIER_ACK	      = 0x1c
P_STATE_CHG_REPLY     = 0x1d
P_OV_REQUEST	      = 0x1e
P_OV_REPLY	      = 0x1f
P_OV_RESULT	      = 0x20
P_CSUM_RS_REQUEST     = 0x21
P_RS_IS_IN_SYNC	      = 0x22
P_SYNC_PARAM89	      = 0x23
P_COMPRESSED_BITMAP   = 0x24
P_DELAY_PROBE         = 0x27
P_OUT_OF_SYNC         = 0x28
P_RS_CANCEL           = 0x29
P_CONN_ST_CHG_REQ     = 0x2a
P_CONN_ST_CHG_REPLY   = 0x2b
P_RETRY_WRITE	      = 0x2c
P_PROTOCOL_UPDATE     = 0x2d
P_TWOPC_PREPARE       = 0x2e
P_TWOPC_ABORT         = 0x2f
P_DAGTAG	      = 0x30
P_TRIM                = 0x31
P_RS_THIN_REQ         = 0x32
P_RS_DEALLOCATED      = 0x33
P_WSAME               = 0x34
P_TWOPC_PREP_RSZ      = 0x35
P_ZEROES              = 0x36
P_PEER_ACK            = 0x40
P_PEERS_IN_SYNC       = 0x41
P_UUIDS110	      = 0x42
P_PEER_DAGTAG         = 0x43
P_CURRENT_UUID	      = 0x44
P_TWOPC_YES           = 0x45
P_TWOPC_NO            = 0x46
P_TWOPC_COMMIT        = 0x47
P_TWOPC_RETRY         = 0x48
P_CONFIRM_STABLE      = 0x49
P_RS_CANCEL_AHEAD     = 0x4a
P_DISCONNECT          = 0x4b
P_RS_DAGTAG_REQ       = 0x4c
P_RS_CSUM_DAGTAG_REQ  = 0x4d
P_RS_THIN_DAGTAG_REQ  = 0x4e
P_OV_DAGTAG_REQ       = 0x4f
P_OV_DAGTAG_REPLY     = 0x50
P_WRITE_ACK_IN_SYNC   = 0x51
P_RS_NEG_ACK          = 0x52
P_OV_RESULT_ID        = 0x53
P_RS_DEALLOCATED_ID   = 0x54

fio_write_args = {
        'verify': 'md5',
        'do_verify': 0,
        'rw': 'write'}

fio_verify_args = {
        'verify': 'md5',
        'verify_only': 1,
        'rw': 'read'}

fio_write_small_args = {
        **fio_write_args,
        'size': '4K',
        'randrepeat': 0}

drbd_config_dir = '/var/lib/drbd-test'
package_download_dir = '/opt/package-download'

silent = False
debug_level = 0
skip_cleanup = False
# possibly set by Cleanup.hook()
uncaught_exception = None

devnull = open(os.devnull, 'w')

# stream to write output to
logstream = None

state_twopc_regex = re.compile(r'Executing tid: (\d+)')

class MetadataFlag(Flag):
    CONSISTENT = auto()
    PRIMARY_IND = auto()
    WAS_UP_TO_DATE = auto()
    CRASHED_PRIMARY = auto()
    AL_CLEAN = auto()
    AL_DISABLED = auto()
    PRIMARY_LOST_QUORUM = auto()
    PEER_CONNECTED = auto()
    PEER_OUTDATED = auto()
    PEER_FENCING = auto()
    PEER_FULL_SYNC = auto()
    PEER_DEVICE_SEEN = auto()
    NODE_EXISTS = auto()
    HAVE_BITMAP = auto()


class Tee(object):
    """
    replicates writes to streams
    """

    def __init__(self):
        self.streams = set()

    def add(self, stream):
        # Do not modify self.streams in place. Another thread may be iterating over it.
        streams = set(self.streams)
        streams.add(stream)
        self.streams = streams

    def remove(self, stream):
        # Do not modify self.streams in place. Another thread may be iterating over it.
        streams = set(self.streams)
        streams.remove(stream)
        self.streams = streams

    def write(self, message):
        for stream in self.streams:
            stream.write(message)

    def flush(self):
        for stream in self.streams:
            stream.flush()


class FirstWriteTrap(object):
    """
    Captures the first write and passes subsequent writes through.
    """

    def __init__(self, target, condition):
        self.target = target
        self.condition = condition
        self.first_message = None

    def write(self, message):
        if self.first_message is None:
            with self.condition:
                self.first_message = message
                self.condition.notify()
        else:
            self.target.write(message)

    def flush(self):
        self.target.flush()


def log(*args, **kwargs):
    """ Print message to stderr """
    print(*args, file=logstream)
    logstream.flush()


def debug(*args, **kwargs):
    """ Print debug message according to configured debug level. """

    level = 1
    try:
        level = kwargs.pop('level')
    except:
        pass
    if level <= debug_level:
        print(*args, file=logstream)


class Cleanup(object):
    """ Catch uncaught exceptions, set skip_cleanup accordingly and log. """

    def __init__(self, cleanup):
        sys.excepthook = self.hook
        self.cleanup = cleanup
        if self.cleanup == 'never':
            global skip_cleanup
            skip_cleanup = True

    def hook(self, etype, value, tb):
        if self.cleanup == 'success':
            global skip_cleanup
            skip_cleanup = True
        if etype == subprocess.CalledProcessError and hasattr(value, 'output') and value.output is not None:
            log(value.output.decode(encoding='utf-8', errors='backslashreplace'))
        traceback.print_exception(etype, value, tb, file=logstream)
        global uncaught_exception
        uncaught_exception = { 'exc_type': etype, 'exc_value': value, 'exc_tb': tb }


def first(iterable):
    return next(iter(iterable))


class Collection(object):
    """ A collection of Nodes, Volumes, Connections, or PeerDevices. """

    def __init__(self, cls, members=[]):
        self.cls = cls
        self.members = OrderedSet(members)
        for member in members:
            assert issubclass(member.__class__, self.cls) and \
                self.same_resource(members)

    def same_resource(self, members):
        if self.members:
            resource = first(self.members).resource
            return all(member.resource is resource for member in members)
        elif members:
            resource = members[0].resource
            return all(member.resource is resource for member in members[1:])
        else:
            return True

    def __len__(self):
        return len(self.members)

    def __getattr__(self, name):
        """
        For unknown attributes in an object, if the member class has a function
        of that name, call each member's function.  For efficiency, create
        that function in the collection object as well.
        """
        attr = getattr(self.cls, name)
        if not attr or not callable(attr):
            raise AttributeError()

        def func(*args, **kwargs):
            for node in self.members:
                getattr(node, name)(*args, **kwargs)
        setattr(self, name, func)
        # FIXME: It should be possible to set the attribute in the class as well.
        return func

    @staticmethod
    def property(collection, name):
        """ Define collection.property as the union of all
        member.property values. """

        def func(self):
            result = collection()
            for member in self.members:
                result.extend(getattr(member, name))
            return result
        return property(func)

    def __repr__(self):
        return ' '.join([str(_) for _ in self])

    def __iter__(self):
        return iter(self.members)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return self.__class__(list(self.members)[index])
        else:
            return list(self.members)[index]

    def add(self, member):
        assert issubclass(member.__class__, self.cls)
        assert self.same_resource([member])
        self.members.add(member)
        return self

    def remove(self, member):
        assert issubclass(member.__class__, self.cls)
        assert self.same_resource([member])
        if member in self.members:
            self.members.remove(member)
        return self

    def extend(self, members):
        for member in members:
            assert issubclass(member.__class__, self.cls)
            assert self.same_resource(members)
        self.members.update(members)
        return self

    def difference(self, members):
        for member in members:
            assert issubclass(member.__class__, self.cls) and \
                self.same_resource(members)
        # TODO: sort result? manual loop, to keep the original order?
        return self.__class__(self.members.difference(members))

    def pop(self):
        if len(self) == 0:
            raise RuntimeError("Can't pop if empty")
        member = self[0]
        self.remove(member)
        return member


class Nodes(Collection):
    def __init__(self, members=[]):
        super(Nodes, self).__init__(Node, members)

    # The other classes are not defined yet, so defer defining the
    # corresponding properties.
    @classmethod
    def finish(cls):
        cls.volumes = Collection.property(Volumes, 'volumes')
        cls.connections = Collection.property(Connections, 'connections')
        cls.peer_devices = Collection.property(PeerDevices, 'peer_devices')

    def resource(self):
        return first(self.members).resource

    def min_drbd_version_tuple(self):
        return min([node.host.drbd_version_tuple for node in self.members])

    def event(self, *args, **kwargs):
        """ Wait for an event. """

        if self.members:
            filters = {node.name: [[]] for node in self.members}
            return self.resource().logscan(args, filters, **kwargs)
        return []

    def run(self, *args, **kwargs):
        """ Run command on all our nodes. """

        for node in self.members:
            node.run(*args, **kwargs)

    def drbdadm(self, *args, **kwargs):
        for node in self.members:
            node.drbdadm(*args, **kwargs)

    def up(self, extra_options=[]):
        # the order of disk/connection setup isn't strictly defined.
        # make sure that a defined order is seen, so that event matching works.
        self.drbdadm(['up', self.resource().name] + extra_options)

        # doesn't work either.
        #   + drbdmeta 1 v08 /dev/scratch/compat-with-84.new-20150504-103023-disk0 internal apply-al
        #   Device '1' is configured!
        #   + drbdsetup-84 attach 1 /dev/scratch/compat-with-84.new-20150504-103023-disk0 /dev/scratch/compat-with-84.new-20150504-103023-disk0 internal
        #   1: Failure: (124) Device is attached to a disk (use detach first)
        #self.run(['bash', '-c', 'drbdadm up all -v | grep -v " connect " | PATH=/lib/drbd:$PATH bash -x'])
        #self.volumes.diskful.event(r'device .* disk:Inconsistent')
        #self.run(['bash', '-c', 'drbdadm up all -v | grep    " connect " | PATH=/lib/drbd:$PATH bash -x'])

        if proxy_enable:
            self.drbdadm(['proxy-up', self.resource().name] + extra_options)

    def down(self):
        if proxy_enable:
            self.drbdadm(['proxy-down', self.resource().name])

        remove_patterns = []
        for pattern in [r'connection:BrokenPipe', r'connection:NetworkFailure']:
            if pattern in self.resource().forbidden_patterns:
                remove_patterns.append(pattern)
        if r'disk:Failed' in self.resource().forbidden_patterns and self.min_drbd_version_tuple() < (9, 0, 0):
            remove_patterns.append(r'disk:Failed')
        self.resource().forbidden_patterns.difference_update(remove_patterns)
        self.drbdadm(['down', self.resource().name])
        self.event(r'destroy resource')
        self.resource().forbidden_patterns.update(remove_patterns)

    def attach(self):
        self.volumes.attach()

    def detach(self):
        self.volumes.detach()

    def new_resource(self):
        self.drbdadm(['new-resource', self.resource().name])
        self.event(r'create resource')

    def new_minor(self):
        self.drbdadm(['new-minor', self.resource().name])
        self.volumes.event(r'create device')

    def new_peer(self):
        self.drbdadm(['new-peer', self.resource().name])
        self.volumes.peer_devices.event(r'create peer-device')

    def resource_options(self, opts=[]):
        self.drbdadm(['resource-options', self.resource().name] + opts)

    def peer_device_options(self, opts=[]):
        self.drbdadm(['peer-device-options', self.resource().name] + opts)

    def new_path(self):
        self.drbdadm(['new-path', self.resource().name])
        self.connections.event(r'create path')

    def up_unconnected(self):
        self.new_resource()
        self.new_minor()
        self.new_peer()
        self.peer_device_options()
        self.new_path()
        self.attach()
        self.volumes.diskful.event(r'device .* disk:(Failed|Inconsistent|Outdated|Consistent|UpToDate)')

    def get_diskful(self):
        """ Return nodes that have at least one disk. """
        return Nodes([node for node in self
                      if any(volume.disk is not None
                             for volume in node.volumes)])
    diskful = property(get_diskful)

    def get_diskless(self):
        """ Return nodes that have no disks. """
        return Nodes([node for node in self
                      if all(volume.disk is None for volume in node.volumes)])
    diskless = property(get_diskless)

    def adjust(self):
        for n in self.members:
            n.adjust()


class Volumes(Collection):
    def __init__(self, members=[]):
        super(Volumes, self).__init__(Volume, members)

    # The other classes are not defined yet, so defer defining the
    # corresponding properties.
    @classmethod
    def finish(cls):
        cls.peer_devices = Collection.property(PeerDevices, 'peer_devices')

    def event(self, *args, **kwargs):
        """ Wait for an event. """

        if self.members:
            filters = {}
            for volume in self.members:
                node = volume.node
                volume_number = volume.volume
                if node.name not in filters:
                    filters[node.name] = []
                filters[node.name].append(['volume:{}'.format(volume_number)])
            resource = first(self.members).resource
            return resource.logscan(args, filters, **kwargs)
        return []

    def get_diskful(self):
        """ Return volumes that have a disk. """
        return Volumes([_ for _ in self if _.disk is not None])
    diskful = property(get_diskful)

    def get_diskless(self):
        """ Return volumes that do not have a disk. """
        return Volumes([_ for _ in self if _.disk is None])
    diskless = property(get_diskless)

    def resize(self, size):
        return [v.resize(size) for v in self if v.disk is not None]

    def write(self, **kwargs):
        """ Write some data to each of the volumes using fio. """
        for v in self:
            v.write(**kwargs)

    def fio(self, *args, **kwargs):
        """ Run fio on each of the volumes. """
        for v in self:
            v.fio(*args, **kwargs)

    def suspend(self):
        for v in self:
            v.suspend()

    def resume(self):
        for v in self:
            v.resume()

    def attach(self):
        for v in self:
            v.node.drbdadm(['attach', '{}/{}'.format(v.resource.name, v.volume)])
        self.event(r'device .* disk:Attaching')

    def detach(self):
        if not self.members:
            return

        resource = list(self.members)[0].resource
        remove_patterns = []
        if r'disk:Failed' in resource.forbidden_patterns and resource.nodes.min_drbd_version_tuple() < (9, 0, 0):
            remove_patterns.append(r'disk:Failed')

        resource.forbidden_patterns.difference_update(remove_patterns)
        for v in self:
            v.node.drbdadm(['detach', '{}/{}'.format(v.resource.name, v.volume)])
        self.event(r'device .* disk:(Failed|Detaching)')
        self.event(r'device .* disk:Diskless')
        resource.forbidden_patterns.update(remove_patterns)

    def new_current_uuid(self):
        for v in self:
            v.new_current_uuid()

    def new_minor(self):
        for v in self:
            v.new_minor()


class Connections(Collection):
    def __init__(self, members=[]):
        super(Connections, self).__init__(Connection, members)

    def event(self, *args, **kwargs):
        """ Wait for an event. """

        if self.members:
            filters = {}
            for n0, n1 in self.members:
                if n0.name not in filters:
                    filters[n0.name] = []
                if n0.host.drbd_version_tuple >= (9, 0, 0):
                    filters[n0.name].append(['peer-node-id:{}'.format(n1.id)])
                else:
                    filters[n0.name].append([])
            resource = first(self.members).resource
            return resource.logscan(args, filters, **kwargs)
        return []

    def run_drbdadm(self, cmd, state_str, wait=True, options=[]):
        for connection in self:
            node0, node1 = connection.nodes
            if node0.host.drbd_version_tuple >= (9, 0, 0):
                context = '{}:{}'.format(connection.resource.name, node1.host.hostname)
            else:
                context = connection.resource.name
            node0.drbdadm([cmd] + options + [context])
        if wait:
            self.event(r'connection .* connection:%s' % (state_str))

    def connect(self, wait=True, options=[]):
        self.run_drbdadm('connect', 'Connecting', wait, options)

    def disconnect(self, wait=True, force=False):
        self.run_drbdadm('disconnect', 'StandAlone', wait, ['--force'] if force else [])

    def run_cmd(self, *args):
        for connection in self:
            connection.run_cmd(*args)

    def bidir_add(self, node1, node2):
        self.add(Connection(node1, node2))
        self.add(Connection(node2, node1))

    def block(self, *args, **kwargs):
        for connection in self:
            connection.block(*args, **kwargs)

    def unblock(self, *args, **kwargs):
        for connection in self:
            connection.unblock(*args, **kwargs)

    def protocol_versions(self):
        versions = []
        for connection in self:
            versions.append(connection.protocol_version())
        return tuple(versions)

class PeerDevices(Collection):
    def __init__(self, members=[]):
        super(PeerDevices, self).__init__(PeerDevice, members)

    @classmethod
    def from_connections(cls, connections, volumes=[]):
        if not volumes:
            cluster_volumes = connections[0].resource.volumes
            volumes = [ x for x in cluster_volumes if x.node == connections[0].nodes[0] ]
        return cls([PeerDevice(c, v) for c in connections for v in volumes])

    def event(self, *args, **kwargs):
        """ Wait for an event. """

        if self.members:
            filters = {}
            for peer_device in self.members:
                n0, n1 = peer_device.connection
                volume = peer_device.volume.volume
                if n0.name not in filters:
                    filters[n0.name] = []
                filter = ['volume:{}'.format(volume)]
                if n0.host.drbd_version_tuple >= (9, 0, 0):
                    filter.append('peer-node-id:{}'.format(n1.id))
                filters[n0.name].append(filter)
            resource = first(self.members).resource
            return resource.logscan(args, filters, **kwargs)
        return []

    def peer_device_options(self, opts=[]):
        for pd in self:
            node0, node1 = pd.connection.nodes
            node0.drbdadm(['peer-device-options', '%s:%s' %
                       (pd.connection.resource.name, node1.host.hostname), opts])

    def verify(self, wait=True, options=[]):
        for pd in self:
            node0, node1 = pd.connection.nodes
            res = pd.connection.resource.name
            node0.drbdadm(['verify'] + options +
                      ['%s:%s/%d' % (res, node1.host.hostname, pd.volume.volume)])
        if wait:
            self.event(r'peer-device .* replication:VerifyS')

# Now that all collection classes are defined, define inter-class dependencies:
Nodes.finish()
Volumes.finish()


class Cluster(object):
    """
    Container for all hosts and resources.

    In LINSTOR this is roughly equivalent to the "controller".
    """

    def __init__(self, job, logdir, drbd_version, drbd_version_other, resource_name, transport, tls):
        self.job = job
        self.logdir = logdir
        self.drbd_version = drbd_version
        self.drbd_version_other = drbd_version_other
        self.resource_name = resource_name
        self.transport = transport
        self.tls = tls
        self.hosts = []
        self.resources = []
        self.logscan_events = None
        atexit.register(self.cleanup)

    def cleanup(self):
        if not skip_cleanup:
            for host in self.hosts:
                host.cleanup()
        for host in self.hosts:
            host.cleanup_framework()
        # The atexit cleanup handlers may spam the output.
        # I'd still like to have a clear indication about "test failed"
        # as the last line on stderr.
        global uncaught_exception
        if uncaught_exception:
            print("\ntest failed:\n{}{}".format(
		''.join(traceback.format_tb(uncaught_exception["exc_tb"], limit=1)),
		''.join(traceback.format_exception_only(uncaught_exception["exc_type"], uncaught_exception["exc_value"]))),
                file=logstream)
        # else: we cannot be sure about the exit code, so don't claim "Success".

    def teardown(self, validate_dmesg=True):
        """
        Tear down test infrastructure. That is, remove the DRBD module and validate
        the logs.

        This should be called at the end of a successful test run. General
        cleanup is performed by functions registered with "atexit".
        """
        ok = True
        for host in self.hosts:
            host.rmmod()
            host_ok = host.teardown(validate_dmesg)
            if not host_ok:
                ok = False
        if not ok:
            sys.exit(3)

    def listen_to_events(self):
        logscan_inputs = {}
        for host in self.hosts:
            logscan_inputs[host.name] = host.listen_to_events()

        self.logscan_events = Logscan(logscan_inputs, timeout=30)
        self.logscan([r'exists -'],
                {host.name: [[]] for host in self.hosts},
                word_boundary=False)

    def logscan(self, yes=[], filters=[], no=[], always_no=[], **kwargs):
        """ Wait for events to occur. """
        if isinstance(no, str):
            no = [no]

        return self.logscan_events.event(
                yes=yes,
                no=no,
                always_no=always_no,
                filters=filters,
                wordwise=not 'word_boundary' in kwargs or kwargs['word_boundary'],
                timeout=kwargs.get('timeout'),
                verbose_out=logstream)

    def validate_drbd_versions(self):
        """
        Check the expected DRBD versions of the cluster hosts. If
        self.drbd_version_other is set, validate that this version is installed
        on hosts[0]. If self.drbd_version is set, validate that this version is
        installed on all other hosts and all git hashes match.

        Both drbd_version and drbd_version_other may contain wildcards, as in
        "9.2.*".
        """

        git_hashes = set()

        for host in self.hosts:
            expect_version = None
            if self.drbd_version_other and host.has_other_version:
                expect_version = self.drbd_version_other
            elif self.drbd_version:
                expect_version = self.drbd_version
                git_hashes.add(host.drbd_git_hash)

            if expect_version and not fnmatch.fnmatchcase(host.drbd_version, expect_version):
                raise RuntimeError("{}: expect DRBD version '{}'; found '{}'".format(host, expect_version, host.drbd_version))

        if len(git_hashes) > 1:
            raise RuntimeError("Differing git hashes found for DRBD version '{}': {}".format(self.drbd_version, git_hashes))

    def write_drbd_versions_meta(self, f):
        data = {}
        for i, host in enumerate(self.hosts):
            try:
                pkg = host.run_helper('installed-drbd-package', return_stdout=True)
            except CalledProcessError:
                # when drbd is compiled into the kernel, there will be no drbd
                # package installed and the helper will fail. just ignore this
                # condition and return an empty package.
                pkg = ''
            data[host.name] = {
                'version': host.drbd_version,
                'git_hash': host.drbd_git_hash,
                'package': pkg,
            }
        json.dump(data, f)

    def create_resource(self, name=None):
        resource = Resource(self, self.resource_name if name is None else name,
                            transport=self.transport, tls=self.tls)

        for host in self.hosts:
            Node(host, resource, port=host.next_port())

        for node0 in resource.nodes:
            for node1 in resource.nodes:
                if node0 != node1:
                    node0.connections.add(Connection(node0, node1))

        self.resources.append(resource)
        return resource

    def create_storage_pool(self, thin=False, discard_granularity=None):
        for host in self.hosts:
            host.create_storage_pool(thin=thin, discard_granularity=discard_granularity)

    def remove_storage_pool(self):
        for host in self.hosts:
            host.remove_storage_pool()


class Resource(object):
    """
    A single DRBD resource spanning multiple hosts.

    In LINSTOR this is called a "resource definition".
    """

    def __init__(self, cluster, name, transport, tls):
        self.cluster = cluster
        self.name = name
        self._net_options = ""
        self._disk_options = ""
        self._resource_options = ""
        # NOTE: (wap) Not needed for now
        # self.proxy_options = ""
        self._handlers = ""
        self.nodes = Nodes()
        self.num_volumes = 0
        self.transport = transport
        self.tls = tls
        self.forbidden_patterns = OrderedSet()
        self.forbidden_patterns.update([
            r'connection:Timeout',
            r'connection:ProtocolError',
            r'disk:Failed',
            r'peer-disk:Failed'])
        atexit.register(self.cleanup)

    def __repr__(self):
        return self.name

    def next_volume(self):
        volume = self.num_volumes
        self.num_volumes += 1
        return volume

    def remove_storage_pool(self):
        self.nodes.remove_disks()
        self.num_volumes = 0
        self.cluster.remove_storage_pool()

    def add_disk(self, size, *, meta_size=None, diskful_nodes=None, max_size=None, max_peers=None, delay_ms=None, logical_block_size=None):
        """
        Create and add a new disk on some or all nodes.

        Keyword arguments:
        size            -- size of the data device
        meta_size       -- size of the meta-data device,
                           or "None" for internal meta-data
        diskful_nodes   -- nodes which shall have a local lower-level device
                           (defaults to all nodes)
        max_size        -- maximum we expect this disk to be resized to
        max_peers       -- maximum number of peers to reserve metadata for
        """

        volume_number = self.next_volume()
        diskful_volumes = []

        for node in self.nodes:
            if diskful_nodes is None or node in diskful_nodes:
                diskful_volumes.append(node.add_disk(
                    volume_number, size, meta_size=meta_size, max_size=max_size, delay_ms=delay_ms, logical_block_size=logical_block_size))
            else:
                node.add_disk(volume_number)

        for volume in diskful_volumes:
            volume.create_md(max_peers)

        return volume_number

    volumes = property(lambda self: self.nodes.volumes)
    connections = property(lambda self: self.nodes.connections)
    peer_devices = property(lambda self: self.nodes.peer_devices)

    @property
    def net_options(self):
        return self._net_options

    @net_options.setter
    def net_options(self, value):
        self._net_options = value
        self.touch_config()

    @property
    def disk_options(self):
        return self._disk_options

    @disk_options.setter
    def disk_options(self, value):
        self._disk_options = value
        self.touch_config()

    @property
    def resource_options(self):
        return self._resource_options

    @resource_options.setter
    def resource_options(self, value):
        self._resource_options = value
        self.touch_config()

    @property
    def handlers(self):
        return self._handlers

    @handlers.setter
    def handlers(self, value):
        self._handlers = value
        self.touch_config()

    def set_fencing_mode(self, mode):
        for node in self.nodes:
            node.fencing_mode = mode

    def cleanup(self):
        if not skip_cleanup:
            for node in self.nodes:
                node.cleanup()

    def logscan(self, yes, filters, no=[], **kwargs):
        """
        Wait for events to occur.

        Warning: Resource.forbidden_patterns applies to log lines for all
        resources.
        """
        # Only add resource name filter if there is more than one resource to keep the logs clean
        if len(self.cluster.resources) > 1:
            filters = {node_name: [[r'name:{}'.format(self.name)] + filter_set for filter_set in node_filters]
                    for node_name, node_filters in filters.items()}

        return self.cluster.logscan(yes, filters,
                no, self.forbidden_patterns, **kwargs)

    def up(self, extra_options=[]):
        self.nodes.up(extra_options)

    def skip_initial_sync(self):
        node = self.nodes.diskful[0]
        # set to remove duplicates ?!!
        res_vols = set(["%s/%d" % (self.name, v.volume) for v in self.volumes if v.disk])
        node.drbdadm(["new-current-uuid", "--clear-bitmap"] + list(res_vols))
        # wait for completion
        self.initial_resync()

    def up_wait(self, extra_options=[], expected_disk_states=["Inconsistent", "Diskless"]):
        self.up(extra_options)

        ## Each node waits for the other nodes to connect.
        #c = Connections()
        #for n1 in self.nodes:
        #    for n2 in self.nodes:
        #        if n1 != n2:
        #            c.add(Connection(n1, n2))
        #c.event(r'connection .* connection:Connected', timeout=30)
        # Since we might consume a peer-device event between two connection events,
        # the commented out code block will cause the following code block to fail.
        # We would need to save and restore the events position...

        # Wait until all the peer's disks are known
        pds = PeerDevices()
        for n1 in self.nodes:
            for n2 in self.nodes:
                if n1 != n2:
                    for v in self.nodes[0].volumes:
                        pds.add(PeerDevice(Connection(n1, n2), v))
        pds.event(r'peer-device .* peer-disk:({})'.format(r'|'.join(expected_disk_states)), timeout=30)

        # This can occur while connecting due to receive timeouts during
        # two-phase commit resolution. Add it now that the nodes are connected.
        self.forbidden_patterns.add(r'connection:BrokenPipe')
        # Similarly, this can occur while connecting with DRBD 9.2+.
        self.forbidden_patterns.add(r'connection:NetworkFailure')

    def down(self, concurrent=False):
        # Avoid spurious test failures,
        # avoid exercising concurrent down on all nodes.
        # We have a dedicated test for that.
        # By default, serialize the down() on the nodes.
        if concurrent:
            self.nodes.down()
        else:
            for node in self.nodes:
                node.down()

    def initial_resync(self, timeout=300):
        # All diskless nodes should see all diskfull nodes as UpToDate
        diskful_nodes = self.nodes.diskful
        pds = PeerDevices()
        for dln in self.nodes.diskless:
            for v in diskful_nodes[0].volumes:
                for dfn in diskful_nodes:
                    pds.add(PeerDevice(Connection(dln, dfn), v))
        # All diskful nodes should see all other diskfull nodes as UpToDate as well.
        for n1 in diskful_nodes:
            for v in diskful_nodes[0].volumes:
                for n2 in diskful_nodes:
                    if n1 != n2:
                        pds.add(PeerDevice(Connection(n1, n2), v))
        pds.event(r'peer-device .* peer-disk:UpToDate', timeout=timeout)

    def touch_config(self):
        for n in self.nodes:
            n.config_changed = True

    def add_node(self, new_node):
        self.nodes.add(new_node)
        self.touch_config()

    def remove_node(self, del_node):
        self.nodes.remove(del_node)
        self.touch_config()

    def rename(self, new_name):
        self.nodes.run(["drbdsetup", "rename-resource", self.name, new_name])
        # Wait for rename event before changing self.name because event() may
        # filter by resource name
        self.nodes.event(r'rename resource name:{} new_name:{}'.format(self.name, new_name))
        self.name = new_name
        self.touch_config()

    def volumes_by_vnr(self, vnr):
        return Volumes([v for v in self.volumes if v.volume == vnr])

    def peer_devices_by_vnr(self, vnr):
        return PeerDevices([pd for pd in self.peer_devices if pd.volume.volume == vnr])

    def log_sync_mark(self, *args, **kwargs):
            """ Print message to stderr and all nodes /dev/kmsg """
            log(*args)
            self.nodes.run(['bash', '-c', 'echo "== " {} > /dev/kmsg'.format(
                        pipes.quote(' '.join(map(str,args))))])

class Volume(object):
    def __init__(self, node, volume, minor=None):
        if volume is None:
            volume = node.resource.next_volume()
        if minor is None:
            minor = node.host.next_minor()
        self.volume = volume
        self.minor = minor
        self.node = node
        self.disk_volume = None
        self.meta_volume = None
        self.disk_lv = None
        self.meta_lv = None

    def get_resource(self):
        return self.node.resource
    resource = property(get_resource)

    def get_peer_devices(self):
        peer_devices = PeerDevices()
        for connection in self.node.connections:
            peer_devices.add(PeerDevice(connection, self))
        return peer_devices
    peer_devices = property(get_peer_devices)

    def __repr__(self):
        return '%s:%s' % (self.node, self.volume)

    def create_disks(self, size, meta_size=None, *, max_size=None, delay_ms=None, logical_block_size=None):
        self.disk_lv = '{}-disk{}'.format(self.node.resource.name, self.volume)
        self.disk_volume = disktools.create_disk(self.node.host, self.disk_lv,
                size, max_size=max_size, delay_ms=delay_ms, logical_block_size=logical_block_size)
        if meta_size:
            self.meta_lv = '{}-meta{}'.format(self.node.resource.name, self.volume)
            self.meta_volume = disktools.create_disk(self.node.host, self.meta_lv,
                meta_size, delay_ms=delay_ms, logical_block_size=logical_block_size)

    @property
    def disk(self):
        return self.disk_volume.volume_path() if self.disk_volume else None

    @property
    def meta(self):
        return self.meta_volume.volume_path() if self.meta_volume else None

    def create_md(self, max_peers=None):
        if max_peers is None:
            max_peers = len(self.node.resource.nodes) - 1
            if max_peers < 1:
                max_peers = 1
        disktools.create_md(self.node, self.volume, max_peers=max_peers)

    def event(self, *args, **kwargs):
        return Volumes([self]).event(*args, **kwargs)

    def resize(self, size):
        # TODO: metadata-resize?
        self.disk_volume.resize(size)

    def device(self):
        return '/dev/drbd%d' % self.minor

    def write(self, **kwargs):
        """
        Write some data to the volume using fio.

        Keyword arguments override fio parameters. Example:
        volume.write(offset='10M')
        """
        self.node.fio_file(self.device(), fio_write_small_args, **kwargs)

    def fio(self, *args, **kwargs):
        """
        Run fio on the volume.

        Example:
        volume.fio(fio_write_args, bs='64K')
        """
        return self.node.fio_file(self.device(), *args, **kwargs)

    def dmsetup(self, cmd):
        dm_name = '%s-%s' % (self.node.host.volume_group.replace('-', '--'),
                             self.disk_lv.replace('-', '--'))
        self.node.run(['dmsetup', cmd, dm_name])

    def suspend(self):
        self.dmsetup('suspend')

    def resume(self):
        self.dmsetup('resume')

    def attach(self):
        Volumes([self]).attach()

    def detach(self):
        Volumes([self]).detach()

    def new_current_uuid(self):
        self.node.drbdadm(['new-current-uuid', '{}/{}'.format(self.node.resource.name, self.volume)])

    def new_minor(self):
        self.node.drbdadm(['new-minor', '{}/{}'.format(self.node.resource.name, self.volume)])

class Connection(object):
    def __init__(self, node1, node2):
        assert node1.resource is node2.resource
        self.nodes = (node1, node2)

    def get_resource(self):
        return self.nodes[0].resource
    resource = property(get_resource)

    def __repr__(self):
        # return '%s:%s:%s' % (self.nodes[0].resource, self.nodes[0].name, self.nodes[1].name)
        return '%s:%s' % (self.nodes[0].name, self.nodes[1].name)

    def __getitem__(self, key):
        return self.nodes[key]

    def __hash__(self):
        return hash(self.nodes)

    def __eq__(self, other):
        return self[0] is other[0] and self[1] is other[1]

    def event(self, *args, **kwargs):
        return Connections([self]).event(*args, **kwargs)

    def connect(self, *args, **kwargs):
        return Connections([self]).connect(*args, **kwargs)

    def disconnect(self, *args, **kwargs):
        return Connections([self]).disconnect(*args, **kwargs)

    def run_cmd(self, *args):
        self.nodes[0].drbdadm([*args, '%s:%s' %
                           (self.resource.name, self.nodes[1].host.hostname)])

    def pause_sync(self):
        self.run_cmd(['pause-sync'])

    def resume_sync(self):
        self.run_cmd(['resume-sync'])

    def block(self, *args, **kwargs):
        self.nodes[0].block_path(self.nodes[1], *args, **kwargs)

    def unblock(self, *args, **kwargs):
        self.nodes[0].unblock_path(self.nodes[1], *args, **kwargs)

    def protocol_version(self):
        resname = self.nodes[0].resource.name
        peer_name = self.nodes[1].name
        str = self.nodes[0].run(['sh', '-c',
                                 'grep agreed_pro_version: /sys/kernel/debug/drbd/resources/%s/connections/%s*/debug' % (resname, peer_name)],
                                return_stdout=True)
        m = re.match(r'\s*agreed_pro_version: ([0-9]+)', str);
        return int(m.group(1))

class PeerDevice(object):
    def __init__(self, connection, volume):
        self.connection = connection
        self.volume = volume

    def get_resource(self):
        return self.connection.resource
    resource = property(get_resource)

    def __repr__(self):
        return '%s:%s' % (self.connection, self.volume.volume)

    def __hash__(self):
        return hash((self.connection, self.volume))

    def __eq__(self, other):
        return self.connection is other.connection and \
            self.volume is other.volume

    def event(self, *args, **kwargs):
        return PeerDevices([self]).event(*args, **kwargs)

    def peer_device_options(self, opts=[]):
        PeerDevices([self]).peer_device_options(opts)

    def verify(self, wait=True, options=[]):
        PeerDevices([self]).verify(self, wait, options)

    def diskful(self):
        vol_nr = self.volume.volume
        node1, node2 = self.connection.nodes
        return node1.volume_by_vnr(vol_nr).disk_volume is not None and \
            node2.volume_by_vnr(vol_nr).disk_volume is not None

class AsPrimary(object):

    def __init__(self, node, force=False):
        self.node = node
        self.force = force

    def __enter__(self):
        self.node.primary(force=self.force)

    def __exit__(self, *ignore_exception):
        # Let processes detach correctly... eg. fio causes
        #   State change failed: (-12) Device is held open by someone
        # unless /lib/udev/rules.d/{13,60_persistent_storage}*
        # are patched to exclude DRBD from blkid
        self.node.secondary()


class ConfigBlock(object):
    INDENT = "     "

    _glob = threading.local()
    _glob.stack = ["top"]
    _stack = _glob.stack

    def __init__(self, parent=None, fh=None, fn=None, t="", dest_fn=None):
        self.parent = parent
        if not self.parent:
            self.parent = self._stack[-1]

        self.name = t
        self.fd = None
        self.to_var = dest_fn

        if self.parent != "top":
            self.indent = self.INDENT * len(self._stack)
            self.to_var = self.parent.to_var
            self.fd = self.parent.fd
            self.do_close = False
        else:
            if fh:
                self.fd = fh
                self.do_close = False
            elif fn:
                self.fd = open(fn, "wt")
                self.do_close = True

            self.indent = ""

        # should that be in __enter__()?
        self._stack.append(self)

    def __enter__(self):
        self.write_no_indent("%s%s {\n" % (self.indent, self.name))
        return self

    def __exit__(self, *ignore_exception):
        self.write_no_indent("%s}\n\n" % self.indent)

        if self.fd and self.do_close:
            self.fd.close()

        assert(self._stack.pop() == self)

    def write_no_indent(self, content):
        if self.to_var:
            return self.to_var(content)
        else:
            return self.fd.write(content)

    def write(self, data, *args):
        content = "%s%s%s" % (self.indent, self.INDENT, (data % args))
        if not content.endswith("\n"):
            content = content + "\n"

        self.write_no_indent(content)


class Host():
    """
    A host system where DRBD runs.

    In LINSTOR this is called a "node".
    """

    def __init__(self, cluster, name, volume_group, storage_backend, backing_device,
                 first_port=7789, addr=None, multi_paths=None, netns=None):
        self.cluster = cluster
        self.name = name
        self.port = first_port
        self.netns = None
        try:
            self.addr = addr if addr else socket.gethostbyname(name)
        except:
            raise RuntimeError('Could not determine IP for host %s' % name)

        try:
            self.ssh = SSH(self.addr, timeout=30)
        except subprocess.CalledProcessError as e:
            print(e.stderr.decode('utf-8'), file=sys.stderr)
            raise e

        self.events_file = None
        self.fio_count = 0
        self.minors = 0
        self.storage_pool = None
        self.volume_group = volume_group
        self.storage_backend = storage_backend
        self.backing_device = backing_device
        self.has_other_version = False
        self.read_drbd_version()

        if self.drbd_version_tuple < (9, 0, 0):
            hostname_cmd = ['hostname']
        else:
            hostname_cmd = ['hostname', '-f']
        self.hostname = self.run(hostname_cmd, return_stdout=True)

        self.os_id, self.os_version_id = self.run(
                ['bash', '-c', '. /etc/os-release ; echo $ID ; echo $VERSION_ID'],
                return_stdout=True).splitlines()
        log("host {} is running '{}' version '{}'".format(name, self.os_id, self.os_version_id))

        self.addrs = [self.addr]
        self.netdevs = {}

        addresses = self.run(['ip', '-oneline', 'addr', 'show'], return_stdout=True)
        log("got all addresses %s", addresses)
        for line in addresses.splitlines():
            m = re.search(r'^\s*\d+:\s+(\w+)\s+inet\s+([\d\.]+)/(\d+)', line)
            if not m:
                continue
            devname = m.group(1)
            addr = m.group(2)
            prefix = m.group(3)
            if addr == "127.0.0.1" or addr == self.addr:
                continue

            self.netdevs[devname] = {
                'address': addr,
                'prefix': prefix,
            }

        if multi_paths:
            if not self.netdevs:
                raise RuntimeError("%s has no additional address", self)

            log("got all addresses %s", addresses)
            for address_info in self.netdevs.values():
                self.addrs.append(address_info['address'])

        init_iptables = ["bash", "--norc", "-xec", inspect.cleandoc('''
                iptables -F drbd-test-input || iptables -N drbd-test-input
                iptables -F drbd-test-output || iptables -N drbd-test-output
                iptables -I INPUT -j drbd-test-input
                iptables -I OUTPUT -j drbd-test-output
                ''')]

        if netns:
            if not self.netdevs:
                raise RuntimeError("%s is missing additional netdevs to namespace", self)

            self.addrs = []
            self.run(['ip', 'netns', 'add', netns])
            for address_info in self.netdevs.values():
                self.addrs.append(address_info['address'])

            if len(self.addrs) < 1:
                raise RuntimeError("%s has namespaced address", self)

            # Also configure IPTABLES in the init_net namespace, some tests might use both
            self.run_quiet(init_iptables)

            # From now on, all run() commands run in <netns> namespace, unless explicitly excluded
            self.netns = netns
            # Now ensure all netdevs are moved to the right namespace
            self.ensure_netdev(netns=netns)

        self.run_quiet(init_iptables)

        self.start_dmesg()

        self.run(['mkdir', '-p', drbd_config_dir])
        global_config = 'global { usage-count no; }\n' + 'include "{}/{}*";\n'.format(
                drbd_config_dir, cluster.job)
        self.run(['bash', '-c', "cat > " + self.drbd_global_config_file_path()],
                stdin=StringIO(global_config))

    def ensure_netdev(self, netns=None):
        """
        Ensure that all initially configured netdevs are online and addresses are configured.

        Some older distributions drop this information while moving between namespaces.
        """
        for devname, address_info in self.netdevs.items():
            base = ['ip']
            if netns:
                self.run(['ip', 'link', 'set', 'dev', devname, 'netns', netns], ignore_netns=True)
                base = ['ip', '-netns', netns]

            try:
                self.run(base + [
                    'addr', 'add', '{}/{}'.format(address_info['address'], address_info['prefix']), 'dev', devname
                ], ignore_netns=True)
            except CalledProcessError:
                # The command fails if the address is already configured
                pass

            self.run(base + ['link', 'set', 'dev', devname, 'up'], ignore_netns=True)

    def read_drbd_version(self):
        # cat > /dev/kmsg so we have it in the dmesg stream,
        # even if the ring buffer wrapped since the module was loaded
        self.run(['bash', '-c', 'cat /proc/drbd > /dev/kmsg || modprobe drbd'])
        proc_drbd_lines = self.run(['cat', '/proc/drbd'], return_stdout=True).splitlines()
        version_line = proc_drbd_lines[0]
        git_hash_line = proc_drbd_lines[1]

        version_line_match = re.match(r'version: ([^ -]+).*', version_line)
        self.drbd_version = version_line_match.group(1)

        version_match = re.match(r'([0-9]+)\.([0-9]+)\.([0-9]+).*', self.drbd_version)
        self.drbd_version_tuple = int(version_match.group(1)), int(version_match.group(2)), int(version_match.group(3))

        # out-of-tree drbd uses "GIT-hash: 0a1b2c3d",
        # in-tree uses "srcversion: 0A1B2C3D"; allow both formats.
        hash_match = re.match(r'(?:srcversion|GIT-hash): ([0-9A-Fa-f]+).*', git_hash_line)
        self.drbd_git_hash = hash_match.group(1).lower()

    def cleanup(self):
        """
        Clean up resource artifacts. This may or may not be run depending on
        the command line argument "cleanup".
        """
        if self.storage_pool:
            self.remove_storage_pool()

    def cleanup_framework(self):
        """
        Clean up changes made for the test framework. This should always be
        run.
        """

        self.stop_dmesg()

        tlshd_log = self.run(["journalctl", "-u", "tlshd", "-b", "0", "-q"], return_stdout=True)
        if tlshd_log:
            with open(os.path.join(self.cluster.logdir, 'tlshd-{}'.format(self.name)), "w") as tlshd_logfile:
                tlshd_logfile.write(tlshd_log)

        cleanup_iptables = ["bash", "--norc", "-xec", inspect.cleandoc('''
                iptables -D INPUT -j drbd-test-input
                iptables -D OUTPUT -j drbd-test-output
                iptables -F drbd-test-input && iptables -X drbd-test-input || true
                iptables -F drbd-test-output && iptables -X drbd-test-output || true
                ''')]

        self.run_quiet(cleanup_iptables)

        if hasattr(self, 'events'):
            self.events.terminate()

        if self.events_file:
            self.events_file.close()

        log('{}: Closing connection to {}'.format(self.name, self.ssh.host))
        self.ssh.close()

    def start_dmesg(self):
        self.dmesg_out_stream = io.StringIO()

        out_path = os.path.join(self.cluster.logdir, 'dmesg-{}'.format(self.name))
        self.dmesg_out_file = open(out_path, 'w', encoding='utf-8')

        self.dmesg_out_tee = Tee()
        self.dmesg_out_tee.add(self.dmesg_out_stream)
        self.dmesg_out_tee.add(self.dmesg_out_file)

        condition = threading.Condition()
        self.dmesg_pid_trap = FirstWriteTrap(self.dmesg_out_tee, condition)

        self.dmesg_process = self.ssh.Popen('echo $$ ; dmesg --follow-new --time-format=iso || dmesg --follow')
        def dmesg_pipe():
            self.ssh.pipeIO(self.dmesg_process, stdout=self.dmesg_pid_trap)

        self.dmesg_thread = threading.Thread(target=dmesg_pipe, daemon=True)
        self.dmesg_thread.start()
        with condition:
            # Capture the remote process ID before stop_dmesg() is called
            condition.wait()

    def stop_dmesg(self):
        if self.dmesg_process:
            # Kill entire remote session
            self.run(['bash', '-c', 'kill $(ps -s {} -o pid=)'.format(
                self.dmesg_pid_trap.first_message.strip())])
            self.dmesg_process.terminate()
            self.dmesg_process.wait()
            self.dmesg_process = None

        if self.dmesg_thread:
            self.dmesg_thread.join()
            self.dmesg_thread = None

        if self.dmesg_out_file:
            self.dmesg_out_file.close()
            self.dmesg_out_file = None

    def teardown(self, validate_dmesg):
        self.stop_dmesg()

        ok = True
        if validate_dmesg:
            self.dmesg_out_stream.seek(0)
            text = self.dmesg_out_stream.read()

            pattern = re.compile(r'(BUG:|INFO:|ASSERTION|general protection fault)')

            for line in text.split('\n'):
                if pattern.search(line):
                    log('Unexpected log line on %s: %s' % (self.name, line))
                    ok = False

        return ok

    def add_dmesg_capture(self, out_stream):
        self.dmesg_out_tee.add(out_stream)

    def remove_dmesg_capture(self, out_stream):
        self.dmesg_out_tee.remove(out_stream)

    def __repr__(self):
        # return '%s:%s' % (self.resource, self.name)
        return self.name

    def install_helper(self, helper_name, target_path):
        """ Install a helper script to this node. """
        with open('target/{}'.format(helper_name)) as f:
            helper = f.read()
            self.run(['bash', '-c',
                'cat > {0} && chmod +x {0}'.format(target_path)],
                stdin=StringIO(helper))

    def run_helper(self, helper_name, args=[], timeout=None, return_stdout=False):
        """ Run a target helper script. """
        target_path = '/tmp/' + helper_name
        self.install_helper(helper_name, target_path)
        return self.run([target_path, *args], timeout=timeout, return_stdout=return_stdout)

    def rmmod(self):
        if no_rmmod:
            return
        if self.drbd_version_tuple >= (9, 0, 0):
            # might not even be loaded
            try:
                self.run(['rmmod', 'drbd_transport_tcp'])
            except:
                pass
            try:
                self.run(['rmmod', 'drbd_transport_lb-tcp'])
            except:
                pass
            try:
                self.run(['rmmod', 'drbd_transport_rdma'])
            except:
                pass
        try:
            self.run(['rmmod', 'drbd'])
        except:
            pass

    def install_drbd(self, version):
        self.rmmod()
        self.run_helper('install-drbd', [package_download_dir, version], timeout=90)
        self.read_drbd_version()
        for resource in self.cluster.resources:
            resource.touch_config()

    def next_minor(self):
        self.minors += 1
        return self.minors

    def next_port(self):
        port = self.port
        self.port += 1
        return port

    def create_storage_pool(self, thin=False, discard_granularity=None):
        if self.storage_pool:
            raise RuntimeError('storage pool already created')
        self.storage_pool = disktools.create_storage_pool(self, self.storage_backend, self.backing_device,
                thin=thin, discard_granularity=discard_granularity)

    def remove_storage_pool(self):
        if not self.storage_pool:
            raise RuntimeError('no storage pool to remove')

        self.storage_pool.remove()
        self.storage_pool = None

    def drbd_global_config_file_path(self):
        return '{}/{}.conf'.format(drbd_config_dir, self.cluster.job)

    def listen_to_events(self):
        if self.events_file:
            self.events_file.close()
        self.events_file = open(os.path.join(self.cluster.logdir, 'events-' + self.name), 'a')

        try:
            if self.events:
                self.events.terminate()
                self.events.wait()
        except:
            pass
        self.events = self.ssh.Popen('drbdsetup events2 all --statistics --timestamps')
        return InputStream(self.events.stdout, tee_out=self.events_file)

    def run(self, cmd, quote=True, catch=False, return_stdout=False, stdin=None, stdout=None, stderr=None, env={}, timeout=None, ignore_netns=False):
        """
        Run a command via SSH on the target node.

        :param cmd: the command as a list of strings
        :param quote: use shell quoting to prevent environment variable substitution in commands
        :param catch: report command failures on stderr rather than raising an exception
        :param return_stdout: return the stdout returned by the command instead of printing it
        :param stdin: standard input to command (file-like object)
        :param stdout: standard output from command (file-like object)
        :param sterr: standard error from command (file-like object)
        :param env: a dictionary of extra environment variables which will be exported to the command
        :param timeout: command timeout in seconds
        :param ignore_netns: optionally, ignore a node's configured network namespace
        :returns: nothing, or a string if return_stdout is True
        :raise CalledProcessError: when the command fails (unless catch is True)
        """
        stdout = stdout or logstream
        stderr = stderr or logstream
        stdin = stdin or False # False means no stdin
        if return_stdout:
            # if stdout should be returned, do not log stdout to logstream too
            stdout = StringIO()

        if quote:
            cmd_string = ' '.join(pipes.quote(str(x)) for x in cmd)
        else:
            cmd_string = ' '.join(cmd)

        if not ignore_netns and self.netns:
            cmd_string = "ip netns exec {} {}".format(self.netns, cmd_string)

        log(self.name + ': ' + cmd_string)
        result = self.ssh.run(cmd_string, env=env, stdin=stdin, stdout=stdout, stderr=stderr, timeout=timeout)
        if result != 0:
            if catch:
                print('error: {} failed ({})'.format(cmd[0], result), file=logstream)
            else:
                raise CalledProcessError(result, cmd_string)

        if return_stdout:
            return stdout.getvalue().strip()

    def run_quiet(self, cmd, quote=True, stdin=None, env={}, timeout=None, ignore_netns=False):
        """
        Run a command via SSH on the target node, logging output only if it fails.

        See the "run" method for documentation of the arguments.
        """

        out = StringIO()
        try:
            self.run(cmd, quote=quote, stdin=stdin, stdout=out, stderr=out, env=env, timeout=timeout, ignore_netns=ignore_netns)
        # Catch BaseException to include cases like KeyboardInterrupt
        except BaseException as e:
            logstream.write(out.getvalue())
            raise e

    def fio_file(self, filename, base_args={}, **kwargs):
        """
        Run fio on a given file.

        base_args is a dict mapping fio parameter keys to their values

        The remaining keyword arguments also specify fio parameters. These
        parameters override the base_args.
        """
        arg_dict = {'filename': filename, **base_args, **kwargs}
        fio_args = ['--{}={}'.format(key, value) for (key, value) in arg_dict.items()]

        cmd = ['fio',
                '--output-format=json',
                # reduce the amount of memory which fio tries to allocate
                '--max-jobs=16',
                '--name=test',
                *fio_args]

        result = self.run(cmd, return_stdout=True)

        output_filename = 'fio-{}-{}.json'.format(self.name, self.fio_count)
        log('write fio output to {}'.format(output_filename))
        with open(os.path.join(self.cluster.logdir, output_filename), 'w') as output_file:
            output_file.write(result)

        fio_output = json.loads(result)

        job = fio_output['jobs'][0]
        log('fio results: read={}KiB, write={}KiB, time={}s'.format(
            job['read']['io_kbytes'],
            job['write']['io_kbytes'],
            job['elapsed']))

        self.fio_count = self.fio_count + 1
        return fio_output

    def net_device_to_peer(self, peer_host, net_num=0):
        """Returns the network device this peer is reachable via."""
        lines = self.run(['ip', '-o', 'route', 'get', peer_host.addrs[net_num]],
                         return_stdout=True)
        fields = lines.split(' ')
        dev = fields[2]
        return dev


class Node():
    """
    A single DRBD resource on a single host.

    In LINSTOR this is called a "resource".
    """

    def __init__(self, host, resource, port):
        self._fencing_mode = ""
        self.host = host
        self.resource = resource
        self.name = host.name

        self.port = port
        self.disks = []  # by volume
        self.id = len(self.resource.nodes)
        self.resource.nodes.add(self)
        self.config_changed = True
        self.connections = Connections()

    def cleanup(self):
        """
        Clean up resource artifacts. This may or may not be run depending on
        the command line argument "cleanup".
        """
        self.run(['bash', '-c',
            '! [ -e /proc/drbd ] || drbdsetup down {}'.format(self.resource.name)],
            update_config=False)

        self.remove_disks()

    def __repr__(self):
        return '{}:{}'.format(self.resource, self.name)

    def add_disk(self, volume_number, size=None, *, meta_size=None, max_size=None, delay_ms=None, logical_block_size=None):
        """
        Keyword arguments:
        volume_number -- volume number of the new disk
        size -- size of the data device or None for a diskless node
        meta_size -- size of the meta-data device
        max_size -- maximum we expect this disk to be resized to
        thin -- whether to create a thin provisioned disk
        """

        # Create storage pool if not yet created
        if not self.host.storage_pool:
            self.host.create_storage_pool()

        if volume_number >= len(self.disks):
            minor = None
        else:
            minor = self.disks[volume_number].minor
        volume = Volume(self, volume_number, minor=minor)
        if size is not None:
            volume.create_disks(size, meta_size, max_size=max_size, delay_ms=delay_ms, logical_block_size=logical_block_size)
        if volume_number >= len(self.disks):
            self.disks.append(volume)
        else:
            self.disks[volume_number] = volume
        self.config_changed = True
        return volume

    def remove_disks(self):
        for volume in self.disks:
            if volume.disk_volume:
                volume.disk_volume.remove()
            if volume.meta_volume:
                volume.meta_volume.remove()

        self.disks = []

    @property
    def fencing_mode(self):
        return self._fencing_mode

    @fencing_mode.setter
    def fencing_mode(self, value):
        self._fencing_mode = value
        self.config_changed = True

    def _config_conns_84(self):
        # no explicit connections for 8.4
        # done via "address" in "on <host>" section
        pass

    def _config_one_host_addr(self, node, block, addr):
        block.write("host %s address %s:%d;" %
                    (node.name,
                     addr,
                     node.port))

    def _config_one_connection(self, n1, n2):
        with ConfigBlock(t="connection"):
            port_inside = self.port
            port_outside = self.port

            if proxy_enable:
                with ConfigBlock(t='host %s address 127.0.0.1:%s via proxy on %s'
                        % (n1.name, n1.port, n1.name)) as N1:
                    N1.write("inside 127.0.0.2:%s;" % port_inside)
                    N1.write("outside ipv4 %s:%s;"% (n1.host.addrs[0], port_outside))
                with ConfigBlock(t='host %s address 127.0.0.1:%s via proxy on %s'
                        % (n2.name, n2.port, n2.name)) as N2:
                    N2.write("inside 127.0.0.2:%s;" % port_inside)
                    N2.write("outside ipv4 %s:%s;"% (n2.host.addrs[0], port_outside))
                with ConfigBlock(t='net') as NET_OPTS:
                    NET_OPTS.write("protocol A;")
            else:
                with ConfigBlock(t='net'):
                    pass

                for a1, a2 in zip(n1.host.addrs, n2.host.addrs):
                    with ConfigBlock(t='path') as path:
                        self._config_one_host_addr(n1, path, a1)
                        self._config_one_host_addr(n2, path, a2)

    def _config_conns_9(self):
        for start, n1 in enumerate(self.resource.nodes):
            for n2 in self.resource.nodes[start + 1:]:
                self._config_one_connection(n1, n2)

    def config_host(self, node):
        with ConfigBlock(t='on %s' % node.host.hostname) as N:
            if self.host.drbd_version_tuple >= (9, 0, 0):
                N.write("node-id %d;" % node.id)
            else:
                # 8.4 compat
                N.write("address %s:%d;" % (node.host.addr, node.port))

            for index, disk in enumerate(node.disks):
                with ConfigBlock(t='volume %d' % index) as V:
                    V.write("device %s;" % disk.device())
                    V.write("disk %s;" % (disk.disk or "none"))
                    if disk.disk:
                        V.write("meta-disk %s;" % (disk.meta or "internal"))

    def config(self):
        text = []

        resource = self.resource
        with ConfigBlock(dest_fn=lambda x: text.append(x),
                         t="resource %s" % resource.name):

            with ConfigBlock(t='handlers') as handlers:
                handlers.write(resource._handlers)

            with ConfigBlock(t='options') as res_options:
                res_options.write(resource._resource_options)

            with ConfigBlock(t='disk') as disk:
                disk.write("disk-flushes no;")
                disk.write("md-flushes no;")
                if 'c-min-rate' not in resource._disk_options and self.host.os_id == 'ubuntu' and self.host.os_version_id == '18.04':
                    # Work around issue on Ubuntu Bionic.
                    # Application IO activity is detected when there is none, causing c-min-rate throttling to be applied.
                    disk.write("c-min-rate 0;")
                if self._fencing_mode and self.host.drbd_version_tuple < (9, 0, 0):
                    disk.write('fencing {};'.format(self._fencing_mode))
                disk.write(resource._disk_options)

            with ConfigBlock(t='net') as net:
                if resource.transport:
                    net.write('transport "{}";'.format(resource.transport))
                if resource.tls == 'yes':
                    net.write('tls {};'.format(resource.tls))
                if self._fencing_mode and self.host.drbd_version_tuple >= (9, 0, 0):
                    net.write('fencing {};'.format(self._fencing_mode))
                net.write(resource._net_options)

            # NOTE: (wap) W/ drbd9/LINSTOR, separate proxy stanza not needed
            #       for proxy but only for proxy options like compressions
            with ConfigBlock(t='proxy') as proxy:
                if proxy_enable:
                    if lz4_enable:
                        with ConfigBlock(t='plugin') as proxy_plugin:
                            proxy_plugin.write("lz4;")
                    elif zstd_enable:
                        with ConfigBlock(t='plugin') as proxy_plugin:
                            proxy_plugin.write("zstd levels %d;" % zstd_enable)

                    try:
                        if memlimit:
                            proxy.write("memlimit %d;" % memlimit)
                    except:
                        pass

            for n in resource.nodes:
                self.config_host(n)

            if self.host.drbd_version_tuple >= (9, 0, 0):
                self._config_conns_9()
            else:
                self._config_conns_84()


        return "".join(text)

    def drbd_config_file_path(self):
        return '{}/{}-{}.res'.format(drbd_config_dir, self.resource.cluster.job, self.resource.name)

    def update_config(self):
        """ Create or update the configuration file on the node when needed. """

        if self.config_changed:
            self.config_changed = False
            config = self.config()
            file = open(os.path.join(self.resource.cluster.logdir,
                                     'drbd.conf-{}-{}'.format(self.resource.name.replace('/', '_'), self.name)), 'w')
            file.write(config)
            file.close
            self.run(['bash', '-c', 'cat > ' + self.drbd_config_file_path()],
                    stdin=StringIO(config), update_config=False)

    def config_proxy(self):
        """ Update DRBD proxy options in the configuration file. """
        # TODO: (wap) Implement adding proxy options
        pass

    def run(self, *args, update_config=True, **kwargs):
        """
        Run a command via SSH on the target node. Arguments are passed to Host.run.

        :param update_config: whether or not to update the DRBD config file before running
        """
        if update_config:
            self.update_config()

        return self.host.run(*args, **kwargs)

    def fio_file(self, *args, **kwargs):
        self.host.fio_file(*args, **kwargs)

    def drbdadm(self, cmd, **kwargs):
        self.run(['drbdadm', '-c', self.host.drbd_global_config_file_path(), '-v'] + cmd, **kwargs)

    # dump the drbd metadata to a file on the target node
    def dump_md_to_file(self, filename):
        self.run(['/bin/bash', '-c',
            'drbdadm -c {} dump-md {} > {}'.format(
                self.host.drbd_global_config_file_path(), self.resource.name, filename
            )])

    def get_volumes(self):
        return Volumes(self.disks)
    volumes = property(get_volumes)

    def get_peer_devices(self):
        peer_devices = PeerDevices()
        for connection in self.connections:
            for volume in self.disks:
                peer_devices.add(PeerDevice(connection, volume))
        return peer_devices
    peer_devices = property(get_peer_devices)

    def adjust(self):
        self.update_config()
        self.drbdadm(['adjust', self.resource.name])

    def up(self, extra_options=[]):
        Nodes([self]).up(extra_options)

    def up_wait(self, extra_options=[]):
        # A single node doesn't know who to wait for...
        return self.up(extra_options)

    def down(self):
        Nodes([self]).down()

    def attach(self):
        self.volumes.attach()

    def detach(self):
        self.volumes.detach()

    def new_resource(self):
        Nodes([self]).new_resource()

    def new_minor(self):
        Nodes([self]).new_minor()

    def new_peer(self):
        Nodes([self]).new_peer()

    def resource_options(self, *args):
        Nodes([self]).resource_options(*args)

    def peer_device_options(self):
        Nodes([self]).peer_device_options()

    def new_path(self):
        Nodes([self]).new_path()

    def up_unconnected(self):
        Nodes([self]).up_unconnected()

    def event(self, *args, **kwargs):
        return Nodes([self]).event(*args, **kwargs)

    def asPrimary(self, **kwargs):
        return AsPrimary(self, **kwargs)

    def primary(self, force=False, wait=True):
        if force:
            self.drbdadm(['primary', '--force', self.resource.name])
            ev = []
            if self.volumes.diskful:
                ev.append(r'device .* disk:UpToDate')
            if wait:
                ev.append(r'resource .* role:Primary')
            self.event(*ev)
        else:
            self.drbdadm(['primary', self.resource.name])
            if wait:
                self.event(r'resource .* role:Primary')

    def secondary(self, wait=True, force=False):
        self.drbdadm(['secondary', self.resource.name] + (['--force'] if force else []))
        if wait:
            self.event(r'resource .* role:Secondary')

    def set_gi(self, peer_volume, current_uuid=None, bitmap_uuid=None,
            history_uuid_0=None, history_uuid_1=None,
            flags_set=[], flags_unset=[]):
        """
        Run set-gi on the given volume. This should be a volume from a peer if
        any of the peer related values are touched, but may be a local volume
        otherwise.
        """
        local_volume = self.volumes[peer_volume.volume]

        def empty_if_none(arg):
            return '' if arg is None else str(arg)

        def flag_val(flag):
            return '1' if flag in flags_set else '0' if flag in flags_unset else ''

        values = [empty_if_none(current_uuid),
                empty_if_none(bitmap_uuid),
                empty_if_none(history_uuid_0),
                empty_if_none(history_uuid_1),
                flag_val(MetadataFlag.CONSISTENT),
                flag_val(MetadataFlag.WAS_UP_TO_DATE),
                flag_val(MetadataFlag.PRIMARY_IND),
                flag_val(MetadataFlag.CRASHED_PRIMARY),
                flag_val(MetadataFlag.AL_CLEAN),
                flag_val(MetadataFlag.AL_DISABLED),
                flag_val(MetadataFlag.PRIMARY_LOST_QUORUM),
                flag_val(MetadataFlag.PEER_CONNECTED),
                flag_val(MetadataFlag.PEER_OUTDATED),
                flag_val(MetadataFlag.PEER_FENCING),
                flag_val(MetadataFlag.PEER_FULL_SYNC),
                flag_val(MetadataFlag.PEER_DEVICE_SEEN)]

        # Call drbdmeta directly instead of drbdadm because drbdadm doesn't
        # allow peer_volume to be a local volume.
        self.run(['drbdmeta', str(local_volume.minor), 'v09', local_volume.disk, 'internal',
            '--node-id={}'.format(peer_volume.node.id), '--force',
            'set-gi', ':'.join(values)])

    def connect(self, node):
        return Connections([Connection(self, node)]).connect()

    def disconnect(self, node, wait=True):
        return Connections([Connection(self, node)]).disconnect(wait=wait)

    def write(self, **kwargs):
        """ Write some data to each of the volumes on this node using fio. """
        for v in self.volumes:
            self.fio_file(v.device(), fio_write_small_args, **kwargs)

    def fio(self, *args, **kwargs):
        """ Run fio on each of the volumes on this node. """
        for v in self.volumes:
            self.fio_file(v.device(), *args, **kwargs)

    @staticmethod
    def _iptables_cmd_1(chain, sa, sp, da, dp, jump, add_remove, udp_tcp, additional_filter=[]):
        r = ['iptables',
             add_remove, chain,
             '-p', udp_tcp,
             "--source", sa,
             "--destination", da]
        if sp:
            r.extend(("--source-port", str(sp)))
        if dp:
            r.extend(("--destination-port", str(dp)))
        r.extend(("-j", jump))
        return r + additional_filter

    def _iptables_cmd(self, node2, jump, path_nr, add_remove, additional_filter=[]):
        """Returns an array of arrays (for .run) to filter the given path."""
        r = []
        rdma = self.resource.transport == 'rdma'
        if rdma:
            r.append(Node._iptables_cmd_1('drbd-test-output',  self.host.addrs[path_nr], None, node2.host.addrs[path_nr], 4791, jump, add_remove, 'udp'))
            r.append(Node._iptables_cmd_1('drbd-test-input',  node2.host.addrs[path_nr], None,  self.host.addrs[path_nr], 4791, jump, add_remove, 'udp'))
            return r

        r.append(Node._iptables_cmd_1('drbd-test-output',  self.host.addrs[path_nr],  self.port, node2.host.addrs[path_nr],       None, jump, add_remove, 'tcp'))
        r.append(Node._iptables_cmd_1('drbd-test-output',  self.host.addrs[path_nr],       None, node2.host.addrs[path_nr], node2.port, jump, add_remove, 'tcp'))
        r.append(Node._iptables_cmd_1('drbd-test-input',  node2.host.addrs[path_nr],       None,  self.host.addrs[path_nr],  self.port, jump, add_remove, 'tcp'))
        r.append(Node._iptables_cmd_1('drbd-test-input',  node2.host.addrs[path_nr], node2.port,  self.host.addrs[path_nr],       None, jump, add_remove, 'tcp'))
        return r

    def block_path(self, other_node, net_number=0, jump_to="DROP", iptables_filter=[]):
        """Uses iptables to block one network path."""
        log("BLOCKING path #%d from %s to %s" % (net_number, self, other_node))
        cmds = self._iptables_cmd(other_node, jump_to, net_number, "-I", iptables_filter)
        for c in cmds:
            self.run(c)

    def unblock_path(self, other_node, net_number=0, jump_to="DROP"):
        """Uses iptables to unblock one network path."""
        log("Unblocking path #%d from %s to %s" % (net_number, self, other_node))
        cmds = self._iptables_cmd(other_node, jump_to, net_number, "-D")
        for c in cmds:
            self.run(c)

    def _block_packet_type(self, packet, op, from_node, volume):
        cmdline = ['iptables', op, 'drbd-test-input', '-p']
        cmdline.append('udp' if self.resource.transport == 'rdma' else 'tcp')
        if from_node is not None:
            cmdline += ['-s', from_node.host.addrs[0]]
        cmdline += [ '-m', 'string', '--algo', 'bm', '--from', '0',
                     '--hex-string', '|8620ec20 %04X %04X 0000|' % (volume, packet)]
        for ipt_target in ['LOG', 'DROP']:
            self.run(cmdline + ['-j', ipt_target])

    def block_packet_type(self, packet, from_node=None, volume=0):
        """
        Block a specific DRBD packet from being received on this node.

        Warning: The packet will be blocked for all resources.
        """
        self._block_packet_type(packet, '-A', from_node, volume)

    def unblock_packet_type(self, packet, from_node=None, volume=0):
        self._block_packet_type(packet, '-D', from_node, volume)

    def set_fault_injection(self, volume, faults):
        self.host.run_helper('enable-faults',
                ['--faults=%d' % (faults),
                    '--rate=100',
                    '--devs=%d' % (1 << volume.minor)])

    def disable_fault_injection(self, volume):
        self.host.run_helper('disable-faults', ['--devs=%d' % (1 << volume.minor)])

    def twopc_tid(self):
        text = self.run(['cat',
                         '/sys/kernel/debug/drbd/resources/{}/state_twopc'.format(self.resource.name)],
                        return_stdout=True)
        match = state_twopc_regex.search(text)
        if match:
            return int(match.group(1))

        return None

    def volume_by_vnr(self, vol_nr):
        return next(v for v in self.resource.volumes_by_vnr(vol_nr) if v.node == self)

    def peer_devices_by_vnr(self, vol_nr):
        return PeerDevices([pd for pd in self.resource.peer_devices_by_vnr(vol_nr) if pd.volume.node == self])

def skip_test(text):
    print(text, file=sys.stderr)
    sys.exit(100)


def setup_resource(*args, **kwargs):
    """
    Test setup.  Returns a resource object.

    The arguments are the same as those to setup().
    """

    cluster = setup(*args, **kwargs)
    return cluster.create_resource()


def setup(nodes=None, max_nodes=None, min_nodes=2, multi_paths=False, netns=None):
    """
    Test setup.  Returns a cluster object.

    Keyword arguments:
      nodes, min_nodes, max_nodes
                -- exact, minimum, and maximum number of test nodes required
      multi_paths
                -- set up addresses for multi-path testing
      netns     -- set up network namespaces
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('host', nargs='*')
    parser.add_argument('--job')
    parser.add_argument('--resource')
    parser.add_argument('--logdir')
    parser.add_argument('--cleanup', default='success',
                        choices=('success', 'always', 'never'))
    parser.add_argument('--volume-group', default='scratch')
    parser.add_argument('--vconsole', action='store_true')
    parser.add_argument('--silent', action='store_true')
    parser.add_argument('-d', action='count', dest='debug')
    parser.add_argument('--debug', type=int)
    parser.add_argument('--transport', choices=('tcp', 'lb-tcp', 'rdma'))
    parser.add_argument('--tls', default='no', choices=('yes', 'no'))
    parser.add_argument('--override-max', action="store_true")
    parser.add_argument('--report-and-quit', action="store_true")
    parser.add_argument('--no-rmmod', action="store_true")
    parser.add_argument('--proxy', action="store_true")
    parser.add_argument('--lz4', action="store_true")
    parser.add_argument('--zstd', type=int)
    parser.add_argument('--memlimit', type=int)
    parser.add_argument('--storage-backend', default='lvm', choices=('lvm', 'raw', 'zfs'))
    parser.add_argument('--backing-device', type=str)
    parser.add_argument('--drbd-version', help='validate that this DRBD version is installed')
    parser.add_argument('--drbd-version-other')
    parser.add_argument('--drbd-other-node', type=int, default=0, help='index of node to install "other" version on')
    args = parser.parse_args()

    if nodes is not None:
        min_nodes = max_nodes = nodes

    if args.report_and_quit:
        print("min_nodes=%d" % min_nodes)
        if max_nodes:
            print("max_nodes=%d" % max_nodes)
        sys.exit(0)

    if max_nodes is not None and min_nodes == max_nodes and \
       len(args.host) != min_nodes:
        skip_test('Test case requires %s nodes' % min_nodes)
    if len(args.host) < min_nodes:
        skip_test('Test case requires %s or more nodes' % min_nodes)
    if max_nodes is not None and len(args.host) > max_nodes and not args.override_max:
        skip_test('Test case requires %s or fewer nodes; user --override-max if really meant.' % max_nodes)

    global silent
    silent = args.silent

    global debug_level
    if args.debug is not None:
        debug_level = args.debug

    if args.job is None:
        args.job = re.sub(r'.*/(.*?)(?:\.py)?$', r'\1', sys.argv[0]) + \
            '-' + time.strftime('%Y%m%d-%H%M%S')
    if args.resource is None:
        args.resource = args.job
    job_symlink = None
    if args.logdir is None:
        args.logdir = os.path.join('log', args.job)
        job_symlink = re.sub(r'-[^-]*-[^-]*?$', '', args.job) + '-latest'

    global no_rmmod
    no_rmmod = args.no_rmmod

    os.environ['LOGSCAN_TIMEOUT'] = '30'

    if not silent:
        print('Logging to directory %s' % args.logdir, file=sys.stderr)

    if not os.access(args.logdir, os.R_OK + os.X_OK + os.W_OK):
        os.makedirs(args.logdir)
    if job_symlink is not None:
        try:
            os.remove(os.path.join('log', job_symlink))
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise e
        os.symlink(args.job, os.path.join('log', job_symlink))

    logfile = open(os.path.join(args.logdir, 'test.log'), 'w', encoding='utf-8')
    # no need to close logfile - it is kept open until the program terminates
    global logstream
    logstream = Tee()
    logstream.add(sys.stderr)
    logstream.add(logfile)

    global proxy_enable
    proxy_enable = args.proxy

    global lz4_enable
    lz4_enable = args.lz4

    global zstd_enable
    if args.zstd:
        if args.zstd > 0 and args.zstd <= 22:
            zstd_enable = args.zstd
        else:
            zstd_enable = 3
    else:
        zstd_enable = 0

    if args.memlimit:
        global memlimit
        memlimit = args.memlimit

    Cleanup(args.cleanup)

    if args.vconsole:
        for host in args.host:
            logfile = 'console-%s' % host

            # Check if a virtual machine called "$host" exists -- otherwise we
            # would loop forever below.
            subprocess.check_call(['virsh', 'domid', host], stdout=devnull)
            subprocess.check_call(['screen', '-S', logfile, '-d',
                                   '-m', 'virsh', 'console', host])

            # Wait until screen has started up and is ready
            while True:
                try:
                    subprocess.check_call(['screen', '-S', logfile,
                                           '-p', '0', '-X', 'version'],
                                          stdout=devnull)
                    break
                except:
                    time.sleep(0.1)

            subprocess.check_call(['screen', '-S', logfile, '-p',
                                   '0', '-X', 'logfile',
                                   os.path.join(args.logdir,
                                                'console-%s.log' % host)])
            subprocess.check_call(['screen', '-S', logfile, '-p',
                                   '0', '-X', 'log', 'on'])
            log("%s: capturing console" % host, level=2)

            def close_logfile(logfile):
                def func():
                    subprocess.check_call(['screen', '-S', logfile,
                                           '-p', '0', '-X', 'stuff', '\035'])
                return func
            atexit.register(close_logfile(logfile))

    cluster = Cluster(
            job=args.job,
            logdir=args.logdir,
            drbd_version=args.drbd_version,
            drbd_version_other=args.drbd_version_other,
            resource_name=args.resource,
            transport=args.transport,
            tls=args.tls)

    for i, host_name in enumerate(args.host):
        host = Host(cluster, host_name,
            args.volume_group, args.storage_backend, args.backing_device,
            multi_paths=multi_paths, netns=netns)

        cluster.hosts.append(host)

        if args.drbd_version_other and i == args.drbd_other_node:
            # Automatically install other version
            host.install_drbd(args.drbd_version_other)
            host.has_other_version = True

    if args.tls == 'yes':
        tls.setup_kernel_tls_helper(cluster.hosts)

    cluster.validate_drbd_versions()

    drbd_versions_meta_path = os.path.join(args.logdir, 'drbd-versions.json')
    with open(drbd_versions_meta_path, 'w') as f:
        cluster.write_drbd_versions_meta(f)

    cluster.listen_to_events()

    for host in cluster.hosts:
        host.run_helper('disable-faults')

    return cluster


def connections(from_node=None, to_node=None, *, from_nodes=None, to_nodes=None, bidir=False):
    """
    Construct a Connections object using all combinations of the given from and
    to nodes. The from nodes can be specified as a single node with from_node,
    as multiple nodes with from_nodes, or as all nodes by omitting both
    parameters. Similarly, the to nodes can be specified using to_node or
    to_nodes. At least one from or to node parameter must be set.

    :param from_node: Node object from which the connections originate.
    :param to_node: Node object to which the connections terminate.
    :param from_nodes: Iterable of Node objects from which the connections originate.
    :param to_nodes: Iterable of Node objects to which the connections terminate.
    :param bidir: If True, also include the reversed connections.
    """
    if from_node and from_nodes:
        raise RuntimeError('both from_node and from_nodes specified')

    if from_node:
        from_nodes = [from_node]

    if to_node and to_nodes:
        raise RuntimeError('both to_node and to_nodes specified')

    if to_node:
        to_nodes = [to_node]

    # Compare with None rather than checking "truthy" status. The parameters
    # from_nodes and to_nodes may be empty collections.
    if from_nodes is None and to_nodes is None:
        raise RuntimeError('neither from nor to specified')

    if from_nodes is None:
        from_nodes = to_nodes[0].resource.nodes if to_nodes else []

    if to_nodes is None:
        to_nodes = from_nodes[0].resource.nodes if from_nodes else []

    cs = Connections()

    for from_n in from_nodes:
        for to_n in to_nodes:
            if from_n != to_n:
                cs.add(Connection(from_n, to_n))

    if bidir:
        cs.extend([Connection(c.nodes[1], c.nodes[0]) for c in cs])

    return cs


def peer_devices(*args, **kwargs):
    cs = connections(*args, **kwargs)
    return PeerDevices.from_connections(cs)


# is assert(), but with non-conflicting name
def ensure(want, have, explanation=None):
    if want != have:
        log("Wanted '%s', but got '%s'.\n" % (repr(want), repr(have)))
        if explanation:
            log("%s\n" % explanation)
        raise RuntimeError('assert trigger')
