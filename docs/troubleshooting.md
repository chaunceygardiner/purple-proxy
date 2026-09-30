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
A PurpleAir that has lost its WAN connection drops into setup mode.  In that
mode it answers a request addressed by DNS name with a redirect to its own
`PurpleAir-xxxx.lan` name, which nothing on the LAN can resolve, and the
reading is lost (`Failed to resolve 'purpleair-xxxx.lan'` in the log; `WAN
down, PA in setup mode` in the logwatch report).  Since 4.1 the daemon
resolves `hostname` itself and fetches by IP address, which the sensor
answers normally even in setup mode, so this failure should no longer
appear.  If it does, the sensor is redirecting a request addressed by IP;
please report it.

## Reads time out every couple of minutes

```
Skipping reading because of: ReadTimeout(ReadTimeoutError("HTTPConnectionPool(host='<address>', port=80): Read timed out. (read timeout=25)"))
```

If these arrive in a steady rhythm, every two minutes or so, with good
readings in between, look first at where else the sensor sends its data.
With the default 30-second `poll-freq-secs` the rhythm costs about one
poll in four, and every proxy polling that sensor sees the same pattern at
the same moments.

A PurpleAir can be registered to send its readings to a third-party server
as well as to PurpleAir, Weather Underground for example.  It sends on
a two-minute cycle, and while a send is waiting for its answer, the
sensor's web server does not answer on the LAN.  When that server is slow
or failing, each send waits out the sensor's own limit, about 35 seconds,
and any poll that lands in that window times out.  Raising `timeout-secs`
is not the fix: the window is longer than the 25-second default, and
outlasting it would take a timeout longer than `poll-freq-secs`.

To confirm it:

* The sensor's own page, `http://<sensor-hostname>/`, shows a light for
  each place the sensor sends to.  A third-party target is labeled `3RD`.
* Its `/json` has a `status_N` field for each target; `3` is a target
  whose sends are failing.  `httpsends` and `httpsuccess` count the sends
  and the ones that succeeded, so a failing target pulls `httpsuccess`
  well below `httpsends`: on sensors whose third-party target failed on
  every send, `httpsuccess` sat at about half of `httpsends`.
* Time the sensor directly for a few minutes.  It usually answers in a
  fraction of a second; one held up by a failing upload goes quiet for
  half a minute every two minutes:

  ```sh
  for i in $(seq 90); do curl -s -o /dev/null -m 60 -w '%{time_total}\n' 'http://<sensor-hostname>/json'; sleep 2; done
  ```

To fix it, remove the third-party upload from the sensor's registration
(the Registration & Map link on the sensor's page leads to it), or correct
it if you still want the data sent there.  The sensor picks up the change
from PurpleAir; check that the `3RD` light and its `status_N` field are
gone.  If they are still there a few minutes later, submit the
registration again.  The timeouts stop with the next upload cycle.

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

```
Could not save archive reading to database:
```

A record that cannot be saved is lost rather than retried; the failure is
logged at critical level and the daemon keeps running.  For an archive record
that is deliberate: the period's readings are discarded with it, so the next
record covers its own period only, instead of quietly averaging two periods
into one.

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
