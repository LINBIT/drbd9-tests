import json
import os


class BusyWrite(object):
    """ Keep DRBD device busy using 'fio'. """

    def __init__(self, volume):
        self._volume = volume
        self._node = volume.node
        self._fio_pid = None
        self._fio_out_str = None

    def start(self, fio_arg_str='',
              fio_base_args='--rw=randwrite --direct=1 ' +
              '--iodepth=32 --time_based --runtime=600'):
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
        fio_base_args -- arguments to pass to fio; defaults to writing busily for a long time
        """
        self._output_filename = 'fio-{}-{}-async.json'.format(self._node.name, self._node.host.fio_count)

        # run fio in background
        fio_cmd = ['setsid', 'bash', '-c',
                'fio --output-format=json --max-jobs=16 --name=test --ioengine=libaio ' +
                '--filename={} '.format(self._volume.device()) +
                fio_base_args + ' ' + fio_arg_str +
                ' < /dev/null > /tmp/{} 2> /dev/null & echo $!'.format(self._output_filename)]
        self._fio_pid = self._node.run(fio_cmd, return_stdout=True)

        self._node.host.fio_count += 1

    def is_running(self):
        if self._fio_pid is None:
            return False

        running_str = self._node.run([
            'bash', '-c', 'ps -p {} > /dev/null && echo true || echo false'.format(self._fio_pid)],
            return_stdout=True)

        if running_str == 'true':
            return True
        if running_str == 'false':
            return False
        raise RuntimeError('unexpected output from running check: ' + running_str)

    def wait(self, timeout=None):
        """ Wait for fio to terminate and collect results. """
        self._node.run(['tail', '--pid={}'.format(self._fio_pid), '-f', '/dev/null'], timeout=timeout)
        self._fio_pid = None
        self._fio_out_str = self._node.run(['cat', '/tmp/{}'.format(self._output_filename)], return_stdout=True)
        # Some fio versions write non-json messages before the json output
        self._fio_out_str = self._fio_out_str[self._fio_out_str.find('{'):]
        with open(os.path.join(self._node.resource.cluster.logdir, self._output_filename), 'w') as output_file:
            output_file.write(self._fio_out_str)

    def kill_jobs(self):
        if self._fio_pid is None:
            raise RuntimeError('Start first')

        self._node.run(['bash', '-c', 'kill $(ps --ppid {} -o pid=)'.format(self._fio_pid)])

    def stop(self):
        if self._fio_pid is None:
            raise RuntimeError('Start first')

        self._node.run(['kill', str(self._fio_pid)])
        self.wait()

    def get_write_kib(self):
        if self._fio_out_str is None:
            raise RuntimeError('Wait for fio to stop first')
        fio_output = json.loads(self._fio_out_str)
        return fio_output['jobs'][0]['write']['io_kbytes']
