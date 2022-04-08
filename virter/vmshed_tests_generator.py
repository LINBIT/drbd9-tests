#!/usr/bin/python3

import os
import subprocess
import json
import argparse
import sys


tests_dir = 'tests'
vmshed_prefix = '### vmshed: '
output_header = 'virter/tests.header.toml'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--selection', choices=['all', 'ci'], default='all',
            help='which selection of tests to generate (default "all")')
    parser.add_argument('--drbd-version', help='only output tests for this DRBD version')
    args = parser.parse_args()

    drbd_version = parse_version(args.drbd_version) if args.drbd_version else None

    # Read test files
    test_configs = []
    for name in os.listdir(tests_dir):
        filepath = tests_dir + '/' + name
        if not os.path.isfile(filepath):
            continue

        vmshed_config = read_vmshed_json(filepath)
        if vmshed_config is None:
            raise RuntimeError('no "{}" line found in "{}"'.format(vmshed_prefix, filepath))
            continue

        vms = vmshed_config.get('vms_all')
        if vms is None or len(vms) == 0:
            raise RuntimeError('no "vms_all" configured for "{}"'.format(filepath))

        test_configs.append((name, vmshed_config))

    # Write header
    with open(output_header) as f:
        print(f.read().rstrip())

    # Write tests
    for name, vmshed_config in sorted(test_configs, key=lambda a: a[0]):
        vms_key = 'vms_all' if args.selection == 'all' else 'vms_ci'
        vms = vmshed_config[vms_key]
        if vms is None or len(vms) == 0:
            continue

        drbd_version_min_str = vmshed_config.get('drbd_version_min')
        if drbd_version is not None and drbd_version_min_str is not None:
            drbd_version_min = parse_version(drbd_version_min_str)
            # Naive element by element comparison is good enough here
            if drbd_version < drbd_version_min:
                continue

        print('[tests.{}]'.format(name))
        print('vms = {}'.format(vms))

        samevms = vmshed_config.get('samevms')
        if samevms:
            print('samevms = true')

        print()

# Naive version parsing handling dot separated elements which are either integers or strings
def parse_version(version_str):
    return [int(element) if element.isdecimal() else element
            for element in version_str.split('.')]

def read_vmshed_json(filepath):
    with open(filepath) as f:
        for line in f:
            if not line.startswith(vmshed_prefix):
                continue
            json_str = line[len(vmshed_prefix):]
            return json.loads(json_str)
    return None


if __name__ == '__main__':
    main()