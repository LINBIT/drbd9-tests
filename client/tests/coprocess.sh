#! /bin/bash

. ${0%/*}/../client.sh

create_coprocess LOCAL exxe
create_coprocess X ssh localhost exxe

exec < /dev/null

on LOCAL echo foo
on X echo foo
on LOCAL X echo bar
echo baz | on -i X tr a-z A-Z

close_coprocess LOCAL
close_coprocess X
