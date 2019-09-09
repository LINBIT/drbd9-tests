#!/usr/bin/python3

import subprocess
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


def cleanup_and_prepare_vm(vm):
    cmds = [ 'drbdsetup down all 2>/dev/null',
             'rmmod drbd_transport_tcp 2>/dev/null || true',
             'rmmod drbd 2>/dev/null || true',
             'insmod /lib/modules/$(uname -r)/updates/drbd.ko',
             'insmod /lib/modules/$(uname -r)/updates/drbd_transport_tcp.ko' ]

    for cmd in cmds:
        subprocess.run(['ssh', 'root@' + vm, cmd], check=True)


def run_with_progress(args):
    N_CHARS = 10
    start = time.time()
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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
    now = time.time()
    return {'exit_code': p.returncode, 'run_time': now - start}

def list_LVs(vm):
    p = subprocess.run(['ssh', 'root@' + vm, 'lvs --noheadings -o lv_path'],
                       check=True, stdout=subprocess.PIPE)
    lvs = [lv.strip() for lv in p.stdout.decode('utf-8').splitlines()]
    return lvs

def remove_excess_LVs(orig_lvs, vm):
    lvs = list_LVs(vm)
    for lv in lvs:
        if not lv in orig_lvs:
            cleanup_and_prepare_vm(vm)
            subprocess.run(['ssh', 'root@' + vm, 'lvremove -f %s' % (lv)], check=True)

def cleanup(original_lvs, all_vm_names):
    for vm in all_vm_names:
        remove_excess_LVs(original_lvs[vm], vm)

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

    for n in iter(test_sets):
        result = {}
        result['vms'] = n
        result['tests'] = test_sets[n]
        yield result

def run_tests(test_set_iter, all_vm_names, exclude_tests):
    original_lvs = {}
    results = {}

    for vm in all_vm_names:
        original_lvs[vm] = list_LVs(vm)

    for test_set in test_set_iter:
        if len(all_vm_names) < test_set['vms']:
            continue
        vm_names = all_vm_names[:test_set['vms']]
        for test in test_set['tests']:
            if test in exclude_tests:
                continue
            for vm in vm_names:
                print(CR + "Preparing %s" % (vm), end='')
                cleanup_and_prepare_vm(vm)
            print(CR + 'running %s on %s: ' %
                  (WHITE + test + NORMAL, ', '.join(vm_names)), end='')
            result = run_with_progress(["tests/" + test, '-v', '--cleanup=always', *vm_names])
            result['nodes'] = len(vm_names)
            results[test] = result
            exit_code = result.get('exit_code')
            if exit_code == 0:
                print(GREEN + 'OKAY' + NORMAL)
            else:
                print(RED + 'FAILED' + NORMAL)
                cleanup(original_lvs, all_vm_names)
                return (exit_code, results)

    return (0, results)

def collect_software_versions(vm):
    cleanup_and_prepare_vm(vm)
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

    args = cmdline_parser.parse_args()
    all_vm_names = args.vm_name

    (kern_ver, drbd_ver, drbd_git) = collect_software_versions(all_vm_names[0])

    if args.run:
        test_set_iter=generate_test_set(args.run, len(all_vm_names))
    else:
        test_set_iter=stream_read_json(args.test_set_file)

    try:
        f = open('result_db.json', 'r')
        result_db = json.load(f)
    except FileNotFoundError:
        result_db = []

    (exit_code, results) = run_tests(test_set_iter, all_vm_names, args.exclude)

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