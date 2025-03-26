from .drbdtest import log


def read_md5sum(node, filename, size_mb):
    count_arg = ''
    if size_mb:
        count_arg = 'count={}'.format(size_mb)

    return node.run(['/bin/bash', '-c', 'set -o pipefail ; dd if={} bs=1M iflag=direct {} | md5sum'
        .format(filename, count_arg)],
        return_stdout=True)


def verify_data(nodes, size_mb=None, backing_disk=False):
    """ Verify that DRBD devices contain the same data. """

    log('* Validate data is same on nodes {}'.format(nodes))

    if backing_disk and size_mb is None:
        raise RuntimeError('verifying data on backing disk requires explicit size')

    md5sums=[]
    for n in nodes:
        filename = n.volumes[0].disk if backing_disk else n.volumes[0].device()

        if n.host.drbd_version_tuple < (9, 0, 0) and not backing_disk:
            n.primary()
            md5sums.append(read_md5sum(n, filename, size_mb))
            n.secondary()
        else:
            md5sums.append(read_md5sum(n, filename, size_mb))

    if len(set(md5sums)) > 1:
        log(md5sums)
        raise RuntimeError("Data differs!")
