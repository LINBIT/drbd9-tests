import os
import sys
import subprocess
import select

class SSH:
    """
    Class SSH serves as a wrapper for ssh ControlMaster connections. It manages
    exactly one connection and its corresponding ControlMaster socket.
    """

    def __init__(self, host, user='root', basedir='/tmp'):
        """
        The constructor immediately connects to a remote host and stores the
        ControlMaster socket in the local file system.

        :param host: the IP address or hostname of the host to connect to
        :param user: the username to log in as; defaults to 'root'
        :param basedir: the base directory where the ControlMaster socket will
            be stored; defaults to 'tmp'. The format of the file name is
            'controlmaster-$host', where $host is the host parameter
        """
        self.user = user
        self.host = host
        self.sockpath = os.path.join(basedir, 'controlmaster-'+host)
        subprocess.run(['ssh', '-S', self.sockpath, '-l', self.user,
            '-f', # Requests ssh to go to background just before command execution.
            '-N', # Do not execute a remote command.
            '-M', # Places the ssh client into "master" mode for connection sharing.
            self.host,
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    def close(self):
        """
        Close the ssh ControlMaster connection managed by this instance. If the
        connection is already closed, this is a no-op.
        """
        try:
            subprocess.run(['ssh', '-S', self.sockpath, '-O', 'exit', '_'],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            if e.returncode == 255:
                # socket not found, so it is probably already closed
                pass

    @staticmethod
    def inline_env(cmd, env):
        """
        Prepend environment variables to a command string.
        :param cmd: the original command string
        :param env: a dictionary containing the environment variables to be set
        :returns: a new command string that contains extra statements to export
            the environment variables before calling the command
        """
        parameters = " ".join(
            ["{}={}".format(k, v) for k, v in sorted(env.items())]
        )
        # NOTE: we actually need to use "export" here,
        # "{} {}".format(parameters, cmd) is not enough. This is because with
        # nontrivial shell statements like "command1 && command2", only command1
        # would actually have the variables set, but not command2.
        return "export {} && {}".format(parameters, cmd)

    def run(self, cmd_string, stdin=False, stdout=None, stderr=None, env=None):
        """
        Execute a command over the ssh ControMaster connection. The user is
        responsible for making sure that the ControlMaster connection is open
        before calling this function.

        :param cmd_string: the command to execute. This function does no further
            quoting or escaping to this string
        :param stdin: a file-like object that the process's standard input should
            be read from. This is expected to produce only UTF-8 encoded data.
            The special value "None" means that the parent process's standard
            input will be used. The special value "False" means that no standard
            input is needed; the process's stdin will be closed immediately
        :param stdout: a file-like object that the process's standard output stream
            should be written to. The called process is expected to produce only
            UTF-8 encoded data. The special value "None" means that the parent
            process's standard output will be used
        :param stderr: a file-like object that the process's standard error stream
            should be written to. The called process is expected to produce only
            UTF-8 encoded data. The special value "None" means that the parent
            process's standard error will be used
        :param env: a dictionary containing extra environment variables to be
            set before the command is executed. This function "inlines" the
            environment variables in the command string
        :returns: the called process's exit code, once it exits
        """
        stdout = stdout or sys.stdout
        stderr = stderr or sys.stderr
        if stdin is None:
            stdin = sys.stdin

        if env:
            cmd_string = self.inline_env(cmd_string, env)

        p = subprocess.Popen(['ssh', '-S', self.sockpath, '_', cmd_string],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)

        dest = { p.stdout: stdout, p.stderr: stderr }

        if stdin:
            p.stdin.write(stdin.read().encode('utf-8'))
        p.stdin.close()

        def check_io():
            ready_to_read = select.select([p.stdout, p.stderr], [], [], 1000)[0]
            for stream in ready_to_read:
                dest[stream].write(stream.read(select.PIPE_BUF).decode('utf-8'))

        while p.poll() is None:
            check_io()

        check_io() # check again to catch anything after the process exits

        return p.wait()
