---
title: Configuration
layout: default
nav_order: 4
---

# Configuration

[purple-proxy manual](https://chaunceygardiner.github.io/purple-proxy/) · [purple-proxy on GitHub](https://github.com/chaunceygardiner/purple-proxy) · [Report an issue](https://github.com/chaunceygardiner/purple-proxy/issues)

---

The daemon reads one file, `<target-dir>/purpleproxy.conf` (by default
`/home/purpleproxy/purpleproxy.conf`).  It is a flat `key = value` file — no
sections, no nesting:

```
debug                 = 0
log-to-stdout         = 0
service-name          = purple-proxy
hostname              = purple-air
port                  = 80
timeout-secs          = 25
long-read-secs        = 10
server-port           = 8000
poll-freq-secs        = 30
poll-freq-offset      = 0
archive-interval-secs = 300
gc-interval-secs      = 3600
database-file         = /home/purpleproxy/archive/purpleproxy.sdb
```

The install script writes this file and migrates it on upgrade, so the
normal way to change a setting is to re-run the installer with the matching
option (`./install -h` lists them).  Editing the file by hand works too;
restart the service afterwards.

| Key | Default | Description |
| --- | --- | --- |
| [`debug`](#debug) | 0 | Log debug messages. |
| [`log-to-stdout`](#log-to-stdout) | 0 | Log to stdout instead of syslog. |
| [`service-name`](#service-name) | purple-proxy | Syslog program name. |
| [`hostname`](#hostname) | (required) | DNS name or IP address of the sensor. |
| [`port`](#port) | 80 | Port of the sensor. |
| [`timeout-secs`](#timeout-secs) | 25 | Timeout for sensor reads. |
| [`long-read-secs`](#long-read-secs) | 10 | Log sensor reads slower than this. |
| [`server-port`](#server-port) | 8000 | Port the proxy's REST API listens on. |
| [`poll-freq-secs`](#poll-freq-secs) | 30 | How often to poll the sensor. |
| [`poll-freq-offset`](#poll-freq-offset) | 0 | Offset the polls by this many seconds. |
| [`archive-interval-secs`](#archive-interval-secs) | 300 | How often to write an archive record. |
| [`gc-interval-secs`](#gc-interval-secs) | 3600 | How often to run a garbage collection pass. |
| [`database-file`](#database-file) | (required) | Path of the sqlite database. |

## The settings

### debug

`0` or `1`.  With `1` the daemon logs a great deal more, including a line
for every poll.  Useful while setting up; noisy afterwards.

### log-to-stdout

`0` or `1`.  With `1` the daemon writes its log to stdout instead of syslog.
Under systemd that means the journal.  The normal value is `0`, which logs
to syslog and lets rsyslog route it to `/var/log/purple-proxy.log`.

### service-name

The program name the daemon logs under.  This is the name rsyslog, logrotate
and logwatch key on.

{: .important }
Change this and the shipped log configuration no longer matches: the log
stops arriving in `/var/log/purple-proxy.log` and the logwatch section stops
appearing.  The install script warns when the name is not `purple-proxy`.
There is very little reason to change it.

### hostname

The DNS name or IP address of the PurpleAir sensor on your network.  This is
the one setting with no useful default; the installer asks for it.  The
daemon fetches `http://<hostname>:<port>/json?live=true`.

### port

The sensor's HTTP port.  PurpleAir devices serve on 80 and there is rarely a
reason to change this.

### timeout-secs

How long to wait for a sensor read before giving up.  A read that times out
is logged and skipped; the next poll tries again with a fresh session.  The
default of 25 seconds is deliberately generous — a busy sensor can take many
seconds to answer, and a skipped reading is worse than a slow one.

### long-read-secs

Reads that take longer than this are logged (and counted in the logwatch
report) but are otherwise perfectly good readings.  This is a health signal
for the sensor, not an error: a rising count of long reads is the usual
first sign that a sensor is being asked for too much.

### server-port

The port the proxy's own REST API listens on.  The server binds `::`, so it
answers on IPv6 and IPv4 both.

{: .note }
Two proxies on the *same* machine — which is not the usual arrangement, but
is possible — need different `server-port` values and different
`database-file` paths.

### poll-freq-secs

How often the sensor is polled, in seconds.  Polls are scheduled on
boundaries of this value rather than "every N seconds from whenever the
daemon started", so with the default of 30 a poll lands on every minute and
every half minute.

`archive-interval-secs` must be a whole multiple of this value.  Both the
installer and the daemon itself refuse a combination that is not, so a
hand-edited conf with a bad pairing fails at startup rather than quietly
misbehaving.

### poll-freq-offset

Shifts every poll later by this many seconds.  It exists for the two-proxy
arrangement: with two proxies polling one sensor, give the second an offset
so the two never ask at the same moment.  Simultaneous requests are exactly
what a PurpleAir's processor handles worst — the symptom is occasional
multi-second delays in answering.

### archive-interval-secs

How often an averaged archive record is written to the database.  It should
match the archive interval of the weather software that reads it; 300 (five
minutes) is the WeeWX default and the default here.

The record is written by the first poll at or past the boundary, and its
timestamp is snapped to the boundary itself.  A sensor read that runs long
and straddles the boundary therefore delays the record by a poll rather than
losing it.

{: .note }
If a whole archive period passes with no sane reading at all, no record is
written for it.  That is deliberate: the gap is real, and inventing a value
to fill it would be worse than leaving it empty.

### gc-interval-secs

How often to run a full cyclic garbage collection pass, in seconds; `0`
disables it.  The pass runs only on non-archive polls, so its pause never
lands on top of the work of writing an archive record.  The default is
hourly.

### database-file

Path of the sqlite database holding the current reading, the two-minute
average and the archive history.  The installer's default is
`<target-dir>/archive/purpleproxy.sdb`.  It grows with the archive history
and is not pruned — a couple of years of five-minute records from a dual
sensor device runs to something like 80 MB.  Nothing here deletes old
records; they are the history that makes backfilling possible.
