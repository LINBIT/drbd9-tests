from subprocess import CalledProcessError
from .drbdtest import log


class TrafficControl(object):
    """
    Delay and throttle connections using 'tc'.

    Warning: The delays apply to all resources.
    """

    def __init__(self, source_node, nodes):
        """ Prepare source_node for traffic control. """

        self.source_node = source_node
        self.nodes = nodes

        for dev, (net_num, nodes) in self._get_nodes_by_dev().items():
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
                ip = node.host.addrs[net_num]
                log('Traffic control for net {0} from {1} to {2} uses {3} ({4})'
                        .format(net_num, self.source_node, node, dev, ip))

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
        for net_num in range(len(self.source_node.host.addrs)):
            dev = self.source_node.host.net_device_to_peer(to_node.host, net_num)
            log('Slowing down connection for net {0} from {1} to {2}'.format(net_num, self.source_node, to_node))

            netem_args = []
            if delay != '':
                netem_args += ['delay', delay]
            if speed != '':
                netem_args += ['rate', speed]

            # Add our netem qdisc as the child of the corresponding class of the 'prio' qdisc.
            self.source_node.run(['tc', 'qdisc', 'replace', 'dev', dev,
                'parent', self._node_to_class(to_node),
                'handle', self._node_to_handle(to_node),
                'netem'] + netem_args)

    def remove_slow_down(self, to_node):
        for net_num in range(len(self.source_node.host.addrs)):
            dev = self.source_node.host.net_device_to_peer(to_node.host, net_num)
            self.source_node.run(['tc', 'qdisc', 'del', 'dev', dev,
                'parent', self._node_to_class(to_node),
                'handle', self._node_to_handle(to_node)])

    def _get_nodes_by_dev(self):
        nodes_by_dev = {}
        for net_num in range(len(self.source_node.host.addrs)):
            for node in self.nodes:
                if node != self.source_node:
                    dev = self.source_node.host.net_device_to_peer(node.host, net_num)
                    if not dev in nodes_by_dev:
                        nodes_by_dev[dev] = (net_num, [])
                    dev_net_num, nodes = nodes_by_dev[dev]
                    if dev_net_num != net_num:
                        raise RuntimeError('{}: network {} and {} use same device {}'
                                .format(node, net_num, dev_net_num, dev))
                    nodes.append(node)
        return nodes_by_dev

    @staticmethod
    def _node_to_class(node):
        # Class "node.id + 1" corresponds to band "node.id"
        return '1:{}'.format(node.id + 1)

    @staticmethod
    def _node_to_handle(node):
        return '{}:'.format(node.id + 100)
