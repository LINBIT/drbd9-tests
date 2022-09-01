#!/usr/bin/python3

import os
import json
import argparse


tests_dir = 'tests'
vmshed_prefix = '### vmshed: '
output_header = 'virter/tests.header.toml'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--selection', choices=['all', 'ci'], default='all',
            help='which selection of tests to generate (default "all")')
    parser.add_argument('--drbd-version', help='only output tests for this DRBD version')
    parser.add_argument('--drbd-version-other', help='only output tests also supported by this DRBD version')
    parser.add_argument('--default-variants', default=['tcp', 'rdma'], type=str, nargs='+',
                        help='which variants to add to tests that do not specify their own')
    args = parser.parse_args()

    drbd_version = parse_version(args.drbd_version) if args.drbd_version else None
    drbd_version_other = parse_version(args.drbd_version_other) if args.drbd_version_other else None

    if drbd_version_other is None:
        drbd_version_lower = drbd_version
    elif drbd_version is None:
        drbd_version_lower = drbd_version_other
    else:
        # Naive element by element comparison is good enough here
        drbd_version_lower = min(drbd_version, drbd_version_other)

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
        if vms is None:
            continue

        if drbd_version_lower is not None and drbd_version_lower < [9]:
            vms = [x for x in vms if x <= 2]

        if len(vms) == 0:
            continue

        drbd_version_min_str = vmshed_config.get('drbd_version_min')
        if drbd_version_lower is not None and drbd_version_min_str is not None:
            drbd_version_min = parse_version(drbd_version_min_str)
            # Naive element by element comparison is good enough here
            if drbd_version_lower < drbd_version_min:
                continue

        print('[tests.{}]'.format(name))
        print('vms = {}'.format(vms))

        vm_tags = vmshed_config.get('vm_tags')
        if vm_tags:
            # Python string formatting is compatible with toml
            print('vm_tags = {}'.format(vm_tags))

        variants = vmshed_config.get('variants', args.default_variants)
        print('variants = {}'.format(variants))

        samevms = vmshed_config.get('samevms')
        if samevms:
            print('samevms = true')

        for network in vmshed_config.get('networks', []):
            print('[[tests.{}.networks]]'.format(name))
            print('forward = "{}"'.format(network.get('forward', '')))
            print('domain = "{}"'.format(network.get('domain', '')))
            print('dhcp = {}'.format('true' if network.get('dhcp') else 'false'))

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
