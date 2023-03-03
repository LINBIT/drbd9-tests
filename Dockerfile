FROM ubuntu:jammy

ARG LBPYTEST_VERSION=0.3.0

RUN apt-get update && apt-get -y install \
    python3 \
    python3-pip \
    openssh-client

RUN pip3 install lbpytest==${LBPYTEST_VERSION}

# Python 3.7+ automatically sets the environment variable 'LC_CTYPE=C.UTF-8'
# (PEP 538). The default SSH config in the base image causes LC_* to be passed
# to the remote. Older distributions (CentOS 7) do not support this LC_CTYPE,
# so they emit warnings. Do not send this unsupported environment variable.
RUN sed -i /SendEnv/d /etc/ssh/ssh_config

RUN mkdir -p /drbd-tests
COPY docker/entry.sh /

ENV TEST_NAME=
ENV TARGETS=

WORKDIR /drbd-tests

ENTRYPOINT [ "/entry.sh" ]
