FROM ubuntu:jammy

ARG LBPYTEST_VERSION=0.3.0

RUN apt-get update && apt-get -y install \
    python3 \
    python3-pip \
    openssh-client

RUN pip3 install lbpytest==${LBPYTEST_VERSION}

RUN mkdir -p /drbd-tests
COPY docker/entry.sh /

ENV TEST_NAME=
ENV TARGETS=

WORKDIR /drbd-tests

ENTRYPOINT [ "/entry.sh" ]
