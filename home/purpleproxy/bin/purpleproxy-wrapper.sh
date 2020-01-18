#!/bin/sh

cd /home/purpleproxy/bin
nohup /home/purpleproxy/bin/purpleproxyd /home/purpleproxy/purpleproxy.conf $@ > /dev/null 2>&1 &
