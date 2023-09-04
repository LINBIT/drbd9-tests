#!/usr/bin/python3

import os
import json
import argparse


vmshed_prefix = '### vmshed: '
variants_toml = 'virter/variants.toml'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tests-dir', default='tests',
            help='directory containing test scripts')
    parser.add_argument('--selection', choices=['all', 'ci'], default='all',
            help='which selection of tests to generate (default "all")')
    parser.add_argument('--drbd-version', help='only output tests for this DRBD version')
    parser.add_argument('--drbd-version-other', help='only output tests also supported by this DRBD version')
    parser.add_argument('--default-variants', default=['tcp', 'rdma', 'second_is_other'], type=str, nargs='+',
                        help='which variants to add to tests that do not specify their own')
    parser.add_argument('--test-timeout', default='5m',
                        help='test timeout in Golang duration format (default "5m")')
    args = parser.parse_args()

    drbd_version = parse_version(args.drbd_version) if args.drbd_version else None
    drbd_version_other = parse_version(args.drbd_version_other) if args.drbd_version_other else None

    if drbd_version_other is None:
        drbd_version_lower = drbd_version
    elif drbd_version is None:
        drbd_version_lower = drbd_version_other
    else:
        if is_lower(drbd_version, drbd_version_other):
            drbd_version_lower = drbd_version
        else:
            drbd_version_lower = drbd_version_other

    # Read test files
    test_configs = []
    for name in os.listdir(args.tests_dir):
        filepath = args.tests_dir + '/' + name
        if not os.path.isfile(filepath):
            continue

        vmshed_config = read_vmshed_json(filepath)
        if vmshed_config is None:
            raise RuntimeError('no "{}" line found in "{}"'.format(vmshed_prefix, filepath))

        vms = vmshed_config.get('vms_all')
        if vms is None or len(vms) == 0:
            raise RuntimeError('no "vms_all" configured for "{}"'.format(filepath))

        test_configs.append((name, vmshed_config))

    # Write header
    print('test_suite_file = "run.toml"')
    print('test_timeout = "{}"'.format(args.test_timeout))
    print('artifacts = ["/gcov.tar.gz"]')
    print()
    with open(variants_toml) as f:
        print(f.read().rstrip())
    print()
    print('[tests]')

    # Write tests
    for name, vmshed_config in sorted(test_configs, key=lambda a: a[0]):
        vms_key = 'vms_all' if args.selection == 'all' else 'vms_ci'
        vms = vmshed_config.get(vms_key)
        if vms is None:
            continue

        if drbd_version_lower is not None and drbd_version_lower < [9]:
            vms = [x for x in vms if x <= 2]

        if len(vms) == 0:
            continue

        drbd_version_min_str = vmshed_config.get('drbd_version_min')
        if drbd_version_lower is not None and drbd_version_min_str is not None:
            drbd_version_min = parse_version(drbd_version_min_str)
            if is_lower(drbd_version_lower, drbd_version_min):
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


def is_lower(version, min_version):
    for i, _ in enumerate(min_version):
        if i >= len(version):
            # a longer list is always "greater" than a shorter one (if all elements so far are equal)
            return True
        if version[i] == '*':
            return False
        if version[i] < min_version[i]:
            return True
        elif version[i] > min_version[i]:
            return False
    return len(version) < len(min_version)


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
