# DRBD 9 Test Suite

This mainly is a test suite for version 9 of DRBD.  Some of the tests are
compatible with version 8 of DRBD as well, though.

The basic architecture of the test suite consists of a coordinator node and a
number of target nodes.  The test coordinator first opens ssh connections to
each of the target nodes to send the target nodes commands and collect results.
Then it prepares the target nodes for the actual test by creating test volumes
and a drbd configuration.  Once that is done, it sends the test nodes a series
of commands as defined by the test case, and waits for specific changes to
occur.  For example, it can tell the test cluster to bring itself up, and wait
until all nodes are fully connected.  All the test results are collected on the
coordinator.  Finally, when a test ends, it attempts to clean up any changes
made on the target nodes.

The test scripts themselves are python scripts.


## Requirements

Running the test suite requires the following components:

 * One test coordinator node.  The basic test infrastructure can be run as an
   unprivileged user.

 * Typically two or more nodes to use as the test cluster.  The nodes must be
   accessible over ssh without password prompt. (This is best configured by
   putting the ssh public key of the user running the test suite into
   `~root/.ssh/authorized_keys` on each test node.)

 * The DRBD 9 kernel module and user-space utilities must be installed on all
   test nodes.

 * `iptables` on all test nodes.

 * For some tests, [fio](https://github.com/axboe/fio), the "Flexible I/O
   Tester".

 * On each test node, all test volumes are currently created inside an LVM
   volume group called `scratch`.  (The volume group name can be overridden
   with the `--volume-group=<name>` option.)


## Individual Test Runs

Each individual test run is assigned a job name which consists of the base name
of the test, with a timestamp appended: the `tests/connect` script would log
into directory `log/connect-20131015-173644/`, for example.  The following
files can be found in the log directory:

 * `drbd.conf`: the DRBD configuration file used on all nodes.

 * `events-<node-name>`: The output of `drbdsetup events` on each node.  These
   event traces are used for checking for state transitions.

 * `test.log`: The output of the test script (everything written to `logstream`,
   including messages logged by calling the `log` function).

 * `dmesg-<node-name>`: The dmesg log of each node.

 * `console-<node-name>`: the serial console output of each node (if the
   `--vconsole` option is used).


The most important options supported by the test scripts are:

 * Positional arguments: The names of the test nodes.
   Depending on the test, one, two, or more nodes are required.

 * `--debug`: Include some information for debugging the test suite.


## Serial Consoles

Logging the serial console output of virtual machines running on the test
coordinator is supported via the `--vconsole` option.  This requires that the
virtual machine is visible by the current user in `virsh`.  The name of the
virtual machine must be the same as the name used for accessing the node via
ssh.


## Examples

```
tests/connect tick trick track
```


## GitLab

See [doc/gitlab.md](./doc/gitlab.md) for more information about test automation
in GitLab including the different forms of testing which are used.
