---
title: REST API
layout: default
nav_order: 5
---

# REST API

[purple-proxy manual](https://chaunceygardiner.github.io/purple-proxy/) · [purple-proxy on GitHub](https://github.com/chaunceygardiner/purple-proxy) · [Report an issue](https://github.com/chaunceygardiner/purple-proxy/issues)

---

The proxy answers plain HTTP GETs on
[`server-port`](configuration.md#server-port) (8000 by default).  The server
binds `::`, so it answers over IPv6 and IPv4 both, and it is threaded —
requests do not queue behind one another.

{: .note }
Arguments are separated by commas, not ampersands:
`?since_ts=0,limit=10`.  This is not the usual query-string convention, but
it is what the proxy parses.

## Readings

### `/json`

Returns the average of the readings taken in the last two minutes.  This is
the request weather software normally makes; averaging is most of the point
of running a proxy.

### `/json?live=true`

Returns the most recent single reading, unaveraged.

### `/fetch-two-minute-record`

The same as `/json`.

### `/fetch-current-record`

The same as `/json?live=true`.

The JSON matches what the PurpleAir device itself serves, for the fields the
proxy stores.  On a dual sensor (outdoor) device the B sensor's fields are
present with a `_b` suffix:

```
$ curl 'http://localhost:8000/fetch-current-record'
{"DateTime": "2026/08/27T02:58:14z", "current_temp_f": 82,
 "current_humidity": 45, "current_dewpoint_f": 58, "pressure": 1014.97,
 "pm1_0_cf_1": 1.0, "pm1_0_atm": 1.0, "pm2_5_cf_1": 2.0, "pm2_5_atm": 2.0,
 "pm10_0_cf_1": 2.0, "pm10_0_atm": 2.0, "p_0_3_um": 357.0, "p_0_5_um": 103.0,
 "p_1_0_um": 18.0, "p_2_5_um": 1.0, "p_5_0_um": 0.0, "p_10_0_um": 0.0,
 "pm2.5_aqi": 8, "p25aqic": "rgb(1,228,0)",
 "pm1_0_cf_1_b": 1.0, ... "pm2.5_aqi_b": 4, "p25aqic_b": "rgb(0,228,0)"}
```

`DateTime` is UTC.  Note that the AQI field is spelled `pm2.5_aqi`, with a
dot, because that is how the device spells it.

## History

### `/get-earliest-timestamp`

The timestamp of the oldest archive record held, in seconds since the epoch:

```
$ curl 'http://localhost:8000/get-earliest-timestamp'
{"timestamp": 1726433400}
```

### `/fetch-archive-records?since_ts=<since_ts>`

Every archive record with a timestamp **greater than** `<since_ts>`, as a
JSON array of the same reading objects.  `since_ts=0` fetches the entire
history, which on a long-running proxy is a great many records.

Two optional arguments narrow it:

| Argument | Effect |
| --- | --- |
| `max_ts=<max_ts>` | Only records with timestamp **less than or equal to** `<max_ts>`. |
| `limit=<count>` | At most `<count>` records. |

They combine, in any order:

```
/fetch-archive-records?since_ts=1726433400,max_ts=1726433700
/fetch-archive-records?since_ts=0,limit=10
/fetch-archive-records?since_ts=0,max_ts=1726433700,limit=10
```

A single archive period is the `since_ts`/`max_ts` pair of that period's
bounds — which is exactly how weewx-purple backfills one missed period.

{: .note }
`limit` counts readings, not database rows.  On a dual sensor device each
reading occupies two rows, and before 4.0 the limit counted rows — halving
the number of records returned, and on an odd limit splitting a reading so
its A sensor arrived without its B.  If you are relying on `limit`, be on
4.0 or later.

## Version

### `/get-version`

```
$ curl 'http://localhost:8000/get-version'
{"version": "3"}
```

{: .important }
This is the version of the **command set** — the API described on this page
— not the version of the program.  It changes only when the requests
themselves change, which they have not since 3.  For the program version,
look at the `Version` line the daemon logs at startup.

## Errors

A malformed or unknown request gets HTTP 404 with the reason in the body:

```
$ curl 'http://localhost:8000/fetch-archive-records'
... <p>Message: fetch-archive-records requires since_ts argument.</p> ...

$ curl 'http://localhost:8000/bogus'
... <p>Message: Unknown command: /bogus..</p> ...
```

Requesting `/` itself answers `A command must be specified.` — there is no
index page.

Every request is logged at info level, which is what makes the logwatch
report able to say how many of each kind arrived.  See
[Running the proxy](running.md).
