from .drbdtest import log


def verify_data(nodes, size_mb=None, backing_disk=False):
    """ Verify that DRBD devices contain the same data. """

    log('* Validate data is same on nodes {}'.format(nodes))

    count_arg = ''
    if size_mb:
        count_arg = 'count={}'.format(size_mb)
    elif backing_disk:
        raise RuntimeError('verifying data on backing disk requires explicit size')

    md5sums=[]
    for n in nodes:
        md5sum = n.run(['/bin/bash', '-c', 'dd if={} bs=1M iflag=direct {} | md5sum'
            .format(n.volumes[0].disk if backing_disk else n.volumes[0].device(), count_arg)],
            return_stdout=True)
        md5sums.append(md5sum)

    if len(set(md5sums)) > 1:
        log(md5sums)
        raise RuntimeError("Data differs!")
