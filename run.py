#!/usr/bin/python3

import subprocess
import signal
from subprocess import CalledProcessError, TimeoutExpired
from threading import Timer
import argparse
import pathlib
import time
import json
import sys
import re
import os

NORMAL='\033[0m'
GREEN='\033[32m'
WHITE='\033[97m'
RED='\033[91m'
BS='\010'
CR='\015'

def stream_read_json(file_name):
    start_pos = 0
    with open(file_name, 'r') as f:
        while True:
            try:
                obj = json.load(f)
                yield obj
                return
#            except json.JSONDecodeError as e:
#                f.seek(start_pos)
#                json_str = f.read(e.pos)
#                obj = json.loads(json_str)
#                start_pos += e.pos
#                yield obj
            except ValueError as e:
                f.seek(start_pos)
                end_pos = int(re.match('Extra data: line \d+ column \d+ .*\(char (\d+).*\)',
                                    e.args[0]).groups()[0])
                json_str = f.read(end_pos)
                obj = json.loads(json_str)
                start_pos += end_pos
                yield obj

def drbdsetup_down(vm):
    cmd = 'drbdsetup down all'
    args = ['ssh', 'root@' + vm, cmd]
    subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30)

def unmount_dev(vm, dev):
    cmd = 'umount ' + dev
    args = ['ssh', 'root@' + vm, cmd]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate()
    if p.returncode != 0:
        raise Exception(stderr)

def is_process_running(vm, pid):
    cmd = 'test -d /proc/' + pid
    args = ['ssh', 'root@' + vm, cmd]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.communicate()
    return p.returncode == 0

def kill_process(vm, pid):
    cmd = 'kill -9 ' + pid
    args = ['ssh', 'root@' + vm, cmd]

    attempt = 0
    last_stderr = ''
    while attempt < 3:
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        if not is_process_running(vm, pid):
            break
        print('  Process was not killed on attempt {0}, retrying'.format(attempt+1))
        attempt += 1
    else:
        raise Exception()

def kill_node(vm):
    cmd = '{ sleep 0.5; echo b > /proc/sysrq-trigger; } > /dev/null &'
    args = ['ssh', 'root@' + vm, cmd]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate()
    if p.returncode != 0:
        raise Exception(stderr)

def handle_down_error(vm, e):
    """
    handle an error produced by 'drbdsetup down'
    """
    if e.returncode == 11:
        # held open by someone
        regexPid = r'^(.*) opened by (.*) \(pid (\d*)\) at .*$'
        r = re.search(regexPid, str(e.stderr))
        dev = r.group(1)
        procname = r.group(2)
        pid = r.group(3)
        # special case: if 'mount' is holding the device open, we need to unmount it
        if procname == 'mount':
            print('  Device is mounted, unmounting {0}'.format(dev))
            unmount_dev(vm, dev)
        else:
            print('  Device is being held open, killing {0} (pid {1})'.format(procname, pid))
            kill_process(vm, pid)
    else:
        raise Exception('Unknown drbdsetup down exception: {0}'.format(e))

    # let's try this again...
    drbdsetup_down(vm)

def try_down_all(vm, all_vm_names):
    try:
        drbdsetup_down(vm)
    except TimeoutExpired as e:
        print('  drbdsetup down is not responding, killing all nodes')
        try:
            for node in all_vm_names:
                kill_node(node)
        except Exception as e:
            print('  sysrq-trigger failed, cannot continue')
            raise e
    except CalledProcessError as e:
        try:
            handle_down_error(vm, e)
        except Exception as e:
            print('  Could not handle error, rebooting all nodes')
            print(e)
            try:
                for node in all_vm_names:
                    kill_node(node)
            except Exception as e:
                print('  sysrq-trigger failed, cannot continue')
                raise e

def cleanup_and_prepare_vm(vm, all_vm_names, parallel=False):
    try_down_all(vm, all_vm_names)
    cmd = """
rmmod drbd_transport_tcp 2>/dev/null || true
rmmod drbd 2>/dev/null || true
modprobe crc32c
UNR=$(uname -r)
if test -e /lib/modules/$UNR/updates/drbd.ko; then
    insmod /lib/modules/$UNR/updates/drbd.ko
    insmod /lib/modules/$UNR/updates/drbd_transport_tcp.ko
elif test -e /lib/modules/$UNR/extra/drbd/drbd.ko; then
    insmod /lib/modules/$UNR/extra/drbd/drbd.ko
    insmod /lib/modules/$UNR/extra/drbd/drbd_transport_tcp.ko
else
    echo "drbd.ko is in an unknown location, cannot load"
    exit 1
fi
"""
    p = subprocess.Popen(['ssh', 'root@' + vm, cmd])
    if not parallel:
        p.wait()
        if p.returncode != 0:
            raise subprocess.CalledProcessError(p.returncode, 'ssh')

    return p

def cleanup_and_prepare_vms(vm_names):
    processes = []

    print("Preparing", end='')
    for vm in vm_names:
        print(" %s" % (vm), end='')
        processes.append(cleanup_and_prepare_vm(vm, vm_names, parallel=True))
    sys.stdout.flush()

    for p in processes:
        p.wait()
        if p.returncode != 0:
            raise subprocess.CalledProcessError(p.returncode, 'ssh')

def run_with_progress(args):
    N_CHARS = 10
    TIMEOUT_SEC = 5*60 # 5 minutes
    start = time.time()
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, preexec_fn=os.setsid)

    timeout = False
    def do_timeout():
        nonlocal timeout
        os.killpg(p.pid, signal.SIGKILL)
        timeout = True
    timer = Timer(TIMEOUT_SEC, do_timeout)
    timer.start()
    now = start
    while True:
        before = now
        line = p.stdout.readline()
        now = time.time()
        if not line:
            break
        if now - before > 0.1:  # 100ms since last update
            print(('%5.1f secs' % (now - start)) + (BS * N_CHARS), end='')
            sys.stdout.flush()
    print(' ' * N_CHARS + BS * N_CHARS, end='')
    sys.stdout.flush()
    p.wait()
    timer.cancel()
    now = time.time()
    return {'exit_code': p.returncode, 'run_time': now - start, 'timeout': timeout}

def list_LVs(vm):
    p = subprocess.run(['ssh', 'root@' + vm, 'lvs --noheadings -o lv_path'],
                       check=True, stdout=subprocess.PIPE)
    lvs = [lv.strip() for lv in p.stdout.decode('utf-8').splitlines()]
    return lvs

def remove_excess_LVs(orig_lvs, vm, all_vm_names):
    lvs = list_LVs(vm)
    for lv in lvs:
        if not lv in orig_lvs:
            cleanup_and_prepare_vm(vm, all_vm_names)
            subprocess.run(['ssh', 'root@' + vm, 'lvremove -f %s' % (lv)], check=True)

def cleanup(original_lvs, all_vm_names):
    for vm in all_vm_names:
        remove_excess_LVs(original_lvs[vm], vm, all_vm_names)

def generate_test_set(tests, n_vms):
    test_sets = {}
    if not test_sets:
        for test in tests:
            p = subprocess.run(["tests/" + test, '--report-and-quit'],
                               stdout=subprocess.PIPE, check=True)
            [min_nodes_str, max_nodes_str] = p.stdout.decode('utf-8').splitlines()
            min_nodes = int(re.findall(r'min_nodes=(\d+)', min_nodes_str)[0])
            max_nodes = int(re.findall(r'max_nodes=(\d+)', max_nodes_str)[0])
            if n_vms >= min_nodes:
                use_vms = min(n_vms, max_nodes)
                if use_vms in test_sets:
                    test_sets[use_vms].append(test)
                else:
                    test_sets[use_vms] = [test]
            else:
                print("Can not run %s with %d VMs, need %d at minimum" %
                      (WHITE + test + NORMAL, n_vms, min_nodes))

    for n in iter(test_sets):
        result = {}
        result['vms'] = n
        result['tests'] = test_sets[n]
        yield result

def run_tests(test_set_iter, all_vm_names, exclude_tests, keep_going):
    original_lvs = {}
    results = {}
    global_exit_code = 0

    for vm in all_vm_names:
        original_lvs[vm] = list_LVs(vm)

    for test_set in test_set_iter:
        if len(all_vm_names) < test_set['vms']:
            continue
        vm_names = all_vm_names[:test_set['vms']]
        for test in test_set['tests']:
            if test in exclude_tests:
                continue
            cleanup_and_prepare_vms(vm_names)
            print(CR + 'running %s on %s: ' %
                  (WHITE + test + NORMAL, ', '.join(vm_names)), end='')
            result = run_with_progress(["tests/" + test, '-v', '--cleanup=always', *vm_names])
            result['nodes'] = len(vm_names)
            results[test] = result
            exit_code = result.get('exit_code')
            timeout = result.get('timeout')
            if timeout:
                print(RED + 'TIMEOUT' + NORMAL)
                cleanup(original_lvs, all_vm_names)
                if keep_going:
                    # just return 1 for now
                    global_exit_code = 1
                else:
                    return (exit_code, results)
            else:
                if exit_code == 0:
                    print(GREEN + 'OKAY' + NORMAL)
                else:
                    print(RED + 'FAILED' + NORMAL)
                    cleanup(original_lvs, all_vm_names)
                    if keep_going:
                        # just return 1 for now
                        global_exit_code = 1
                    else:
                        return (exit_code, results)

    return (global_exit_code, results)

def collect_software_versions(all_vm_names):
    vm = all_vm_names[0]
    cleanup_and_prepare_vm(vm, all_vm_names)
    p = subprocess.run(['ssh', 'root@' + vm, 'uname -r; cat /proc/drbd'],
                       check=True, stdout=subprocess.PIPE)
    s = p.stdout.decode('utf-8')
    [(kern_ver, drbd_ver, drbd_git)] = re.findall(
        r'([^\s]+)\nversion: ([\d\.-]+)[^G]*GIT-hash: ([0-9a-f]+)', s)
    return ( kern_ver, drbd_ver, drbd_git)

def main():
    cmdline_parser = argparse.ArgumentParser(
        description="run the testsuite's tests locally"
        )
    cmdline_parser.add_argument('vm_name', type=str, nargs='+',
                                help='name of VM/host that can be used to ssh into it')
    cmdline_parser.add_argument('-f', '--test-set-file', type=pathlib.Path,
                                dest='test_set_file', default='tests.drbd9.json',
                                metavar="FILE", help='JSON stream file to read the test set')
    cmdline_parser.add_argument('-n', '--not', type=str, metavar="TEST_NAME", nargs='*',
                                dest='exclude', help='exclude these tests', default=[])
    cmdline_parser.add_argument('-r', '--run', type=str, metavar="TEST_NAME", nargs='*',
                                dest='run', help='run only these named tests', default=[])
    cmdline_parser.add_argument('-k', '--keep-going', action='store_true', dest='keep_going',
                                help='keep going even after a test fails', default=False)

    args = cmdline_parser.parse_args()
    all_vm_names = args.vm_name

    (kern_ver, drbd_ver, drbd_git) = collect_software_versions(all_vm_names)

    if args.run:
        test_set_iter=generate_test_set(args.run, len(all_vm_names))
    else:
        test_set_iter=stream_read_json(args.test_set_file)

    try:
        f = open('result_db.json', 'r')
        result_db = json.load(f)
    except FileNotFoundError:
        result_db = []

    (exit_code, results) = run_tests(test_set_iter, all_vm_names, args.exclude, args.keep_going)

    result_db.append({
        'version': drbd_ver,
        'git_hash': drbd_git,
        'kernel': kern_ver,
        'date_time': time.strftime("%Y%m%d-%H%M%S"),
        'results': results})

    with open('result_db.json', 'w') as f:
        json.dump(result_db, f)

    return exit_code

if __name__ == "__main__":
    main()
