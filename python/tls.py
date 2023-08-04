import datetime
import io
from typing import Optional

from OpenSSL import crypto

TLSHD_CONFIG = '''
[debug]
loglevel=10
tls=10

[authenticate.client]
x509.truststore=/etc/tlshd.d/ca.crt
x509.certificate=/etc/tlshd.d/tls.crt
x509.private_key=/etc/tlshd.d/tls.key

[authenticate.server]
x509.truststore=/etc/tlshd.d/ca.crt
x509.certificate=/etc/tlshd.d/tls.crt
x509.private_key=/etc/tlshd.d/tls.key
'''


def _gen_key() -> crypto.PKey:
    """Generate a 2048 bit RSA key"""
    cakey = crypto.PKey()
    cakey.generate_key(crypto.TYPE_RSA, 2048)
    return cakey


def _gen_cert(now: datetime.datetime, pubkey: crypto.PKey, common_name: str, issuer: Optional[crypto.X509Name],
              signer: crypto.PKey) -> crypto.X509:
    """
    Generate a certificate signed by the given issuer.

    If no issuer is given, the certificate is self-signed, in this case signer should be the same as pubkey.

    The certificate is valid for 1 day after 'now', and starting from one hour before 'now', to account for small
    differences in system clocks.
    """
    cert = crypto.X509()
    cert.get_subject().CN = common_name
    cert.set_notBefore(f"{now - datetime.timedelta(hours=1):%Y%m%d%H%M%S}Z".encode())
    cert.set_notAfter(f"{now + datetime.timedelta(days=1):%Y%m%d%H%M%S}Z".encode())
    if issuer:
        cert.set_issuer(issuer)
    else:
        cert.set_issuer(cert.get_subject())
    cert.set_pubkey(pubkey)
    cert.sign(signer, 'sha256')
    return cert


def setup_kernel_tls_helper(hosts):
    """
    Set up the kernel TLS handshake service on nodes.

    All hosts will use certificates from a single certificate authority, and all nodes will be configured to trust
    each other.
    """
    now = datetime.datetime.now()

    ca_key = _gen_key()
    ca_cert = _gen_cert(now, ca_key, "drbd9-tests", None, ca_key)

    for host in hosts:
        node_key = _gen_key()
        node_cert = _gen_cert(now, node_key, host.name, ca_cert.get_issuer(), ca_key)

        host.run(['mkdir', '-p', '/etc/tlshd.d'])
        host.run(['bash', '-c', 'cat > /etc/tlshd.conf'], stdin=io.StringIO(TLSHD_CONFIG))
        host.run(['bash', '-c', 'cat > /etc/tlshd.d/ca.crt'],
                 stdin=io.StringIO(crypto.dump_certificate(crypto.FILETYPE_PEM, ca_cert).decode()))
        host.run(['bash', '-c', 'cat > /etc/tlshd.d/tls.crt'],
                 stdin=io.StringIO(crypto.dump_certificate(crypto.FILETYPE_PEM, node_cert).decode()))
        host.run(['bash', '-c', 'cat > /etc/tlshd.d/tls.key'],
                 stdin=io.StringIO(crypto.dump_privatekey(crypto.FILETYPE_PEM, node_key).decode()))

        # Ignore errors here: the kernel may have the handshake module built in if it is new enough.
        host.run(['modprobe', 'handshake'], catch=True)
        host.run(['systemctl', 'restart', 'tlshd.service'])
