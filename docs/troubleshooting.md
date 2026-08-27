---
title: Troubleshooting
layout: default
nav_order: 7
---

# Troubleshooting

[purple-proxy manual](https://chaunceygardiner.github.io/purple-proxy/) · [purple-proxy on GitHub](https://github.com/chaunceygardiner/purple-proxy) · [Report an issue](https://github.com/chaunceygardiner/purple-proxy/issues)

---

Almost everything shows up in `/var/log/purple-proxy.log`.  Start there.

```sh
tail -f /var/log/purple-proxy.log
```

## The service will not start

```sh
sudo systemctl status purple-proxy
sudo journalctl -u purple-proxy -n 50
```

The daemon reads its configuration once, at startup, and exits if it cannot.
The usual causes are a `database-file` in a directory the `purpleproxy` user
cannot write or traverse, a missing `hostname`, or a Python package that was
never installed (`python3-configobj`, `python3-dateutil`,
`python3-requests`).

Because the unit is `Restart=on-failure` with a ten second delay, a daemon
that fails at startup produces a start-fail-wait-start cycle in the journal
rather than a single error.  Look at the first failure, not the latest.

## No readings are arriving

The daemon logs `Saved current reading …` on every successful poll.  If
those lines are absent, the sensor is not answering.  Check by hand, from
the machine the proxy runs on:

```sh
curl 'http://<sensor-hostname>/json?live=true'
```

The log distinguishes the ways this fails, and the words matter.  These are
the words the daemon writes; the logwatch report gives the same failures
friendlier names, so grep the log for these, not for the report's:

| In the log | What it means |
| --- | --- |
| `Name or service not known` | DNS cannot resolve `hostname`.  Check the spelling and that the name resolves from *this* machine. |
| `No route to host`, `Network is unreachable` | The sensor is on a network this machine cannot reach. |
| `Connection refused` | Something answered at that address, but nothing is listening on `port`.  Wrong host, or wrong port. |
| `Read timed out` | The sensor accepted the connection and then did not answer within `timeout-secs`.  Usually an overloaded sensor. |
| `Connection aborted`, `Connection broken` | The sensor dropped the connection mid-answer. |
| `ChunkedEncodingError`, `JSONDecodeError` | The sensor answered with something that was not the JSON expected.  A sensor in setup mode does this. |

None of these stop the daemon.  Each is logged, the reading is skipped, the
requests session is reset, and the next poll tries again.

{: .note }
A PurpleAir that has lost its WAN connection can drop into setup mode and
serve a page that is not the reading JSON.  The logwatch classifier counts
this case separately (`WAN down, PA in setup mode`) precisely because it
looks alarming in the log but means only that the sensor wants its network
back.

## Readings arrive but are rejected

```
Reading found insane due to:  <reason>: <the reading>
```

The daemon checked the reading and refused to believe it.  The reason says
which check failed:

* **a field of the wrong type** — the device sent something that was not the
  number expected.  A JSON boolean where an integer belongs is rejected on
  purpose; `True` is not a particulate count.
* **the clock is off** — the reading's own timestamp differs from this
  machine's clock by more than 20 seconds.  Either the sensor's clock or the
  proxy machine's clock is wrong.  Check NTP on both.
* **the sensors disagree** — on a dual sensor outdoor device, the A and B
  halves differ more than twentyfold.  One of the two channels is usually
  obstructed, contaminated, or failing.

An occasional insane reading is normal and harmless — it is skipped and the
next poll carries on.  A steady stream of them is a sensor that needs
attention, and the logwatch report is where you will notice the trend.

## A gap in the archive

```
Skipping archive record because there have been zero readings this archive period.
```

Every reading in that whole period was missing or rejected, so no record was
written.  This is intentional: the period genuinely has no data, and writing
an invented value would be worse than leaving the hole.  Clients that
backfill from the archive will leave that period empty too.

If gaps are frequent, the cause is upstream — see the two sections above.

## Nothing answers on the REST port

```sh
curl 'http://localhost:8000/get-version'
```

If that hangs or is refused while the service is running, check that
`server-port` is what you think it is, and that nothing else on the machine
has taken the port.  Two proxies on the same machine must have different
`server-port` values (and different `database-file` paths).

Remember the argument separator is a comma:
`?since_ts=0,limit=10`.  With an ampersand, the proxy sees one long
malformed argument and answers 404.

## The log is not in `/var/log/purple-proxy.log`

Either rsyslog is not installed, or `service-name` has been changed from
`purple-proxy`.  The rsyslog rule keys on the program name; change the name
and the rule no longer matches.  The install script warns when it sees a
`service-name` that the shipped configuration does not route.

With `log-to-stdout = 1` the daemon logs to stdout instead of syslog, which
under systemd means the journal and not the file.

## The logwatch section is missing

logwatch must be installed **before** purple-proxy, since the install script
only lays down the logwatch configuration if logwatch is present.  Install
logwatch, then re-run `sudo ./install -y`.

## After an upgrade, a setting went back to its default

Check for `purpleproxy.conf.bak` next to the conf: migration keeps existing
values, so a value that reverted was probably spelled in a way this version
no longer recognizes and was dropped as deprecated.  The install prints
`Removing deprecated option: <key>.` when that happens.

{: .note }
If `purpleproxy.conf` is a symlink, it is deliberately **not** migrated —
the installer leaves the symlink alone and says so.  Edit the file it points
at.

## Still stuck

Turn on debug logging, restart, and watch a few polls:

```
debug = 1
```

Then [open an issue](https://github.com/chaunceygardiner/purple-proxy/issues)
with the relevant part of the log.
