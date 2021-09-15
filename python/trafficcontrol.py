from subprocess import CalledProcessError
from .drbdtest import log


class TrafficControl(object):
    """ Delay and throttle connections using 'tc'. """

    def __init__(self, source_node, nodes):
        """ Prepare source_node for traffic control. """

        self.source_node = source_node
        self.nodes = nodes

        for dev, nodes in self._get_nodes_by_dev().items():
            # Clear away any leftover mess
            try:
                self.source_node.run(['tc', 'qdisc', 'del', 'dev', dev, 'root'])
            except CalledProcessError:
                pass # The command fails when nothing is configured

            self.source_node.run(['tc', 'qdisc', 'replace', 'dev', dev,
                'root',
                'handle', '1:',
                # Use the 'prio' classful qdisc. We do not care about prioritization. We just need some classes.
                'prio',
                'bands', len(self.nodes),
                # Send all unfiltered packets to band 'self.id', where no rate limiting will be applied.
                'priomap'] + [str(self.source_node.id)] * 16)

            for node in nodes:
                ip = node.addr
                log('Traffic control from {0} to {1} uses {2} ({3})'
                        .format(self.source_node, node, dev, ip))

                # Filter packets to the destination IP and send them to the corresponding class.
                self.source_node.run(['tc', 'filter', 'add', 'dev', dev,
                    'parent', '1:',
                    'protocol', 'ip',
                    'prio', '1',
                    'u32',
                    'match', 'ip', 'dst', ip,
                    'flowid', self._node_to_class(node)])

    def reset(self):
        for dev in self._get_nodes_by_dev():
            self.source_node.run(['tc', 'qdisc', 'del', 'dev', dev, 'root'])

    def slow_down(self, to_node, speed='', delay=''):
        dev = self.source_node.net_device_to_peer(to_node)
        log('Slowing down connection from {0} to {1}'.format(self.source_node, to_node))

        netem_args = ['delay', delay] if delay != '' else ['rate', speed]

        # Add our netem qdisc as the child of the corresponding class of the 'prio' qdisc.
        self.source_node.run(['tc', 'qdisc', 'replace', 'dev', dev,
            'parent', self._node_to_class(to_node),
            'handle', self._node_to_handle(to_node),
            'netem'] + netem_args)

    def remove_slow_down(self, to_node):
        dev = self.source_node.net_device_to_peer(to_node)
        self.source_node.run(['tc', 'qdisc', 'del', 'dev', dev,
            'parent', self._node_to_class(to_node),
            'handle', self._node_to_handle(to_node)])

    def _get_nodes_by_dev(self):
        nodes_by_dev = {}
        for node in self.nodes:
            if node != self.source_node:
                dev = self.source_node.net_device_to_peer(node)
                if not dev in nodes_by_dev:
                    nodes_by_dev[dev] = []
                nodes_by_dev[dev].append(node)
        return nodes_by_dev

    @staticmethod
    def _node_to_class(node):
        # Class "node.id + 1" corresponds to band "node.id"
        return '1:{}'.format(node.id + 1)

    @staticmethod
    def _node_to_handle(node):
        return '{}:'.format(node.id + 100)
