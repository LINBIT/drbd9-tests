#!/usr/bin/env python3

import argparse
import itertools
import signal
import sys


def signal_handler(signum, frame):
    pass


def main():
    parser = argparse.ArgumentParser(description='Allocate memory and wait')
    parser.add_argument('--alloc-kib', type=int, default=200*(2**10))
    args = parser.parse_args()

    print('Allocate', file=sys.stderr)
    # Create one "bytearray" and copy it.
    # This is faster than allocating a single "bytes".
    chunk_kib = 64
    chunk_size = chunk_kib * 1024
    chunk_count = args.alloc_kib // chunk_kib
    first_chunk = bytearray(itertools.repeat(ord('a'), chunk_size))
    data = [first_chunk] + [bytearray(first_chunk) for _ in range(chunk_count - 1)]

    print('Wait', file=sys.stderr)
    signal.signal(signal.SIGINT, signal_handler)
    signal.pause()

    # Do something with "data" to reduce the likelihood that it is optimized away
    # by a future version of the Python interpreter.
    print(sum([len(chunk) for chunk in data]), file=sys.stderr)


if __name__ == "__main__":
    main()
