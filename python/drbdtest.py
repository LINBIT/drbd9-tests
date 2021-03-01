# setup parameters: console

# FIXME: Why are the prefixes missing from output of the target cleanup scripts?

# FIXME: class Collection: Switch to an ordered set?  Right now, the order in
# which nodes are given on the command line is not preserved.

# FIXME: Check for synchronized time on the test nodes.

# FIXME: How to add a diskless volume on a node?

# FIXME: For test cases with multiple resources, we only need to capture the
# consoles, syslogs, and event logs once. We need to prefix the .pos file names
# and the log messages with the resource name.

import os
import errno
import sys
import re
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
import exxe

from .syslogd import syslog_server
from io import StringIO

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

DRBD_TEST_DATA = os.getenv('DRBD_TEST_DATA', '/usr/share/drbd-test')

fio_write_args = {
        'bs': '4K',
        'ioengine': 'sync',
        'verify': 'md5',
        'do_verify': 0,
        'rw': 'write'}

fio_verify_args = {
        'bs': '4K',
        'ioengine': 'sync',
        'verify': 'md5',
        'verify_only': 1,
        'rw': 'read'}

fio_write_small_args = {
        **fio_write_args,
        'size': '4K',
        'randrepeat': 0}

silent = False
debug_level = 0
skip_cleanup = False

devnull = open(os.devnull, 'w')

# stream to write output to
logstream = None


class Tee(object):
    """
    replicates writes to streams
    """

    def __init__(self, streams):
        self.streams = streams

    def write(self, message):
        for stream in self.streams:
            stream.write(message)

    def flush(self):
        for stream in self.streams:
            stream.flush()


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

    def __str__(self):
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

    def event(self, *args, **kwargs):
        """ Wait for an event. """

        if self.members:
            where = \
                [_ for node in self.members
                 for _ in ['events-%s' % node.name,
                           '--label', node.name,
                           '-p', '.events.pos']
                 ]
            return self.resource().logscan(self, where, *args, **kwargs)
        return None

    def run(self, *args, **kwargs):
        """ Run command on all our nodes. """

        if not kwargs.pop('prepare', False):
            self.update_config()
        # by default send all output to the log
        if not 'stdout' in kwargs:
            kwargs['stdout'] = logstream
        if not 'stderr' in kwargs:
            kwargs['stderr'] = logstream
        log(' '.join([node.name for node in self]) + ': ' +
                ' '.join(pipes.quote(str(x)) for x in args[0]))
        exxe.run(self, *args, **kwargs)

    def up(self, extra_options=[]):
        # the order of disk/connection setup isn't strictly defined.
        # make sure that a defined order is seen, so that event matching works.
        self.run(['drbdadm', 'up', 'all', '-v'] + extra_options)

        # doesn't work either.
        #   + drbdmeta 1 v08 /dev/scratch/compat-with-84.new-20150504-103023-disk0 internal apply-al
        #   Device '1' is configured!
        #   + drbdsetup-84 attach 1 /dev/scratch/compat-with-84.new-20150504-103023-disk0 /dev/scratch/compat-with-84.new-20150504-103023-disk0 internal
        #   1: Failure: (124) Device is attached to a disk (use detach first)
        #self.run(['bash', '-c', 'drbdadm up all -v | grep -v " connect " | PATH=/lib/drbd:$PATH bash -x'])
        #self.volumes.diskful.event(r'device .* disk:Inconsistent')
        #self.run(['bash', '-c', 'drbdadm up all -v | grep    " connect " | PATH=/lib/drbd:$PATH bash -x'])
        self.after_up()

        if proxy_enable:
            self.run(['drbdadm', 'proxy-up', 'all', '-v'] + extra_options)

    def down(self):
        if proxy_enable:
            self.run(['drbdadm', 'proxy-down', 'all', '-v'])

        self.resource().forbidden_patterns.difference_update([
            r'connection:BrokenPipe',
            r'connection:NetworkFailure'
        ])
        self.run(['drbdadm', 'down', 'all'])
        self.after_down()
        self.event(r'destroy resource')

    def attach(self):
        self.run(['drbdadm', 'attach', 'all', '-v'])
        self.volumes.diskful.event(r'device .* disk:Attaching')

    def detach(self):
        self.run(['drbdadm', 'detach', 'all', '-v'])
        self.volumes.diskful.event(r'device .* disk:Detaching')
        self.volumes.diskful.event(r'device .* disk:Diskless')

    def new_resource(self):
        self.run(['drbdadm', 'new-resource', 'all', '-v'])
        self.event(r'create resource')

    def new_minor(self):
        self.run(['drbdadm', 'new-minor', 'all', '-v'])
        self.volumes.event(r'create device')

    def new_peer(self):
        self.run(['drbdadm', 'new-peer', 'all', '-v'])
        self.volumes.peer_devices.event(r'create peer-device')

    def resource_options(self, opts=[]):
        self.run(['drbdadm', 'resource-options', 'all', '-v'] + opts)

    def peer_device_options(self, opts=[]):
        self.run(['drbdadm', 'peer-device-options', 'all', '-v'] + opts)

    def new_path(self):
        self.run(['drbdadm', 'new-path', 'all', '-v'])
        self.connections.event(r'create path')

    def bidir_connections_to_node(self, new_node):
        cs = Connections()
        for n in self.members:
            cs.bidir_add(new_node, n)
        return cs

    def connections_to_node(self, new_node):
        cs = Connections()
        for n in self.members:
            cs.add(Connection(n, new_node))
        return cs

    def connections_from_node(self, new_node):
        cs = Connections()
        for n in self.members:
            cs.add(Connection(new_node, n))
        return cs

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
            where = \
                [__ for node, volume in
                 [(_.node, _.volume) for _ in self.members]
                 for __ in ['events-%s' % node.name,
                            '--label', '%s:%s' % (node.name, volume),
                            '-p', '.events-volume-%s.pos' % volume,
                            '-f', 'volume:%s' % volume]
                 ]
            resource = first(self.members).resource
            return resource.logscan(self, where, *args, **kwargs)

        return None

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


class Connections(Collection):
    def __init__(self, members=[]):
        super(Connections, self).__init__(Connection, members)

    def event(self, *args, **kwargs):
        """ Wait for an event. """

        results = []
        if self.members:
            where = \
                [__ for n0, n1 in
                 [(_[0], _[1]) for _ in self.members]
                 for __ in ['events-%s' % n0.name,
                            '--label', '%s:%s' % (n0.name, n1.name),
                            '-p', '.events-connection-%s.pos' % n1.name,
                            '-f', 'peer-node-id:%d' % n1.id]
                 ]
            resource = first(self.members).resource
            results = resource.logscan(self, where, *args, **kwargs)
        return results

    def from_node(self, node):
        return self.from_nodes([node])

    def from_nodes(self, nodes):
        return Connections([_ for _ in self if _.nodes[0] in nodes])

    def to_node(self, node):
        return self.to_nodes([node])

    def to_nodes(self, nodes):
        return Connections([_ for _ in self if _.nodes[1] in nodes])

    def run_drbdadm(self, cmd, state_str, wait=True, options=[]):
        for connection in self:
            node0, node1 = connection.nodes
            node0.run(['drbdadm', cmd] + options +
                      ['%s:%s' % (connection.resource.name, node1.hostname)])
        if wait:
            self.event(r'connection .* connection:%s' % (state_str))

    def connect(self, wait=True, options=[]):
        self.run_drbdadm('connect', 'Connecting', wait, options)
        for connection in self:
            node0 = connection.nodes[0]
            node0.connections.add(connection)

    def disconnect(self, wait=True, force=False):
        self.run_drbdadm('disconnect', 'StandAlone', wait, ['--force'] if force else [])
        for connection in self:
            node0, node1 = connection.nodes
            node0.connections.remove(connection)

    def verify(self, options=[]):
        self.run_drbdadm('verify', None, false, options)

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
            where = \
                [__ for n0, n1, volume in
                 [(_.connection[0], _.connection[1], _.volume.volume)
                  for _ in self.members]
                 for __ in ['events-%s' % n0.name,
                            '--label', '%s:%s:%s' % (n0.name, n1.name, volume),
                            '-p', '.events-peer-device-%s:%s.pos' % (n1.name, volume),
                            '-f', 'peer-node-id:%d' % n1.id,
                            '-f', 'volume:%s' % volume]
                 ]
            resource = first(self.members).resource
            return resource.logscan(self, where, *args, **kwargs)

    def peer_device_options(self, opts=[]):
        for pd in self:
            node0, node1 = pd.connection.nodes
            cmdline = ['drbdadm', 'peer-device-options', '%s:%s' %
                       (pd.connection.resource.name, node1.hostname),
                       opts]

            node0.run(cmdline)
    def from_node(self, node):
        return self.from_nodes([node])

    def from_nodes(self, nodes):
        return PeerDevices([_ for _ in self if _.connection.nodes[0] in nodes])

    def to_node(self, node):
        return self.to_nodes([node])

    def to_nodes(self, nodes):
        return PeerDevices([_ for _ in self if _.connection.nodes[1] in nodes])

    def verify(self, wait=True, options=[]):
        for pd in self:
            node0, node1 = pd.connection.nodes
            res = pd.connection.resource.name
            node0.run(['drbdadm', 'verify'] + options +
                      ['%s:%s/%d' % (res, node1.hostname, pd.volume.volume)])
        if wait:
            self.event(r'peer-device .* replication:VerifyS')

# Now that all collection classes are defined, define inter-class dependencies:
Nodes.finish()
Volumes.finish()


class Resource(object):
    def __init__(self, name, logdir, rdma=False):
        self.name = name
        self.net_options = ""
        self.disk_options = ""
        self.resource_options = ""
        # NOTE: (wap) Not needed for now
        # self.proxy_options = ""
        self.handlers = ""
        self.nodes = Nodes()
        self.num_volumes = 0
        self.logdir = logdir
        self.rdma = rdma
        self.events_cls = None
        self.forbidden_patterns = OrderedSet()
        self.add_new_posfile('.events.pos')
        atexit.register(self.cleanup)

    def __str__(self):
        return self.name

    def next_volume(self):
        volume = self.num_volumes
        self.posfiles_add_volume(volume)
        self.num_volumes += 1
        return volume

    def add_disk(self, size, meta_size=None, diskful_nodes=None, thin=False,
                 max_peers=None):
        """
        Create and add a new disk on some or all nodes.

        Keyword arguments:
        size            -- size of the data device
        meta_size       -- size of the meta-data device,
                           or "None" for internal meta-data
        diskful_nodes   -- nodes which shall have a local lower-level device
                           (defaults to all nodes)
        """
        volume = self.next_volume()
        for node in self.nodes:
            if diskful_nodes is None or node in diskful_nodes:
                node.add_disk(volume, size, meta_size, thin=thin,
                              max_peers=max_peers)
            else:
                node.add_disk(volume)

    volumes = property(lambda self: self.nodes.volumes)
    connections = property(lambda self: self.nodes.connections)
    peer_devices = property(lambda self: self.nodes.peer_devices)

    def peer_devices_to_peer(self, peer):
        pds = self.peer_devices
        for pd in pds:
            log("** %s to %s" % pd.connection.nodes)
        return PeerDevices([pd for pd in pds if peer == pd.connection.nodes[1]])

    def cleanup(self):
        if not skip_cleanup:
            self.nodes.run(['cleanup'], prepare=True, catch=True)
        for node in self.nodes:
            node.cleanup()

    def rmmod(self):
        if no_rmmod:
            return
        for n in self.nodes:
            if n.drbd_version_tuple >= (9, 0, 0):
                # might not even be loaded
                try:
                    n.run(['rmmod', 'drbd_transport_tcp'])
                except:
                    pass

        try:
            self.nodes.run(['rmmod', 'drbd'])
        except:
            pass

    def logscan(self, collection, where, *args, **kwargs):
        """ Run logscan to scan / wait for events to occur. """
        if args is None:
            args = []
        no = kwargs.get('no', [])
        if isinstance(no, str):
            no = [no]

        self.sync_events(collection.__class__)

        log('Waiting for event ' + ' '.join(
            [str(_) for _ in collection] +
            ['-y ' + _ for _ in args] +
            ['-n ' + _ for _ in no]))

        cmd = ['logscan', '-d', os.environ['DRBD_LOG_DIR']]
        if not 'word_boundary' in kwargs or kwargs['word_boundary']:
            cmd.append('-w')
        if silent:
            cmd.append('--silent')
        cmd.append('--verbose')
        if 'timeout' in kwargs:
            cmd.extend(['--timeout', str(kwargs['timeout'])])
        for expr in self.forbidden_patterns:
            cmd.extend(['-N', expr])
        for expr in args:
            cmd.extend(['-y', expr])
        for expr in no:
            cmd.extend(['-n', expr])
        debug('# ' + ' '.join(pipes.quote(_) for _ in cmd + where))

        result_bytes = subprocess.check_output(cmd + where, stderr=subprocess.STDOUT)
        result = result_bytes.decode(encoding='utf-8', errors='backslashreplace')
        log(result)

        lines = result.split("\n")
        match_results = []
        for l in lines:
            g = re.match('^Pattern .*? matches .*?; (\[.*)', l)
            if g:
                match_results.append([g for g in json.loads(str(g.group(1))) if g != ' '])

        return match_results

    def posfiles(self, nodes=None):
        """ List of all logscan position tracking files. """

        if nodes is None:
            nodes = self.nodes
        return \
            ['.events.pos'] + \
            ['.events-volume-%s.pos' % volume
             for volume in range(self.num_volumes)] + \
            ['.events-connection-%s.pos' % node.name
             for node in nodes] + \
            ['.events-peer-device-%s:%s.pos' % (node.name, volume)
             for node in nodes
             for volume in range(self.num_volumes)]

    def add_new_posfile(self, posfile):
        data = ''.join(['1 0 events-%s\n' % node.name for node in self.nodes])
        fd = os.open(os.path.join(os.environ['DRBD_LOG_DIR'], posfile),
                     os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        os.write(fd, data.encode())
        os.close(fd)

    def append_to_posfile(self, posfile, node):
        data = '1 0 events-%s\n' % node.name
        pathname = os.path.join(os.environ['DRBD_LOG_DIR'], posfile)
        fd = os.open(pathname, os.O_WRONLY | os.O_APPEND)
        os.write(fd, data.encode())
        os.close(fd)

    def posfiles_add_node(self, node):
        nodes = [x for x in self.nodes if x is not node]
        for posfile in self.posfiles(nodes=nodes):
            self.append_to_posfile(posfile, node)
        self.add_new_posfile('.events-connection-%s.pos' % node.name)
        for volume in range(self.num_volumes):
            self.add_new_posfile('.events-peer-device-%s:%s.pos' %
                                 (node.name, volume))

    def posfiles_add_volume(self, volume):
        self.add_new_posfile('.events-volume-%s.pos' % volume)
        for node in self.nodes:
            self.add_new_posfile('.events-peer-device-%s:%s.pos' %
                                 (node.name, volume))

    def sync_events(self, events_cls):
        """ Synchronize logcan position tracking files. """
        if self.events_cls is not events_cls:
            self.events_cls = events_cls
            cmd = ['logscan', '-d', os.environ['DRBD_LOG_DIR'], '--sync'] + \
                self.posfiles()
            debug('# ' + ' '.join(pipes.quote(_) for _ in cmd))
            subprocess.check_call(cmd)

    def up(self, extra_options=[]):
        self.nodes.up(extra_options)
        # Because of "initial packet S crossed" an initial NetworkFailure and/or BrokenPipe is allowed.
        # Wait for the connections to be established.
        self.forbidden_patterns.update([
            r'connection:Timeout',
            r'connection:ProtocolError',
            r'disk:Failed',
            r'peer-disk:Failed'])

    def skip_initial_sync(self):
        node = self.nodes.diskful[0]
        # set to remove duplicates ?!!
        res_vols = set(["%s/%d" % (self.name, v.volume) for v in self.volumes if v.disk])
        node.run(["drbdadm", "new-current-uuid", "--clear-bitmap"] + list(res_vols))
        # wait for completion
        self.initial_resync(node)

    def up_wait(self, extra_options=[]):
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
        pds.event(r'peer-device .* peer-disk:(Inconsistent|Diskless)', timeout=30)

        self.sync_events(self)

        # Now add that, too.
        self.forbidden_patterns.update([
            r'connection:BrokenPipe',
            r'connection:NetworkFailure'])

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

    def initial_resync(self, sync_from):
        self.nodes.run(['drbdadm', 'peer-device-options', '--c-min-rate', '0', 'all', '-v'])
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
        pds.event(r'peer-device .* peer-disk:UpToDate', timeout=300)

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
        self.name = new_name
        self.touch_config()

class Volume(object):
    def __init__(self, node, volume, size=None, meta_size=None, minor=None,
                 max_peers=None, thin=False):
        if volume is None:
            volume = node.resource.next_volume()
        if minor is None:
            minor = node.next_minor()
        self.volume = volume
        self.minor = minor
        self.node = node
        if max_peers is None:
            max_peers = len(node.resource.nodes) - 1
            if max_peers < 1:
                max_peers = 1
        self.disk = None
        self.meta = None
        self.disk_lv = None
        self.meta_lv = None
        if size:
            self.disk_lv = '%s-disk%d' % (self.node.resource.name, volume)
            self.disk = self.create_disk(
                size, self.disk_lv,
                None if meta_size else '--internal-meta', max_peers,
                thin=thin)
            if meta_size:
                self.meta_lv = '%s-meta%d' % (self.node.resource.name, volume)
                self.meta = self.create_disk(
                    meta_size, self.meta_lv,
                    '--external-meta', max_peers,
                    thin=thin)

    def get_resource(self):
        return self.node.resource
    resource = property(get_resource)

    def get_peer_devices(self):
        peer_devices = PeerDevices()
        for connection in self.node.connections:
            peer_devices.add(PeerDevice(connection, self))
        return peer_devices
    peer_devices = property(get_peer_devices)

    def __str__(self):
        return '%s:%s' % (self.node, self.volume)

    def create_disk(self, size, name, meta, max_peers, thin=False):
        cmd = ['create-disk']
        if meta:
            cmd.extend([meta, '--max-peers', str(max_peers)])
        thin_arg = []
        if thin:
            thin_arg = ['--thinpool', 'drbdthinpool']

        cmd.extend(['--job', os.environ['DRBD_TEST_JOB'],
                   '--volume-group', self.node.volume_group, '--size', size]
                   + thin_arg + [name])
        return self.node.run(cmd, return_stdout=True, prepare=True)

    def event(self, *args, **kwargs):
        return Volumes([self]).event(*args, **kwargs)

    def resize(self, size):
        # TODO: metadata-resize?
        self.node.run(['lvresize', '-L', size,
                       "%s/%s" % (self.node.volume_group, self.disk_lv)])

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

class Connection(object):
    def __init__(self, node1, node2):
        assert node1.resource is node2.resource
        self.nodes = (node1, node2)

    def get_resource(self):
        return self.nodes[0].resource
    resource = property(get_resource)

    def __str__(self):
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
        self.nodes[0].run(['drbdadm', *args, '%s:%s' %
                           (self.resource.name, self.nodes[1].hostname)])

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

    def verify(self, *args, **kwargs):
        return Connections([self]).verify(*args, **kwargs)

class PeerDevice(object):
    def __init__(self, connection, volume):
        self.connection = connection
        self.volume = volume

    def get_resource(self):
        return self.connection.resource
    resource = property(get_resource)

    def __str__(self):
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

class AsPrimary(object):

    def __init__(self, node, res="all", force=False):
        self.node = node
        self.force = force
        self.res = res

    def __enter__(self):
        self.node.primary(res=self.res, force=self.force)

    def __exit__(self, *ignore_exception):
        # Let processes detach correctly... eg. fio causes
        #   State change failed: (-12) Device is held open by someone
        # unless /lib/udev/rules.d/{13,60_persistent_storage}*
        # are patched to exclude DRBD from blkid
        self.node.secondary(self.res)


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


class Node(exxe.Exxe):
    def __init__(self, resource, name, volume_group,
                 addr=None, port=7789, multi_paths=None):
        super(Node, self).__init__(['ssh', '-l',
                                    'root', name,
                                    'exxe', '--syslog'], prefix='%s: ' % name)
        self.resource = resource
        self.name = name
        try:
            self.addr = addr if addr else socket.gethostbyname(name)
        except:
            raise RuntimeError('Could not determine IP for host %s' % name)
        self.port = port
        self.disks = []  # by volume
        self.id = len(self.resource.nodes)
        self.fio_count = 0
        self.resource.nodes.add(self)
        self.resource.posfiles_add_node(self)
        self.minors = 0
        self.config_changed = True
        self.volume_group = volume_group
        self.connections = Connections()

        # FIXME: Move some of these calls into setup() to run them in parallel?
        try:
            self.run(['test', '-d', DRBD_TEST_DATA], prepare=True)
        except:
            raise RuntimeError('%s: Directory %s does not exist' %
                               (self.name, DRBD_TEST_DATA))

        self.run(['timeout', os.environ['EXXE_TIMEOUT']],
                 prepare=True)
        self.run(['export', 'PATH=%s:$PATH' % DRBD_TEST_DATA], quote=False,
                 prepare=True)
        self.run(['export', 'DRBD_TEST_DATA=%s' % DRBD_TEST_DATA,
                  'DRBD_TEST_JOB=%s' % os.environ['DRBD_TEST_JOB'],
                  'EXXE_IDENT=exxe/%s' % os.environ['DRBD_TEST_JOB']] + self._extra_environment(),
                 prepare=True)
        self.hostname = self.run(['hostname', '-f'], return_stdout=True,
                                 prepare=True)
        drbd_version = self.run(['drbd-version'], return_stdout=True,
                                prepare=True)
        m = re.match(r'([0-9]+)\.([0-9]+)\.([0-9]+)(.*)', drbd_version);
        self.drbd_version_tuple = (int(m.group(1)), int(m.group(2)), int(m.group(3)))

        self.addrs = [self.addr]
        if multi_paths:
            net_2 = self.run(['ip', '-oneline', 'a', 'show', 'label', '*:1'],
                             return_stdout=True)
            log("got further path %s", net_2)
            m = re.search(r'^\s*\d+:\s+\w+\s+inet\s+([\d\.]+)/\d+', net_2)
            if not m:
                raise RuntimeError("%s has no *:1", self)
            self.addrs.append(m.group(1))

        self.run(["bash", "-c", 'iptables -F drbd-test-input || iptables -N drbd-test-input'])
        self.run(["bash", "-c", 'iptables -F drbd-test-output || iptables -N drbd-test-output'])
        self.run(["iptables", "-I", "INPUT", "-j", "drbd-test-input"])
        self.run(["iptables", "-I", "OUTPUT", "-j", "drbd-test-output"])

        # Ensure that added nodes will be reflected in the DRBD configuration file.
        self.config_changed = True

    def _extra_environment(self):
        return ['DRBD_TEST_DRBDADM_OPTIONS=%s' %
                ("-c /var/lib/drbd-test/%s/drbd.conf" %
                 os.environ['DRBD_TEST_JOB'])]

    def addr_port(self, net_num=0):
        return '%s:%s' % (self.addrs[net_num], self.port)

    def cleanup(self):
        self.run(["iptables", "-D", "INPUT", "-j", "drbd-test-input"])
        self.run(["iptables", "-D", "OUTPUT", "-j", "drbd-test-output"])
        self.run(["bash", "-c", 'iptables -F drbd-test-input && iptables -X drbd-test-input || true'])
        self.run(["bash", "-c", 'iptables -F drbd-test-output && iptables -X drbd-test-output || true'])

        self.config_changed = False
        if hasattr(self, 'events'):
            self.events.terminate()

    def __str__(self):
        # return '%s:%s' % (self.resource, self.name)
        return self.name

    def next_minor(self):
        self.minors += 1
        return self.minors

    def add_disk(self, volume, size=None, meta_size=None, thin=False, max_peers=None):
        """
        Keyword arguments:
        volume -- volume number of the new disk
        size -- size of the data device or None for a diskless node
        meta_size -- size of the meta-data device
        """
        # FIXME: Volume is not added at the right index (by volume number)
        # here.  Does that matter?
        self.disks.append(Volume(self, volume, size, meta_size, thin=thin,
                                 max_peers=max_peers))
        self.config_changed = True

    def _config_conns_84(self):
        # no explicit connections for 8.4
        # done via "address" in "on <host>" section
        pass

    def _config_one_host_addr(self, node, block, i):
        block.write("host %s address %s:%d;" %
                    (node.name,
                     node.addrs[i],
                     node.port))

    def _config_one_connection(self, n1, n2):
        with ConfigBlock(t="connection"):
            port_inside = self.port
            port_outside = self.port

            if proxy_enable:
                with ConfigBlock(t='host %s address 127.0.0.1:%s via proxy on %s'
                        % (n1.name, n1.port, n1.name)) as N1:
                    N1.write("inside 127.0.0.2:%s;" % port_inside)
                    N1.write("outside ipv4 %s:%s;"% (n1.addrs[0], port_outside))
                with ConfigBlock(t='host %s address 127.0.0.1:%s via proxy on %s'
                        % (n2.name, n2.port, n2.name)) as N2:
                    N2.write("inside 127.0.0.2:%s;" % port_inside)
                    N2.write("outside ipv4 %s:%s;"% (n2.addrs[0], port_outside))
                with ConfigBlock(t='net') as NET_OPTS:
                    NET_OPTS.write("protocol A;")
            else:
                with ConfigBlock(t='net'):
                    pass

                for i, a1, a2 in zip(range(len(n1.addr)), n1.addrs, n2.addrs):
                    with ConfigBlock(t='path') as path:
                        self._config_one_host_addr(n1, path, i)
                        self._config_one_host_addr(n2, path, i)

    def _config_conns_9(self):
        for start, n1 in enumerate(self.resource.nodes):
            for n2 in self.resource.nodes[start + 1:]:
                self._config_one_connection(n1, n2)

    def config_host(self, node):
        resource = self.resource

        with ConfigBlock(t='on %s' % node.hostname) as N:
            if self.drbd_version_tuple >= (9, 0, 0):
                N.write("node-id %d;" % node.id)
            else:
                # 8.4 compat
                N.write("address %s:%d;" % (node.addr, node.port))

            for index, disk in enumerate(node.disks):
                with ConfigBlock(t='volume %d' % index) as V:
                    V.write("device %s;" % disk.device())
                    V.write("disk %s;" % (disk.disk or "none"))
                    if disk.disk:
                        V.write("meta-disk %s;" % (disk.meta or "internal"))

    def config(self):
        text = ["global { usage-count no; }\n\n"]

        resource = self.resource
        with ConfigBlock(dest_fn=lambda x: text.append(x),
                         t="resource %s" % resource.name):

            with ConfigBlock(t='handlers') as handlers:
                handlers.write(resource.handlers)

            with ConfigBlock(t='options') as res_options:
                res_options.write(resource.resource_options)

            with ConfigBlock(t='disk') as disk:
                disk.write("disk-flushes no;")
                disk.write("md-flushes no;")
                disk.write(resource.disk_options)

            with ConfigBlock(t='net') as net:
                if resource.rdma:
                    net.write("transport rdma;")
                net.write(resource.net_options)

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

            if self.drbd_version_tuple >= (9, 0, 0):
                self._config_conns_9()
            else:
                self._config_conns_84()


        return "".join(text)

    def update_config(self):
        """ Create or update the configuration file on the node when needed. """

        if self.config_changed:
            self.config_changed = False
            config = self.config()
            file = open(os.path.join(self.resource.logdir,
                                     'drbd.conf-%s' % self.name), 'w')
            file.write(config)
            file.close
            self.run(['install-config'], stdin=StringIO(config), prepare=True)

    def config_proxy(self):
        """ Update DRBD proxy options in the configuration file. """
        # TODO: (wap) Implement adding proxy options
        pass

    def listen_to_events(self):
        f = open(os.path.join(self.resource.logdir, 'events-%s' % self.name), 'ab')
        try:
            if self.events:
                self.events.terminate()
                self.events.wait()
        except:
            pass
        devnull = open('/dev/null', 'r')
        self.events = subprocess.Popen(
            ['ssh', '-q', '-l', 'root', self.name,
             'drbdsetup', 'events2', 'all', '--statistics', '--timestamps'],
            stdout=f, stderr=subprocess.STDOUT, stdin=devnull, close_fds=True)
        self.event(r'exists -', word_boundary=False)

    def run(self, *args, **kwargs):
        if not kwargs.pop('prepare', False):
            self.update_config()
        # by default send all output to the log
        if not 'stdout' in kwargs:
            kwargs['stdout'] = logstream
        if not 'stderr' in kwargs:
            kwargs['stderr'] = logstream
        log(self.name + ': ' + ' '.join(pipes.quote(str(x)) for x in args[0]))
        return super(Node, self).run(*args, **kwargs)

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

    def after_up(self):
        """ When a node is brought up, it normally connects to all
        the other nodes. """

        for node in self.resource.nodes:
            if self is not node:
                self.connections.add(Connection(self, node))

    def adjust(self):
        self.update_config()
        self.run(['drbdadm', 'adjust', 'all', '-v'])

    def up(self, extra_options=[]):
        Nodes([self]).up(extra_options)

    def up_wait(self, extra_options=[]):
        # A single node doesn't know who to wait for...
        return self.up(extra_options)

    def after_down(self):
        for node in self.resource.nodes:
            if self is not node:
                self.connections.remove(Connection(self, node))

    def down(self):
        Nodes([self]).down()

    def attach(self):
        Nodes([self]).attach()

    def detach(self):
        Nodes([self]).detach()

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

    def bidir_connections_to_node(self, new_node):
        return Nodes([self]).bidir_connections_to_node(new_node)

    def connections_to_node(self, new_node):
        return Nodes([self]).connections_to_node(new_node)

    def event(self, *args, **kwargs):
        return Nodes([self]).event(*args, **kwargs)

    def asPrimary(self, **kwargs):
        return AsPrimary(self, **kwargs)

    def primary(self, res="all", force=False, wait=True):
        if force:
            self.run(['drbdadm', 'primary', '--force', res, '-v'])
            ev = []
            if self.volumes.diskful:
                ev.append(r'device .* disk:UpToDate')
            if wait:
                ev.append(r'resource .* role:Primary')
            self.event(*ev)
        else:
            self.run(['drbdadm', 'primary', res, '-v'])
            if wait:
                self.event(r'resource .* role:Primary')

    def secondary(self, res="all", wait=True):
        self.run(['drbdadm', 'secondary', res])
        if wait:
            self.event(r'resource .* role:Secondary')

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
        with open(os.path.join(self.resource.logdir, output_filename), 'w') as output_file:
            output_file.write(result)

        fio_output = json.loads(result)

        # Ubuntu Xenial distributes fio version 2, which names the io_kbytes field wrongly
        io_kbytes_field = 'io_bytes' if fio_output['fio version'].startswith('fio-2') else 'io_kbytes'

        job = fio_output['jobs'][0]
        log('fio results: read={}KiB, write={}KiB, time={}s'.format(
            job['read'][io_kbytes_field],
            job['write'][io_kbytes_field],
            job['elapsed']))

        self.fio_count = self.fio_count + 1
        return fio_output

    def net_device_to_peer(self, peer, net_num=0):
        """Returns the network device this peer is reachable via."""
        lines = self.run(['ip', '-o', 'route', 'get', peer.addrs[net_num]],
                         return_stdout=True)
        fields = lines.split(' ')
        dev = fields[2]
        return dev

    @staticmethod
    def _iptables_cmd_1(chain, sa, sp, da, dp, jump, add_remove, additional_filter=[]):
        r = ['iptables',
             add_remove, chain,
             "-p", "tcp",
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
        r.append(Node._iptables_cmd_1('drbd-test-output',  self.addrs[path_nr],  self.port, node2.addrs[path_nr],       None, jump, add_remove))
        r.append(Node._iptables_cmd_1('drbd-test-output',  self.addrs[path_nr],       None, node2.addrs[path_nr], node2.port, jump, add_remove))
        r.append(Node._iptables_cmd_1('drbd-test-input',  node2.addrs[path_nr],       None,  self.addrs[path_nr],  self.port, jump, add_remove))
        r.append(Node._iptables_cmd_1('drbd-test-input',  node2.addrs[path_nr], node2.port,  self.addrs[path_nr],       None, jump, add_remove))
        return r

    def block_path(self, other_node, net_number=0, jump_to="DROP", iptables_filter=[]):
        """Uses iptables to block one network path."""
        log("BLOCKING path #%d from %s to %s" % (net_number, self, other_node))
        cmds = self._iptables_cmd(other_node, jump_to, net_number, "-I", iptables_filter)
        for c in cmds:
            self.run(c)

    def block_paths(self, net_number=0, jump_to="DROP"):
        for n in self.resource.nodes.difference([self]):
            self.block_path(n, net_number=net_number, jump_to=jump_to)

    def unblock_path(self, other_node, net_number=0, jump_to="DROP"):
        """Uses iptables to unblock one network path."""
        log("Unblocking path #%d from %s to %s" % (net_number, self, other_node))
        cmds = self._iptables_cmd(other_node, jump_to, net_number, "-D")
        for c in cmds:
            self.run(c)

    def unblock_paths(self, net_number=0, jump_to="DROP"):
        for n in self.resource.nodes.difference([self]):
            self.unblock_path(n, net_number=net_number, jump_to=jump_to)

    def _block_packet_type(self, packet, op, from_node, volume):
        cmdline = ['iptables', op, 'drbd-test-input', '-p', 'tcp']
        if from_node is not None:
            cmdline += ['-s', from_node.addrs[0]]
        cmdline += [ '-m', 'string', '--algo', 'bm', '--from', '0',
                     '--hex-string', '|8620ec20 %04X %04X 0000|' % (volume, packet)]
        for ipt_target in ['LOG', 'DROP']:
            self.run(cmdline + ['-j', ipt_target])

    def block_packet_type(self, packet, from_node=None, volume=0):
        self._block_packet_type(packet, '-A', from_node, volume)

    def unblock_packet_type(self, packet, from_node=None, volume=0):
        self._block_packet_type(packet, '-D', from_node, volume)

    def dmesg(self, pattern=None, mode='--read-clear'):
        """Fetches (part of) dmesg; clears it afterwards.

        Returns a list of tuples, containing (string, match object), for each line.
        If pattern is None, simply returns the list of lines."""

        output = self.run(['dmesg', mode], return_stdout=True)
        lines = output.splitlines()
        if not pattern:
            return lines

        result = []
        for l in lines:
            m = re.search(pattern, l)
            if m:
                log("line %s, match %s" % (l, m))
                result.append((l, m))

        return result

    def _drbdsetup_lines(self):
        output = node.run(['drbdsetup', 'status', '--s', '--v', self.resource.name],
                          return_stdout=True)
        return output.splitlines()

    def volume_value(self, which=None, volume=0):
        "Returns one DRBD (or a dict) value via drbdsetup."

        right_volume = False
        values = {}
        for l in self._drbdsetup_lines():
            # Exactly two spaces, else it's a peer-disk
            vol_m = re.search(r'^  volume:(\d+)', l)
            if vol_m:
                right_volume = (int(vol_m.group(1)) == volume)

            if right_volume:
                m = re.findall(r'([a-z-]+):(\S+)', l)
                for (k, v) in m:
                    values[k] = m

        if which and which in values:
            return values[which]

        return values

    def peer_disk_value(self, peer, which=None, volume=0):
        "Returns one DRBD (or a dict) value via drbdsetup."

        right_host = False
        right_volume = False
        values = {}
        for l in self._drbdsetup_lines():
            # Exactly four spaces for a peer-disk
            vol_m = re.search(r'^    volume:(\d+)', l)
            if vol_m:
                right_volume = (int(vol_m.group(1)) == volume)

            host_m = re.search(r'^  (\S+) node-id:(\d+)', l)
            if host_m:
                right_host = (host_m.group(1) == peer)

            if right_host and right_volume:
                m = re.findall(r'([a-z-]+):(\S+)', l)
                for (k, v) in m:
                    values[k] = m

        if which and which in values:
            return values[which]

        return values

    def set_fault_injection(self, volume, faults):
        self.run(['enable-faults',
	      '--faults=%d' % (faults),
              '--rate=100',
              '--devs=%d' % (1 << volume.minor)])

    def disable_fault_injection(self, volume):
        self.run(['disable-faults', '--devs=%d' % (1 << volume.minor)])


def skip_test(text):
    print(text, file=sys.stderr)
    sys.exit(100)


def scan_syslog_files(logdir):
    """ Scan for indications of failures in syslog files. """

    def func():
        found = False

        for filename in os.listdir(logdir):
            match = re.match(r'syslog-(.*)', filename)
            path = os.path.join(logdir, filename)
            if os.path.isfile(path) and match:
                for line in open(path):
                    if re.search(r'(BUG:|INFO:|ASSERTION|general protection fault)', line):
                        log('%s: %s' % (match.group(1), line))
                        found = True

        if found:
            raise SystemExit(3)
    return func


def setup(parser=argparse.ArgumentParser(),
          _node_class=Node, _res_class=Resource,
          nodes=None, max_nodes=None, min_nodes=2, multi_paths=False):
    """
    Test setup.  Returns a resource object.

    Keyword arguments:
      parser    -- command line argument parser to use
                   (for recognizing additional arguments)
      nodes, min_nodes, max_nodes
                -- exact, minimum, and maximum number of test nodes required
      proxy     -- enables proxy connection between two test nodes
      lz4, zstd -- enables compression plugins with DRBD proxy
      memlimit  -- sets memlimit value for DRBD proxy
    """
    parser.add_argument('node', nargs='*')
    parser.add_argument('--job')
    parser.add_argument('--resource')
    parser.add_argument('--logdir')
    parser.add_argument('--cleanup', default='success',
                        choices=('success', 'always', 'never'))
    parser.add_argument('--volume-group', default='scratch')
    parser.add_argument('--no-syslog', action='store_true')
    parser.add_argument('--vconsole', action='store_true')
    parser.add_argument('--silent', action='store_true')
    parser.add_argument('-d', action='count', dest='debug')
    parser.add_argument('--debug', type=int)
    parser.add_argument('--rdma')
    parser.add_argument('--override-max', action="store_true")
    parser.add_argument('--report-and-quit', action="store_true")
    parser.add_argument('--no-rmmod', action="store_true")
    parser.add_argument('--proxy', action="store_true")
    parser.add_argument('--lz4', action="store_true")
    parser.add_argument('--zstd', type=int)
    parser.add_argument('--memlimit', type=int)
    args = parser.parse_args()

    if nodes is not None:
        min_nodes = max_nodes = nodes

    if args.report_and_quit:
        print("min_nodes=%d" % min_nodes)
        if max_nodes:
            print("max_nodes=%d" % max_nodes)
        sys.exit(0)

    # FIXME: Python's argparse module does not support parsing interleaved
    # command-line options and arguments, which we would need for the per-node
    # --console option.  Drop support for per-node options for now.

    if max_nodes is not None and min_nodes == max_nodes and \
       len(args.node) != min_nodes:
        skip_test('Test case requires %s nodes' % min_nodes)
    if len(args.node) < min_nodes:
        skip_test('Test case requires %s or more nodes' % min_nodes)
    if max_nodes is not None and len(args.node) > max_nodes and not args.override_max:
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

    os.environ['EXXE_TIMEOUT'] = '30'
    os.environ['LOGSCAN_TIMEOUT'] = '30'
    os.environ['DRBD_TEST_JOB'] = args.job
    os.environ['DRBD_LOG_DIR'] = args.logdir

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
    logstream = Tee([sys.stderr, logfile])

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
    resource = _res_class(args.resource,
                          logdir=args.logdir,
                          rdma=args.rdma)

    for node in args.node:
        _node_class(resource, node, args.volume_group,
                    multi_paths=multi_paths)

    if args.vconsole:
        for node in args.node:
            logfile = 'console-%s' % node

            # Check if a virtual machine called "$node" exists -- otherwise we
            # would loop forever below.
            subprocess.check_call(['virsh', 'domid', node], stdout=devnull)
            subprocess.check_call(['screen', '-S', logfile, '-d',
                                   '-m', 'virsh', 'console', node])

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
                                                'console-%s.log' % node)])
            subprocess.check_call(['screen', '-S', logfile, '-p',
                                   '0', '-X', 'log', 'on'])
            log("%s: capturing console" % node, level=2)

            def close_logfile(logfile):
                def func():
                    subprocess.check_call(['screen', '-S', logfile,
                                           '-p', '0', '-X', 'stuff', '\035'])
                return func
            atexit.register(close_logfile(logfile))

    if not args.no_syslog:
        syslog_port = 5140
        syslog_server(args.node, port=syslog_port,
                      acc_name=os.path.join(args.logdir, 'syslog.full.txt'),
                      logfile_name=os.path.join(args.logdir, 'syslog-%s'))
        resource.nodes.run(['rsyslogd', socket.gethostname(), str(syslog_port)],
                           prepare=True)
        # Wait for the syslog files to appear ...
        for node in args.node:
            while not os.path.exists(os.path.join(args.logdir, 'syslog-%s' % node)):
                time.sleep(0.1)
        atexit.register(scan_syslog_files(args.logdir))

    for node in resource.nodes:
        node.listen_to_events()
    resource.nodes.run(['disable-faults'], prepare=True)
    resource.nodes.run(['register-cleanup', '-t', 'bash', '-c',
                        '! [ -e /proc/drbd ] || drbdsetup down $DRBD_TEST_JOB'],
                       prepare=True)
    return resource


# is assert(), but with non-conflicting name
def ensure(want, have, explanation=None):
    if want != have:
        log("Wanted '%s', but got '%s'.\n" % (repr(want), repr(have)))
        if explanation:
            log("%s\n" % explanation)
        raise RuntimeError('assert trigger')


def ensure_subset(smaller, bigger, explanation=None):
    """compares two dictionaries"""
    if not all([smaller[k] == bigger[k] for k in smaller.keys()]):
        log("Wanted '%s', but got '%s'.\n" % (repr(smaller), repr(bigger)))
        if explanation:
            log("%s\n" % explanation)
        raise RuntimeError('assert trigger')


def ensure_not(want, have, explanation=None):
    if want == have:
        log("Wanted something but '%s', got '%s'.\n" % (repr(want), repr(have)))
        if explanation:
            log("%s\n" % explanation)
        raise RuntimeError('assert trigger')


def ensure_not_in_set(search, data, explanation=None):
    if search in data:
        log("Wanted something but '%s', got '%s'.\n" % (repr(search), repr(data)))
        if explanation:
            log("%s\n" % explanation)
        raise RuntimeError('assert trigger')
