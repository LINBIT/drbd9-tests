FROM ubuntu:bionic

RUN apt-get update && apt-get -y install \
    wget \
    build-essential \
    autoconf \
    libpcre3-dev \
    python3 \
    python3-distutils \
    openssh-client

# install logscan
RUN wget https://github.com/LINBIT/logscan/archive/master.tar.gz && \
    tar xvf master.tar.gz && \
    cd logscan-master && \
    ./bootstrap && \
    ./configure && \
    make && \
    make install && \
    cd / && rm -rf logscan-master master.tar.gz

RUN mkdir -p /drbd-tests
COPY . /drbd-tests
COPY docker/entry.sh /

ENV TEST_NAME=
ENV TARGETS=

WORKDIR /drbd-tests

ENTRYPOINT [ "/entry.sh" ]
