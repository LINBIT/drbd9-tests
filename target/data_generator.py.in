#!/usr/bin/env python3

import argparse
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--label', help='label to repeat in output', default='A')
parser.add_argument('--bytes', help='number of bytes to generate (rounded down to multiple of 16)', type=int, default=4096)
args = parser.parse_args()

label_bytes = (args.label.encode('utf-8') * 8)[:8]

for i in range(args.bytes // 16):
    sys.stdout.buffer.write(label_bytes)
    sys.stdout.buffer.write(i.to_bytes(8, byteorder='big'))
