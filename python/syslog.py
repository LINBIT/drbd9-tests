#! /usr/bin/env python

# A very primitive syslog server.

import re
import socket
from threading import Thread
from SocketServer import (BaseRequestHandler, ThreadingTCPServer, UDPServer)


class Hostnames(object):
    """ Mapping from IPv4 / IPv6 addresses to host names. """

    def __init__(self):
        self.hostnames = {}

    def add(self, host):
        for addr in socket.getaddrinfo(host, None):
            af, _, _, _, sa = addr
            if af in (socket.AF_INET, socket.AF_INET6):
                try:
                    previous_host = self.hostnames[sa[0]]
                    if previous_host != host:
                        raise RuntimeError("Address %s assigned to host %s as well as %s" %
                                           (sa[0], previous_host, host))
                except KeyError:
                    pass
                self.hostnames[sa[0]] = host

    def __getitem__(self, addr):
        return self.hostnames.get(addr)


class SyslogHandler(BaseRequestHandler):
    """
    Abstract handler for a syslog message.  Messages from known hosts are
    logged into a per-host logfile.
    """

    def __init__(self, *args, **kwargs):
        BaseRequestHandler.__init__(self, *args, **kwargs)

    def handle(self, message):
        message = re.sub(r'^<[0-9]*>(.*\n)$', r'\1', message)
        file = self.logfile()
        file.write(str(message))
        file.flush()
        if self.server.accumulated:
            self.server.accumulated.write(str(message))
            self.server.accumulated.flush()

    def logfile(self):
        addr = self.client_address[0]
        host = self.server.hostnames[addr]
        if host is None:
            host = addr
        try:
            logfile = self.server.logfiles[host]
        except KeyError:
            logfile = open(self.server.logfile_name % host, 'a')
            self.server.logfiles[host] = logfile
        return logfile


class TCPSyslogHandler(SyslogHandler):
    """ TCP syslog message handler: multiple messages per TCP "packet". """

    def __init__(self, *args, **kwargs):
        SyslogHandler.__init__(self, *args, **kwargs)

    def handle(self):
        # NOTE: one TCPServer "request" is one accept().
        # Once this "handle()" routine returns, the server will shutdown() and
        # close() the accepted socket.  Doing a tcp handshake for almost every
        # line of syslog will cause message loss.
        # So we better loop here until the source stops sending.
        SyslogHandler.handle(self, "ESTABLISHED\n")
        part = ''
        lines = []
        while True:
            data = self.request.recv(2048)
            if not data:
                break
            lines = data.splitlines(True)
            if part:
                lines[0] = ''.join([part, lines[0]])
            part = ''
            for message in lines:
                if message[-1] != '\n':
                    part = message
                    break
                SyslogHandler.handle(self, message)
        if part:
                SyslogHandler.handle(self, part + '\n')
        SyslogHandler.handle(self, "SHUTDOWN\n")

class UDPSyslogHandler(SyslogHandler):
    """ UDP syslog message handler: one message per UDP packet. """

    def __init__(self, *args, **kwargs):
        SyslogHandler.__init__(self, *args, **kwargs)

    def handle(self):
        data = self.request[0]
        SyslogHandler.handle(self, data + '\n')


class TCPSyslogServer(Thread, ThreadingTCPServer):
    """ TCP syslog server thread. """

    def __init__(self, hostnames, logfile_name=None, port=None, accumulated=None):
        Thread.__init__(self)
        self.allow_reuse_address = True
        self.daemon = True
        if port is None:
            port = 514
        ThreadingTCPServer.__init__(self, ('', port), TCPSyslogHandler)
        self.hostnames = hostnames
        if logfile_name is None:
            logfile_name = 'syslog-%s'
        self.logfile_name = logfile_name
        self.logfiles = {}
        self.accumulated = accumulated

    def run(self):
        self.serve_forever(poll_interval=5)


class UDPSyslogServer(Thread, UDPServer):
    """ UDP syslog server thread. """

    def __init__(self, hostnames, logfile_name=None, port=None, accumulated=None):
        Thread.__init__(self)
        self.allow_reuse_address = True
        self.daemon = True
        if port is None:
            port = 514
        UDPServer.__init__(self, ('', port), UDPSyslogHandler)
        self.hostnames = hostnames
        if logfile_name is None:
            logfile_name = 'syslog-%s'
        self.logfile_name = logfile_name
        self.logfiles = {}
        self.accumulated = accumulated

    def run(self):
        self.serve_forever()


def syslog_server(hosts, port=None, logfile_name=None, acc_name=None):
    """ Start TCP + UDP syslog server. """

    hostnames = Hostnames()
    for host in hosts:
        hostnames.add(host)

    acc_file = None
    if acc_name:
        acc_file = open(acc_name, 'a')

    tcpSyslogServer = TCPSyslogServer(hostnames, port=port,
                                      logfile_name=logfile_name,
                                      accumulated=acc_file)
    udpSyslogServer = UDPSyslogServer(hostnames, port=port,
                                      logfile_name=logfile_name,
                                      accumulated=acc_file)
    tcpSyslogServer.start()
    udpSyslogServer.start()


if __name__ == '__main__':
    import signal
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('host', nargs='+')
    parser.add_argument('--port', type=int)
    parser.add_argument('--logfile-name')
    args = parser.parse_args()

    syslog_server(args.host, port=args.port, logfile_name=args.logfile_name)
    signal.pause()
