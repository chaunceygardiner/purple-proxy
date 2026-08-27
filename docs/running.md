---
title: Running the proxy
layout: default
nav_order: 6
---

# Running the proxy

[purple-proxy manual](https://chaunceygardiner.github.io/purple-proxy/) · [purple-proxy on GitHub](https://github.com/chaunceygardiner/purple-proxy) · [Report an issue](https://github.com/chaunceygardiner/purple-proxy/issues)

---

## The service

purple-proxy runs as a systemd unit named `purple-proxy`, as the
`purpleproxy` system user, restarting on failure after ten seconds.

```sh
sudo systemctl status purple-proxy
sudo systemctl restart purple-proxy
sudo systemctl stop purple-proxy
sudo systemctl start purple-proxy
```

The install script enables and starts the unit; you should not normally need
to touch it, and an upgrade restarts it only if something actually changed.

## The log

Two places, and they hold different things:

```sh
sudo journalctl -u purple-proxy     # service-level messages: starts, stops, crashes
tail -f /var/log/purple-proxy.log   # the daemon's own log: readings, requests, errors
```

The second exists because rsyslog is configured to route everything logged
under the program name `purple-proxy` into that file, and then to stop
processing it — so the daemon's chatter does not also land in
`/var/log/syslog`.  If rsyslog is not installed, the daemon's log has
nowhere to go but the journal.

The log is rotated weekly with four rotations kept, using `copytruncate` so
the running daemon does not need to be signalled.

A healthy log is repetitive.  At the default settings you see a saved
current reading and a saved two-minute reading every 30 seconds, an archive
record every five minutes, a garbage collection pass every hour, and one
line per REST request served.

## The logwatch report

If logwatch is present when you install, a classifier script is installed
with it and a purple-proxy section appears in the regular logwatch report.
It counts what happened rather than reprinting the log: startups, readings
saved, archive records added, garbage collections, long sensor reads, and
each REST request by name.

Errors are counted by kind, which is what makes the report worth reading —
connection timeouts that retried against ones that gave up, connections
refused, connections aborted, read timeouts, name resolution failures, no
route to host, network unreachable, JSON decoding errors, chunk encoding
errors, database insert errors, skipped archive and two-minute records, and
insane readings split into the reason they were insane (bad instance, bad
time, sensors disagreeing, other).  A sensor that is quietly getting worse
shows up here as a rising count long before anything visibly breaks.

{: .important }
The classifier matches the daemon's log messages verbatim, so the two ship
together and an upgrade always refreshes the script.  If you customize the
logwatch conf files, note that they — unlike the classifier script — are
never overwritten once installed.

## Dumping the database

The daemon takes the configuration file as its argument and accepts two
options; `purpleproxyd --help` lists them.

`--dump` prints the current reading and every archive record held in the
database, then exits.  That is the entire history — on a proxy that has been
running a year or two, a hundred thousand readings or more — so page through
it:

```sh
python3 /home/purpleproxy/bin/purpleproxyd --dump \
    /home/purpleproxy/purpleproxy.conf | less
```

It only reads the database, so the service can be left running.

`--pidfile <path>` writes the process id to a file.  It is a holdover from
the days of the SysV init script; the systemd unit does not use it.

## Where everything lives

| Path | What it is |
| --- | --- |
| `/home/purpleproxy/bin/purpleproxyd` | The daemon. |
| `/home/purpleproxy/purpleproxy.conf` | Its configuration. |
| `/home/purpleproxy/archive/purpleproxy.sdb` | The sqlite database. |
| `/etc/systemd/system/purple-proxy.service` | The systemd unit. |
| `/etc/rsyslog.d/purple-proxy.conf` | Routes the log to its own file. |
| `/etc/logrotate.d/purple-proxy` | Rotates that file weekly. |
| `/etc/logwatch/conf/logfiles/purple-proxy.conf` | Tells logwatch where the log is. |
| `/etc/logwatch/conf/services/purple-proxy.conf` | Declares the logwatch service. |
| `/etc/logwatch/scripts/services/purple-proxy` | Classifies the log. |
| `/var/log/purple-proxy.log` | The daemon's log. |

The target directory defaults to `/home/purpleproxy` but is yours to choose
at install time; the unit is rewritten to match.
