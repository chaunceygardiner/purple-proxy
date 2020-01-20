#!/bin/sh

# Copyright (c) 2020 John A Kline
# See the file LICENSE for your full rights.

cd /home/purpleproxy/bin
nohup /home/purpleproxy/bin/purpleproxyd /home/purpleproxy/purpleproxy.conf $@ > /dev/null 2>&1 &
