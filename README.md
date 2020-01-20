# purple-proxy
Proxy server for PurpleAir air quality sensor.  Serves current and archived readings which are averaged over a specified interval.

## What? Why?

purple-proxy works in the backround querying the PurpleAir sensor and answers queries from clients about air quality.

### Why not query the sensor directly?
* The proxy can handle a higher load, even when running on a Raspberry Pi.
* The proxy will answer the query with an average over the last N seconds (where N is configurable).
* The proxy will archive average readings every N seconds.  These archives are availble to be queried.
* For PurpleAir outdoor devices, that have two sensors, the proxy will answer with both readings plus an average between the two.
* Developed with WeeWX weather software in mind. Use with the [weewx-purple](https://github.com/chaunceygardiner/weewx-purple)
  plugin.

### Rest API
* `/json` Identical to quering the device directly (but also includes the averages in the json).
   (Provided so that clients that don't know about the proxy can still use the proxy and get averaged readings).
* `/fetch-current-record` Same as `/json`.
* `/fetch-archive-records?since_ts=<timestamp` Fetches all archive records since the timestamp (i.e., seconds since the epoch).

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
