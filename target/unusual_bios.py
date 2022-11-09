#!/usr/bin/env python3

from __future__ import division, print_function

import sys, os
import ctypes
from ctypes.util import find_library

#ifndef BLKDISCARD
# define BLKDISCARD	_IO(0x12,119)
#endif
#ifndef BLKSECDISCARD
# define BLKSECDISCARD	_IO(0x12,125)
#endif
#ifndef BLKZEROOUT
# define BLKZEROOUT	_IO(0x12,127)
#endif
#uint64_t end, blksize, step, range[2]

BLKDISCARD = (0x12 << 8) + 119
BLKSECDISCARD = (0x12 << 8) + 125
BLKZEROUT = (0x12 << 8) + 127

class IOCTL_range(ctypes.Structure):
    _fields_ = [("start", ctypes.c_ulonglong),
                ("end", ctypes.c_ulonglong)]

libc = ctypes.CDLL(find_library('c'), use_errno=True)

def ioctl(fd, request, ioctl_range, name):
    n = libc.ioctl(fd, request, ctypes.byref(ioctl_range))
    if n != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, "libc.ioctl(%d, 0x%x (%s), ...): %s" % (
            fd, request, name, os.strerror(errno)))
    return n

def main():
    # 128KiB - a multiple of discard_granularity
    size = 128 * 1024

    if len(sys.argv) > 2:
        size = int(sys.argv[2])

    fd = os.open(sys.argv[1], os.O_RDWR | os.O_DIRECT)
    # will raise an exception if open fails

    ioctl(fd, BLKZEROUT,     IOCTL_range(0 * size, 1 * size), "BLKZEROUT")
    ioctl(fd, BLKDISCARD,    IOCTL_range(1 * size, 2 * size), "BLKDISCARD")
    # The backing disk in the test infrastructure does not support BLKSECDISCARD.
    #ioctl(fd, BLKSECDISCARD, IOCTL_range(4 * size, 3 * size), "BLKSECDISCARD")

    os.close(fd)


if __name__ == "__main__":
    main()
