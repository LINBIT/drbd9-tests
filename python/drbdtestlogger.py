import sys

# stream to write output to
logstream = None

debug_level = 0

class Tee(object):
    """
    replicates writes to streams
    """

    def __init__(self):
        self.streams = set()

    def add(self, stream):
        # Do not modify self.streams in place. Another thread may be iterating over it.
        streams = set(self.streams)
        streams.add(stream)
        self.streams = streams

    def remove(self, stream):
        # Do not modify self.streams in place. Another thread may be iterating over it.
        streams = set(self.streams)
        streams.remove(stream)
        self.streams = streams

    def write(self, message):
        for stream in self.streams:
            stream.write(message)

    def flush(self):
        for stream in self.streams:
            stream.flush()

def open_logstream(fname):
    logfile = open(fname, 'w', encoding='utf-8')
    # no need to close logfile - it is kept open until the program terminates
    global logstream
    logstream = Tee()
    logstream.add(sys.stderr)
    logstream.add(logfile)

def log(*args, **kwargs):
    """ Print message to stderr """
    print(*args, file=logstream)
    logstream.flush()

def debug(*args, **kwargs):
    """ Print debug message according to configured debug level. """

    level = 1
    try:
        level = kwargs.pop('level')
    except:
        pass
    if level <= debug_level:
        print(*args, file=logstream)

def set_debug_level(level):
    global debug_level
    debug_level = level
