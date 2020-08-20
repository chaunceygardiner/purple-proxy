# purple-proxy
Proxy server for PurpleAir air quality sensor.  Serves current and archived readings (archive records
are are averaged over a specified interval).

## What? Why?

purple-proxy works in the backround querying the PurpleAir sensor and answers queries from clients about air quality.

### Why not query the sensor directly?
* The proxy can handle a higher load, even when running on a Raspberry Pi.
* The proxy will archive average readings every N seconds.  These archives are availble to be queried.
* Developed with WeeWX weather software in mind. Use with the [weewx-purple](https://github.com/chaunceygardiner/weewx-purple)
  plugin.

### Rest API
* `/json` Identical to quering the device directly.
   (Provided so that clients that don't know about the proxy can still use the proxy.)
* `/get-version' Returns the version of the proxy command set (currently, '1').
* `/get-earliest-timestamp' Returns the the timestamp of the oldest record in the database.
* `/fetch-current-record` Same as `/json`.
* `/fetch-archive-records?since_ts=<timestamp>` Fetches all archive records >= <timestamp> (i.e., seconds since the epoch).
* `/fetch-archive-records?since_ts=<since_ts>,max_ts=<max_ts>` Fetches all archive records > <since_ts> and <= <max_ts>.
* `/fetch-archive-records?since_ts=<since_ts>,limit=<count>` Fetches up to <count> records  > <since_ts>.
* `/fetch-archive-records?since_ts=<since_ts>,max_ts=<max_ts>,limit=<count>` Fetches up to <count> archive records > <since_ts> and <= <max_ts>.

### Json Specification
See the PurpleAir spec for the json.  In addition to that spec, the proxy adds `_avg` fields for devices with two sensors.

## Installation Instructions

Note: Tested under Debian and Raspbian.  For other platorms,
these instructions and the install script serve as a specification
for what steps are needed to install.

```
sudo <purple-proxy-src-dir>/install <purple-proxy-src-dir> <target-dir> <archive-interval-seconds> <purpleair-dns-name-or-ip-address>"
```

### Example installation commands:
```
cd ~/software/purple-proxy
sudo ./install . /home/purpleproxy 300 purple-air
```
