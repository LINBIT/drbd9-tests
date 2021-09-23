class BusyWrite(object):
    """ Keep DRBD device busy using 'fio'. """

    def __init__(self, volume):
        self._volume = volume
        self._node = volume.node
        self._fio_pid = None

    def start(self, fio_arg_str=''):
        """
        Start writing to DRBD device.

        fio-3.16 (default on Ubuntu Focal) has a bug affecting the combination
        of "size" and "offset". The effects vary depending on whether
        "time_based" is given. With "time_based" and "size == offset", fio
        writes from "offset" to the end of the device. This would allow the
        application IO from this job to finish an ongoing sync. This may not be
        desirable depending on the test case. Avoid using "offset".
        See https://bugs.launchpad.net/ubuntu/+source/fio/+bug/1891169

        Keyword arguments:
        fio_arg_str -- extra arguments to pass to fio
        """
        # run fio in background
        fio_cmd = ['setsid', 'bash', '-c',
                'fio --max-jobs=1 --name=test --filename={} --ioengine=libaio --rw=randwrite --direct=1 --iodepth=32 '.format(self._volume.device()) +
                '--time_based --runtime=600 {} < /dev/null &> /dev/null & echo $!'.format(fio_arg_str)]
        self._fio_pid = self._node.run(fio_cmd, return_stdout=True)

    def stop(self):
        if self._fio_pid is None:
            raise RuntimeError('Start first')

        self._node.run(['kill', str(self._fio_pid)])
        # wait for fio to terminate
        self._node.run(['tail', '--pid={}'.format(self._fio_pid), '-f', '/dev/null'])
        self._fio_pid = None
