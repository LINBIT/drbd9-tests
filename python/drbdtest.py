# setup parameters: console

# FIXME: Why are the prefixes missing from output of the target cleanup scripts?

# FIXME: class Collection: Switch to an ordered set?  Right now, the order in
# which nodes are given on the command line is not preserved.

# FIXME: Check for synchronized time on the test nodes.

# FIXME: How to add a diskless volume on a node?

# FIXME: For test cases with multiple resources, we only need to capture the
# consoles, syslogs, and event logs once. We need to prefix the .pos file names
# and the log messages with the resource name.

from __future__ import print_function

import os
import errno
import sys
import re
import time
import pipes
import socket
import argparse
import subprocess
from subprocess import CalledProcessError
import atexit
from ordered_set import OrderedSet
import exxe

from syslog import syslog_server
from cStringIO import StringIO

TOP = os.getenv('TOP', os.path.join(os.path.dirname(sys.argv[0]), '..'))
DRBD_TEST_DATA = os.getenv('DRBD_TEST_DATA', '/usr/share/drbd-test')

silent = False
verbosity_level = 0
debug_level = 0
skip_cleanup = False

devnull = open(os.devnull, 'rw')


def verbose(*args, **kwargs):
    """ Print message according to configured verbosity level. """

    level = 1
    try:
        level = kwargs.pop('level')
    except:
        pass
    if level <= verbosity_level:
        print(*args, file=sys.stderr)
        sys.stderr.flush()
    else:
        print(*args, file=tee.file)
        tee.file.flush()


def debug(*args, **kwargs):
    """ Print debug message according to configured debug level. """

    level = 1
    try:
        level = kwargs.pop('level')
    except:
        pass
    if level <= debug_level:
        print(*args, file=sys.stderr)


class Cleanup(object):
    """ Catch uncaught exceptions and set skip_cleanup accordingly. """

    def __init__(self, cleanup):
        self.excepthook = sys.excepthook
        sys.excepthook = self.hook
        self.cleanup = cleanup
        if self.cleanup == 'never':
            global skip_cleanup
            skip_cleanup = True

    def hook(self, *args, **kwargs):
        if self.cleanup == 'success':
            global skip_cleanup
            skip_cleanup = True
        self.excepthook(*args, **kwargs)


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
        assert issubclass(member.__class__, self.cls) and \
            self.same_resource([member])
        self.members.add(member)
        return self

    def remove(self, member):
        assert issubclass(member.__class__, self.cls) and \
            self.same_resource([member])
        if member in self.members:
            self.members.remove(member)
        return self

    def extend(self, members):
        for member in members:
            assert issubclass(member.__class__, self.cls) and \
                self.same_resource(members)
        self.members.update(members)
        return self

    def difference(self, members):
        for member in members:
            assert issubclass(member.__class__, self.cls) and \
                self.same_resource(members)
        return self.__class__(self.members.difference(members))


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

    def event(self, *args, **kwargs):
        """ Wait for an event. """

        if self.members:
            where = \
                [_ for node in self.members
                 for _ in ['events-%s' % node.name,
                           '--label', node.name,
                           '-p', '.events.pos']
                 ]
            resource = first(self.members).resource
            resource.logscan(self, where, *args, **kwargs)
        return self

    def run(self, *args, **kwargs):
        """ Run command on all our nodes. """

        if not kwargs.pop('prepare', False):
            self.update_config()
        verbose(' '.join([node.name for node in self]) + ': ' +
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

    def down(self):
        self.run(['drbdadm', 'down', 'all'])
        self.after_down()
        self.event(r'destroy resource')

    def attach(self):
        self.run(['drbdadm', 'attach', 'all', '-v'])
        self.volumes.diskful.event(r'device .* disk:Attaching')
        # and some other state ... Inconsistent, UpToDate, ...
        self.volumes.diskful.event(r'device .* disk:.*')

    def detach(self):
        self.run(['drbdadm', 'detach', 'all', '-v'])
        self.volumes.diskful.event(r'device .* disk:Detaching')
        self.volumes.diskful.event(r'device .* disk:Diskless')

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
            resource.logscan(self, where, *args, **kwargs)

    def get_diskful(self):
        """ Return volumes that have a disk. """
        return Volumes([_ for _ in self if _.disk is not None])
    diskful = property(get_diskful)

    def get_diskless(self):
        """ Return volumes that do not have a disk. """
        return Volumes([_ for _ in self if _.disk is None])
    diskless = property(get_diskless)

    def fio(self, section, jobfile=None, return_output=False, fio_extra=None, name=None):
        """
            Run fio, the 'flexible I/O tester'.

            fio_extra would get appended to the jobfile;
            should be a list of strings, eg. ['bs=4k', 'runtime=20'].
        """
        if jobfile is None:
            jobfile = os.path.join(TOP, 'target', 'write-verify.fio.in')
        template = open(jobfile).read()
        for volume in self:
            job = re.sub(r'@device@', '/dev/drbd%d' % volume.minor, template)
            node = volume.node
            n = 0
            while True:
                prefix = os.path.join(node.resource.logdir, 'fio-%s-%s%s%s%s' %
                                      (node.name, volume.volume,
                                       '-%s' % section if section else '',
                                       '+%s' % name if name else '',
                                       '-%s' % n if n > 0 else ''))
                if not (os.path.exists(prefix + '.fio') or
                        os.path.exists(prefix + '.log')):
                    break
                n += 1

            # TODO: Without auto-promote, we would need to switch to primary on
            # each node first.  With auto-promote, since auto-promote allows
            # parallel reading, we could start read jobs on multiple nodes in
            # parallel.

            result = None

            cmd = ['fio']
            if section:
                cmd.extend(['--section', section])
            cmd.append('-')

            jobfile = open(prefix + '.fio', 'w+')
            jobfile.write(job)
            if fio_extra:
                for arg in fio_extra:
                    # let "fio" be the first string, still
                    cmd.insert(1, "--%s" % arg)
            #    jobfile.write("\n\n[%s]\n" % section)
            #    for l in fio_extra:
            #        jobfile.write("%s\n" % l)

            jobfile.flush()
            jobfile.seek(0)

            if verbosity_level >= 3:
                sys.stderr.write(jobfile.read())
                jobfile.seek(0)

            logfile = open(prefix + '.log', 'w+')
            logfile.write("## command: %s\n\N" % cmd)
            try:
                node.run(cmd, stdin=jobfile, stdout=logfile)
                if return_output:
                    logfile.seek(0)
                    result = FioParser(logfile.readlines())
            except CalledProcessError:
                logfile.seek(0)
                sys.stderr.write(logfile.read())
                raise
            else:
                if verbosity_level >= 3:
                    logfile.seek(0)
                    sys.stderr.write(logfile.read())
            finally:
                logfile.close()

            return result


class Connections(Collection):
    def __init__(self, members=[]):
        super(Connections, self).__init__(Connection, members)

    def event(self, *args, **kwargs):
        """ Wait for an event. """

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
            resource.logscan(self, where, *args, **kwargs)

    def from_node(self, node):
        return self.from_nodes([node])

    def from_nodes(self, nodes):
        return Connections([_ for _ in self if _.nodes[0] in nodes])

    def to_node(self, node):
        return self.to_nodes([node])

    def to_nodes(self, nodes):
        return Connections([_ for _ in self if _.nodes[1] in nodes])

    def connect(self):
        for connection in self:
            node0, node1 = connection.nodes
            node0.run(['drbdadm', 'connect', '%s:%s' %
                       (connection.resource.name, node1.hostname)])
        self.event(r'connection .* connection:Connecting')
        for connection in self:
            node0 = connection.nodes[0]
            node0.connections.add(connection)

    def disconnect(self, wait=True):
        for connection in self:
            node0, node1 = connection.nodes
            node0.run(['drbdadm', 'disconnect', '%s:%s' %
                       (connection.resource.name, node1.hostname)])
        if wait:
            self.event(r'connection .* connection:StandAlone')
        for connection in self:
            node0, node1 = connection.nodes
            node0.connections.remove(connection)


class PeerDevices(Collection):
    def __init__(self, members=[]):
        super(PeerDevices, self).__init__(PeerDevice, members)

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
            resource.logscan(self, where, *args, **kwargs)


# Now that all collection classes are defined, define inter-class dependencies:
Nodes.finish()
Volumes.finish()


class Resource(object):
    def __init__(self, name, logdir):
        self.name = name
        self.net_options = ""
        self.nodes = Nodes()
        self.num_volumes = 0
        self.logdir = logdir
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

    def add_disk(self, size, meta_size=None, diskful_nodes=None):
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
                node.add_disk(volume, size, meta_size)
            else:
                node.add_disk(volume)

    volumes = property(lambda self: self.nodes.volumes)
    connections = property(lambda self: self.nodes.connections)
    peer_devices = property(lambda self: self.nodes.peer_devices)

    def cleanup(self):
        if not skip_cleanup:
            self.nodes.run(['cleanup'], prepare=True, catch=True)
        for node in self.nodes:
            node.cleanup()

    def rmmod(self):
        for n in self.nodes:
            if n.drbd_major_version == 9:
                # might not even be loaded
                try:
                    n.run(['rmmod', 'drbd_transport_tcp'])
                except:
                    pass
        self.nodes.run(['rmmod', 'drbd'])

    def logscan(self, collection, where, *args, **kwargs):
        """ Run logscan to scan / wait for events to occur. """
        if args is None:
            args = []
        no = kwargs.get('no', [])
        if isinstance(no, basestring):
            no = [no]

        self.sync_events(collection.__class__)

        verbose('Waiting for event ' +
                ' '.join([str(_) for _ in collection]) + ' ' +
                ' '.join(['-y ' + _ for _ in args]) +
                ' '.join(['-n ' + _ for _ in no]))

        cmd = ['logscan', '-d', os.environ['DRBD_LOG_DIR'], '-w']
        if silent:
            cmd.append('--silent')
        if verbosity_level >= 2:
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
        subprocess.check_call(cmd + where)

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
                     os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0666)
        os.write(fd, data)
        os.close(fd)

    def append_to_posfile(self, posfile, node):
        data = '1 0 events-%s\n' % node.name
        pathname = os.path.join(os.environ['DRBD_LOG_DIR'], posfile)
        fd = os.open(pathname, os.O_WRONLY | os.O_APPEND)
        os.write(fd, data)
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
        self.forbidden_patterns.update([
            r'connection:Timeout',
            r'connection:NetworkFailure',
            r'connection:ProtocolError',
            r'connection:BrokenPipe',
            r'disk:Failed',
            r'peer-disk:Failed'])

    def down(self):
        self.forbidden_patterns.difference_update([
            r'connection:BrokenPipe'
        ])
        self.nodes.down()

    def initial_resync(self, sync_from):
        self.nodes.run(['drbdadm', 'peer-device-options', '--c-min-rate', '0', 'all', '-v'])
        self.peer_devices.event(r'peer-device .* peer-disk:UpToDate',
                                timeout=300)


class Volume(object):
    def __init__(self, node, volume, size=None, meta_size=None, minor=None,
                 max_peers=None):
        if volume is None:
            volume = node.resource.next_volume()
        if minor is None:
            minor = node.next_minor()
        self.volume = volume
        self.minor = minor
        self.node = node
        if max_peers is None:
            max_peers = len(node.resource.nodes) - 1
        self.disk = None
        self.meta = None
        if size:
            self.disk = self.create_disk(
                size,
                '%s-disk%d' % (self.node.resource.name, volume),
                None if meta_size else '--internal-meta', max_peers)
            if meta_size:
                self.meta = self.create_disk(
                    meta_size,
                    '%s-meta%d' % (self.node.resource.name, volume),
                    '--external-meta', max_peers)

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

    def create_disk(self, size, name, meta, max_peers):
        cmd = ['create-disk']
        if meta:
            cmd.extend([meta, '--max-peers', str(max_peers)])
        cmd.extend(['--job', os.environ['DRBD_TEST_JOB'],
                   '--volume-group', self.node.volume_group, '--size', size,
                    name])
        return self.node.run(cmd, return_stdout=True, prepare=True)

    def event(self, *args, **kwargs):
        return Volumes([self]).event(*args, **kwargs)


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


class ConfigBlock(object):
    INDENT = "     "

    all_text = ""

    def __init__(self, parent=None, fh=None, fn=None, t="", dest_fn=None):
        self.parent = parent
        self.name = t
        self.fd = None
        self.to_var = dest_fn

        if self.parent:
            self.indent = self.parent.indent + self.INDENT
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

    def __enter__(self):
        self.write_no_indent("%s%s {\n" % (self.indent, self.name))
        return self

    def __exit__(self, *ignore_exception):
        self.write_no_indent("%s}\n\n" % self.indent)

        if self.fd and not self.parent and self.do_close:
            self.fd.close()

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
            addr=None, port=7789,
            multi_paths=None):
        super(Node, self).__init__(['ssh', '-l',
                                    'root', name,
                                    'exxe', '--syslog'], prefix='%s: ' % name)
        self.resource = resource
        self.name = name
        self.addr = addr if addr else subprocess.check_output(
            ['gethostip', '-d', name]).strip()
        self.port = port
        self.disks = []  # by volume
        self.id = len(self.resource.nodes)
        self.resource.nodes.add(self)
        self.resource.posfiles_add_node(self)
        # start at some higher number, so that there's no collision with DRBDmanage volumes.
        self.minors = 137
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
                  'EXXE_IDENT=exxe/%s' % os.environ['DRBD_TEST_JOB'],
                  'DRBD_TEST_VERBOSE=%s' % verbosity_level],
                 prepare=True)
        self.hostname = self.run(['hostname', '-f'], return_stdout=True,
                                 prepare=True)
        drbd_version = self.run(['drbd-version'], return_stdout=True,
                                prepare=True)
        self.drbd_major_version = int(re.sub(r'\..*', '', drbd_version))

        self.addrs = [self.addr]
        if multi_paths:
            net_2 = self.run(['ip', '-oneline', 'a', 'show', 'label', 'eth0:1'],
                    return_stdout=True)
            verbose("got further path %s", net_2)
            m = re.search(r'^\s*\d+:\s+\w+\s+inet\s+([\d\.]+)/\d+', net_2)
            if not m:
                raise RuntimeError("%s has no eth0:1", self)
            self.addrs.append(m.group(1))

        self.run(["bash", "-c", 'iptables -N drbd-test-input && iptables -A INPUT -j drbd-test-input || true'])
        self.run(["bash", "-c", 'iptables -N drbd-test-output && iptables -A OUTPUT -j drbd-test-output || true'])


    def addr_port(self, net_num=0):
        return '%s:%s' % (self.addrs[net_num], self.port)

    def cleanup(self):
        self.config_changed = False
        if hasattr(self, 'events'):
            self.events.terminate()

    def __str__(self):
        # return '%s:%s' % (self.resource, self.name)
        return self.name

    def next_minor(self):
        self.minors += 1
        return self.minors

    def add_disk(self, volume, size=None, meta_size=None):
        """
        Keyword arguments:
        volume -- volume number of the new disk
        size -- size of the data device or None for a diskless node
        meta_size -- size of the meta-data device
        """
        # FIXME: Volume is not added at the right index (by volume number)
        # here.  Does that matter?
        self.disks.append(Volume(self, volume, size, meta_size))
        self.config_changed = True

    def _config_conns_84(self, parent):
        # no explicit connections for 8.4
        # done via "address" in "on <host>" section
        pass

    def _config_one_host_addr(self, node, block, i):
        block.write("host %s address %s:%d;" %
                    (node.name,
                     node.addrs[i],
                     node.port))

    def _config_one_connection(self, n1, n2, parent):
        with ConfigBlock(parent=parent, t="connection") as c:
            with ConfigBlock(parent=c, t='net') as net:
                pass

            for i, a1, a2 in zip(xrange(len(n1.addr)), n1.addrs, n2.addrs):
                with ConfigBlock(parent=c, t='path') as path:
                    self._config_one_host_addr(n1, path, i)
                    self._config_one_host_addr(n2, path, i)

    def _config_conns_9(self, parent):
        for start, n1 in enumerate(self.resource.nodes):
            for n2 in self.resource.nodes[start + 1:]:
                self._config_one_connection(n1, n2, parent)

    def config_host(self, node, parent, index):
        resource = self.resource

        with ConfigBlock(parent=parent, t='on %s' % node.hostname) as N:
            if self.drbd_major_version == 9:
                N.write("node-id %d;" % index)
            else:
                # 8.4 compat
                N.write("address %s:%d;" % (node.addr, node.port))

            for index, disk in enumerate(node.disks):
                with ConfigBlock(parent=N, t='volume %d' % index) as V:
                    V.write("device /dev/drbd%d;" % disk.minor)
                    V.write("disk %s;" % (disk.disk or "none"))
                    if disk.disk:
                        V.write("meta-disk %s;" % (disk.meta or "internal"))

    def config(self):
        text = ["global { usage-count no; }\n\n"]

        resource = self.resource
        with ConfigBlock(dest_fn=lambda x: text.append(x),
                           t="resource %s" % resource.name) as res:

            with ConfigBlock(parent=res, t='disk') as disk:
                disk.write("disk-flushes no;")
                disk.write("md-flushes no;")

            with ConfigBlock(parent=res, t='net') as net:
                net.write(resource.net_options)

            for index, n in enumerate(resource.nodes):
                self.config_host(n, parent=res, index=index)

            if self.drbd_major_version == 8:
                self._config_conns_84(res)
            else:
                self._config_conns_9(res)

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

    def listen_to_events(self):
        file = open(os.path.join(self.resource.logdir,
                                 'events-%s' % self.name),
                    'w')
        self.events = subprocess.Popen(
            ['ssh', '-q', '-l', 'root', self.name,
             'drbdsetup', 'events2', 'all', '--statistics', '--timestamps'],
            stdout=file)

    def run(self, *args, **kwargs):
        if not kwargs.pop('prepare', False):
            self.update_config()
        verbose(self.name + ': ' + ' '.join(pipes.quote(str(x)) for x in args[0]))
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

    def up(self, extra_options=[]):
        Nodes([self]).up(extra_options)

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

    def event(self, *args, **kwargs):
        return Nodes([self]).event(*args, **kwargs)

    def primary(self, force=False):
        if force:
            self.run(['drbdadm', 'primary', '--force', 'all'])
            self.event(r'resource .* role:Primary')
            self.volumes.diskful.event(r'device .* disk:UpToDate')
        else:
            self.run(['drbdadm', 'primary', 'all'])
            self.event(r'resource .* role:Primary')

    def secondary(self):
        self.run(['drbdadm', 'secondary', 'all'])
        self.event(r'resource .* role:Secondary')

    def connect(self, node):
        return Connections([Connection(self, node)]).connect()

    def disconnect(self, node, wait=True):
        return Connections([Connection(self, node)]).disconnect(wait=wait)

    def fio(self, *args, **kwargs):
        return self.volumes.fio(*args, **kwargs)

    def fio_bench(self, section="bench", name=None, fio_extra=[], runtime=15):
        """
            Runs fio, but with a timelimit instead of sequential until EOF,
            so that the results have some meaning.

            With a 4M LV a single write pass has too much noise.
        """
        return self.fio(
                section = section,
                return_output = True,
                name = name,
                fio_extra = [ 'runtime=%d' % runtime ] + fio_extra,
                )

    def net_device_to_peer(self, peer, net_num=0):
        """Returns the network device this peer is reachable via."""
        lines = self.run(['ip', '-o', 'route', 'get', peer.addrs[net_num]],
                         return_stdout=True)
        fields = lines.split(' ')
        dev = fields[2]
        assert re.search(r'^eth', dev)
        return dev


class Tee(object):
    """ File object that forwards writes and flushes to two other file objects. """

    class Tee(object):
        def __init__(self, file1, file2):
            self.file1 = file1
            self.file2 = file2

        def write(self, data):
            self.file1.write(data)
            self.file2.write(data)

        def flush(self):
            self.file1.flush()
            self.file2.flush()

    def __init__(self, file):
        self.file = file
        self.stdout = sys.stdout
        self.stderr = sys.stderr
        sys.stdout = Tee.Tee(self.file, sys.stdout)
        sys.stderr = Tee.Tee(self.file, sys.stderr)

    def __del__(self):
        sys.stdout = self.stdout
        sys.stderr = self.stderr
        self.file.close()

    def __enter__(self):
        pass

    def __exit__(self, _type, _value, _traceback):
        pass


def skip_test(text):
    print(text)
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
                        sys.stderr.write('%s: %s' % (match.group(1), line))
                        found = True

        if found:
            raise SystemExit(3)
    return func


def setup(parser=argparse.ArgumentParser(),
          nodes=None, max_nodes=None, min_nodes=2, multi_paths=False):
    """
    Test setup.  Returns a resource object.

    Keyword arguments:
      parser    -- command line argument parser to use
                   (for recognizing additional arguments)
      nodes, min_nodes, max_nodes
                -- exact, minimum, and maximum number of test nodes required
    """
    parser.add_argument('node', nargs='*')
    parser.add_argument('--job')
    parser.add_argument('--resource')
    parser.add_argument('--logdir')
    parser.add_argument('--cleanup', default='success',
                        choices=['success', 'always', 'never'])
    parser.add_argument('--volume-group', default='scratch')
    parser.add_argument('--vconsole', action='store_true')
    parser.add_argument('--silent', action='store_true')
    parser.add_argument('-v', action='count', dest='verbose')
    parser.add_argument('--verbose', type=int)
    parser.add_argument('-d', action='count', dest='debug')
    parser.add_argument('--debug', type=int)
    parser.add_argument('--override-max', action="store_true", dest='override_max')
    parser.add_argument('--report-and-quit', dest='report_n_quit', default=False, action="store_true")
    args = parser.parse_args()

    if nodes is not None:
        min_nodes = max_nodes = nodes

    if args.report_n_quit:
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

    global verbosity_level
    if args.verbose is not None:
        verbosity_level = args.verbose

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

    os.environ['EXXE_TIMEOUT'] = '30'
    os.environ['LOGSCAN_TIMEOUT'] = '30'
    os.environ['DRBD_TEST_JOB'] = args.job
    os.environ['DRBD_LOG_DIR'] = args.logdir
    os.environ['TOP'] = TOP

    if not silent:
        print('Logging to directory %s' % args.logdir)

    if not os.access(args.logdir, os.R_OK + os.X_OK + os.W_OK):
        os.makedirs(args.logdir)
    if job_symlink is not None:
        try:
            os.remove(os.path.join('log', job_symlink))
        except OSError, e:
            if e.errno != errno.ENOENT:
                raise e
        os.symlink(args.job, os.path.join('log', job_symlink))

    global tee
    tee = Tee(open(os.path.join(args.logdir, 'test.log'), 'w'))

    Cleanup(args.cleanup)
    resource = Resource(args.resource,
                        logdir=args.logdir)

    for node in args.node:
        Node(resource, node, args.volume_group,
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
            verbose("%s: capturing console" % node, level=2)

            def close_logfile(logfile):
                def func():
                    subprocess.check_call(['screen', '-S', logfile,
                                           '-p', '0', '-X', 'stuff', '\035'])
                return func
            atexit.register(close_logfile(logfile))

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

## Python 2.6 compat
## http://stackoverflow.com/questions/17539985/check-output-error-in-python
def fake_check_output(*popenargs, **kwargs):
    process = subprocess.Popen(stdout=subprocess.PIPE, *popenargs, **kwargs)
    output, unused_err = process.communicate()
    retcode = process.poll()
    if retcode:
        cmd = kwargs.get("args")
        if cmd is None:
            cmd = popenargs[0]
        error = subprocess.CalledProcessError(retcode, cmd)
        error.output = output
        raise error
    return output

try: subprocess.check_output
except: subprocess.check_output = fake_check_output


class FioParser():
    def _unit_to_num(self, string):
        return { '': 1, 'K': 1e3, 'm': 1e-3, 'u': 1e-6}[string or '']

    def _kv_into_dict(self, dest, string, unit=1.0):
        # m = re.search(r"^(\S+) +clat \((\w+)\):(?: (\w+)=([\d\.]+),?)+\s*$", l)
        # grx, re module doesn't support repeated captures
        # http://stackoverflow.com/questions/9764930/capturing-repeating-subpatterns-in-python-regex
        for part in string.split(", "):
            kv = re.search("(\w+)\s*=\s*([\d\.]+)(K|m)?(B|B/s|sec)?", part)
            #print(part)

            unit2 = unit * self._unit_to_num(kv.group(3))
            dest[kv.group(1)] = float(kv.group(2)) * unit2

        return

    def __init__(self, data):
        self.lines = data
        self.data = dict()

        for i in range(0, len(self.lines)):

            # test-vm-30:   write: io=1008.0KB, bw=67689B/s, iops=16, runt= 15249msec
            m = re.search(r"^\S+\s+(read|write|\w+)\s*: (io=.*)", self.lines[i])
            if not m:
                continue

            # fio returns two lines - one summary line, and one status group with some more data.
            # get these merged.
            k = m.group(1).lower()
            res = self.data.get(k, None)

            if not res:
                res = StatsDict()
                self.data[k] = res

            self._kv_into_dict(res, m.group(2))

            # test-vm-32:     clat (usec): min=3, max=990, avg= 5.51, stdev=29.75
            n = re.search(r"^\S+\s+clat \((\w*)sec\): (.*)", self.lines[i+2])
            if n:
                unit = self._unit_to_num(n.group(1))
                self._kv_into_dict(res, n.group(2), unit)

            print(res)

    def latency(self, what="write"):
        """returns a dict with min/max/avg/... in sec"""
        return self.data.get(what, None)


class StatsDict(dict):
    # see also http://stackoverflow.com/questions/4984647/accessing-dict-keys-like-an-attribute-in-python
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__

    def Z(self, val):
        return (val - self.avg) / self.stdev

    def Zmin(self):
        return self.Z(self.min)

    def Zmax(self):
        return self.Z(self.max)


class Measurement():
    # writes into the STDOUT file, where a script fetches that afterwards

    def __init__(self, path):
        self.id = path

    def save(self, name, value):
        print('<measurement> | %s | %s | %s' % (self.id, name, value))
