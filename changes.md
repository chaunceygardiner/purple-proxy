# purple-proxy change history

## 4.1.1 (pending)

- The manual's troubleshooting page covers reads that time out every two
  minutes or so.  A PurpleAir also registered to send its readings to a
  third-party server, such as Weather Underground, stops answering on the
  LAN for about 35 seconds whenever a send to a failing server waits for
  its answer, which costs about one poll in four.  The page says how to
  confirm it from the sensor's own page and `/json`, and that removing or
  correcting the upload is the fix, not a longer `timeout-secs`.

## 4.1 (09/03/2026)

- The sensor is fetched by IP address rather than by name.  A PurpleAir that
  has lost its WAN connection drops into setup mode, and in that mode it
  answers a request addressed by DNS name with a redirect to its own
  `PurpleAir-xxxx.lan` name, which nothing on the LAN can resolve.  Every poll
  then failed for as long as the sensor stayed in that mode, and every proxy
  polling that sensor went silent at the same time.  The daemon now resolves
  `hostname` itself on every poll and fetches that address, which the sensor
  answers normally even in setup mode.  Resolving on every poll also means a
  sensor whose address changes is followed within one poll.
- An archive period's samples are now discarded when its record cannot be
  saved, instead of being folded into the next period's average.  The record
  is lost either way; carrying its readings forward quietly averaged two
  periods into one on top of the record already lost.
- A [manual](https://chaunceygardiner.github.io/purple-proxy/) covering
  installation, upgrading, every configuration setting, the REST API,
  running the service and troubleshooting.  `systemctl status` links to it.

## 4.0 (07/16/2026)

- Fixed: the `limit` argument of `fetch-archive-records` counted database rows
  rather than readings.  On dual sensor (outdoor) devices each reading spans
  two rows, so half the requested records came back, and an odd limit could
  split a reading and return its A sensor without its B sensor.
- Fixed: `since_ts=0` tripped an assertion and the client got a dropped
  connection instead of the archive records.
- Fixed: the archive query never really ordered A rows before B rows, so
  correct A/B pairing relied on the order SQLite happened to return.
- Fixed: a sensor read that blocked across an archive boundary skipped that
  period's record and folded its samples into the next one.  The record is
  written by the first poll at or past the boundary, correctly timestamped.
- Fixed: a Flex/Zen reading with `gas_680` present but a companion BME680
  field missing hit an unbound variable and was logged as a database error.
- Fixed: all SQL is parameterized.  Values had been interpolated with
  %-formatting, which also rounded floats to six decimal places on their way
  into the database.
- Fixed: sanity checks reject JSON booleans masquerading as integers, and
  error responses no longer carry stray header bytes.
- The daemon is restructured: `purpleproxyd` owns option and config parsing,
  `--dump`, and the version, and the 1200-line `monitor.py` is split into
  `monitor/model.py`, `monitor/database.py` and `monitor/service.py`.  Every
  log message is unchanged.
- A systemd unit replaces the init script and its nohup wrapper.  The daemon
  is supervised, runs as the dedicated `purpleproxy` system user rather than
  root, and crash tracebacks land in the journal instead of `/dev/null`.
- The installer takes every setting as a named flag and never silently
  overwrites configuration: `purpleproxy.conf` is migrated, and every other
  conf file is installed only when absent, with a changed shipped version
  written alongside as `<file>.dpkg-new`.  It also creates the `purpleproxy`
  user and migrates a SysV installation.
- New option `gc-interval-secs` (default 3600), a periodic garbage collection
  pass on a non-archive poll.
- **ACTION REQUIRED, breaking changes:** the positional install form is gone
  and exits with the equivalent option-based command; `purpleproxyd --test`
  is gone, replaced by `python3 tests/test-live.py`; the daemon runs as the
  `purpleproxy` user, which takes ownership of the target directory including
  the database; `/etc/init.d/purple-proxy` is removed, though
  `service purple-proxy start` still works.

## 3.5 (02/01/2024)

- Better logging when the A and B sensors disagree wildly.

## 3.4 (01/31/2024)

- Do not retry after a JSON decode error; wait for the next poll.

## 3.3 (01/27/2024)

- Retry the request on a JSON decode error.  Clean up mypy errors.

## 3.2 (01/25/2024)

- Tweak the detection of wildly differing sensor readings.

## 3.1 (10/25/2023)

- Guard against an insane reading on one of the two sensors.  When one is
  found, the observation is ignored.
- Sanity check that a reading's timestamp is no more than 20 seconds off the
  host clock, and log the reason a reading is declared insane.
- Do not retry a read against the device; wait for the next poll, so a slow
  sensor is not hammered.

## 3.0 (03/19/2023)

- `/json?live=true` returns the very latest reading; `/json` returns a two
  minute average.
- Serve on both IPv4 and IPv6.
- Poll as soon as the service starts rather than waiting for the first poll
  boundary.
- Log every request, return 404 for an unknown URI, and make error responses
  valid json.

## 2.3 (02/19/2023)

- Add the missing `p_1_0`, `p_2_5`, `p_5_0` and `p_10_0` fields.
- **ACTION REQUIRED:** run `update_db_columns.sh` when upgrading.

## 2.2 (02/19/2023)

- Add all the new BME680 columns found in the Flex and Zen products.
- **ACTION REQUIRED:** run `update_db_columns.sh` when upgrading.

## 2.1 (02/16/2023)

- Fix the 2.0 release.  Do not use 2.0.

## 2.0 (02/16/2023)

- Support the `gas_680` field available in the PurpleAir Flex.

## 1.0 (01/18/2020)

- Initial release: poll the sensor, sanity check and average readings, keep
  a sqlite archive, and serve them over a small REST API.
- `get-version`, retrieval of archive records in chunks, and a `limit`
  argument on `fetch-archive-records`.
- A poll frequency offset, so two proxies polling one sensor do not query it
  at the same moment.
- Request the live reading from the device rather than its two minute
  average, over a session that is reset when a read fails.
