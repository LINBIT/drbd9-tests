#!/bin/bash

if [ -z "$TEST_NAME" ]; then
    echo "No test specified"
    exit 1
fi

if [ ! -e tests/"$TEST_NAME" ]; then
    echo "Unknown test '$TEST_NAME'"
    exit 1
fi

echo "===== Prepare SSH access"

mkdir -p /root/.ssh
echo "$SSH_PRIVATE_KEY" > /root/.ssh/id_rsa
chmod 600 /root/.ssh/id_rsa

nodes=()

IFS=,; for t in $TARGETS; do
    ssh-keyscan -H $t >> ~/.ssh/known_hosts

    t_host=$(ssh $t hostname -f)
    echo "=== Target $t => $t_host"
    echo "$t $t_host" >> /etc/hosts
    ssh-keyscan -H $t_host >> ~/.ssh/known_hosts
    nodes+=( "$t_host" )
done

tests/$TEST_NAME --no-syslog --logdir /log ${nodes[@]}
