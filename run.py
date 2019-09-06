#!/usr/bin/python3

import subprocess
import argparse
import time
import json
import sys
import re
import os

GREEN='\033[32m'
RED='\033[91m'
WHITE='\033[97m'
NORMAL='\033[0m'
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
    cmds = [ 'drbdsetup down all',
             'rmmod drbd_transport_tcp || true',
             'rmmod drbd || true',
             'insmod /lib/modules/$(uname -r)/updates/drbd.ko',
             'insmod /lib/modules/$(uname -r)/updates/drbd_transport_tcp.ko' ]

    print(CR + "Preparing %s" % (vm), end='')
    sys.stdout.flush()
    for cmd in cmds:
        subprocess.run(['ssh', 'root@' + vm, cmd], stderr=subprocess.DEVNULL, check=True)


def run_with_progress(args):
    n_chars = 10
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
            print(('%5.1f secs' % (now - start)) + (BS * n_chars), end='')
            sys.stdout.flush()
    print(' ' * n_chars + BS * n_chars, end='')
    sys.stdout.flush()
    p.wait()
    now = time.time()
    return p.returncode

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
            p = subprocess.run(['ssh', 'root@' + vm, 'lvremove %s' % (lv)], check=True)

def cleanup(original_lvs, all_vm_names):
    for vm in all_vm_names:
        remove_excess_LVs(original_lvs[vm], vm)

def main():
    original_lvs = {}

    cmdline_parser = argparse.ArgumentParser(
        description="run the testsuite's tests locally"
        )
    cmdline_parser.add_argument('vm_name', type=str, nargs='+',
                                help='name of VM that can be used to ssh into it')

    args = cmdline_parser.parse_args()
    all_vm_names = args.vm_name

    for vm in all_vm_names:
        original_lvs[vm] = list_LVs(vm)

    test_set_iter=stream_read_json('tests.drbd9.json')
    for test_set in test_set_iter:
        if len(all_vm_names) < test_set['vms']:
            continue
        vm_names = all_vm_names[:test_set['vms']]
        for test in test_set['tests']:
            for vm in vm_names:
                cleanup_and_prepare_vm(vm)
            print(CR + 'running %s on %s: ' %
                  (WHITE + test + NORMAL, ', '.join(vm_names)), end='')
            exit_code = run_with_progress(["tests/" + test, '-v' ,*vm_names])
            if exit_code == 0:
                print(GREEN + 'OKAY' + NORMAL)
            else:
                print(RED + 'FAILED' + NORMAL)
                cleanup(original_lvs, all_vm_names)
                exit(exit_code)


if __name__ == "__main__":
    main()
