---
title: Home
layout: default
nav_order: 1
permalink: /
---

# purple-proxy — one poller in front of the sensor

[View on GitHub](https://github.com/chaunceygardiner/purple-proxy){: .btn .btn-primary }
[Download purple-proxy.zip](https://github.com/chaunceygardiner/purple-proxy/releases/latest/download/purple-proxy.zip){: .btn }
[Report an issue](https://github.com/chaunceygardiner/purple-proxy/issues){: .btn }

purple-proxy is a small daemon that sits between your
[PurpleAir](https://www2.purpleair.com/) sensor and everything that wants to
read it.  It polls the sensor on the local network at a steady rate, sanity
checks each reading, keeps a rolling two-minute average, writes an archive
record every archive interval into a sqlite database, and answers a handful
of REST requests over HTTP.

It is a standalone program.  There is no WeeWX code in it and it does not
need WeeWX to run, though it was written with WeeWX in mind and the
[weewx-purple](https://github.com/chaunceygardiner/weewx-purple) extension
is its main client.

**Requirements:** Debian or Raspberry Pi OS, systemd, and Python 3 with the
`python3-configobj`, `python3-dateutil` and `python3-requests` packages.
See [Installation](installation.md).

## Why not just query the sensor directly?

**The sensor's processor is easily overwhelmed.**  It is a small embedded
device serving a JSON page.  Point two or three clients at it on a short
interval and readings start timing out.  The proxy is the only thing that
talks to the sensor, at one steady rate you choose, no matter how many
clients ask the proxy.

**A spot reading is noisy.**  Particulate counts jump around from one
sample to the next.  Asking the sensor directly gets you whatever it
happened to measure at that instant; asking the proxy gets you the average
of the last two minutes, which is what you actually want to graph or
report.

**Every reading is checked before it is believed.**  Field types are
verified (a JSON boolean where an integer belongs is rejected), readings
whose clock is more than 20 seconds off are rejected, and on dual sensor
outdoor devices a reading whose A and B halves disagree more than twentyfold
is rejected.  A bad reading is logged and skipped — the daemon does not pass
it on and does not exit.

**Only the proxy has a history.**  This is the reason that has no
workaround.  The sensor remembers nothing: ask it a question and it tells
you about right now.  The proxy writes an averaged archive record every
archive interval and keeps them.  weewx-purple 7.0 and later uses those
records to fill in `pm1_0`, `pm2_5` and `pm10_0` for every archive period
WeeWX was not running for, so a WeeWX outage no longer leaves a permanent
hole in the database or in the graphs drawn from it.  On a sensor-only
install there is nothing to recover from, because nothing kept the readings.

## Two proxies, one sensor

Running a single proxy makes the proxy a single point of failure.  The usual
arrangement is two proxies on two different machines polling the same
sensor, with
[`poll-freq-offset`](configuration.md#poll-freq-offset) set on the second so
the two never hit the sensor at the same moment.  Clients list both; if one
machine is down the other answers.

## Where to go next

* [Installation](installation.md) — get the source, install the service.
* [Upgrading](upgrading.md) — what a re-install does and does not touch.
* [Configuration](configuration.md) — every setting, with its default.
* [REST API](rest-api.md) — the requests the proxy answers.
* [Running the proxy](running.md) — service, logs, logwatch, dumping the database.
* [Troubleshooting](troubleshooting.md) — when readings stop arriving.
