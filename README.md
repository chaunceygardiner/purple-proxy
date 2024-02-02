# purple-proxy
Proxy server for PurpleAir air quality sensor.  Serves current and archived readings which are averaged over a specified interval.

## What? Why?

purple-proxy works in the backround querying the PurpleAir sensor and answers queries from clients about air quality.

### Why not query the sensor directly?
* The proxy can handle a higher load, even when running on a Raspberry Pi.
* The proxy will archive average readings every N seconds.  These archives are availble to be queried.
* For PurpleAir outdoor devices, that have two sensors, the proxy will answer with both readings plus an average between the two.
* Developed with WeeWX weather software in mind. Use with the [weewx-purple](https://github.com/chaunceygardiner/weewx-purple)
  plugin.

### Rest API
* `/json` Identical to quering the device directly (returns an average of readings over the last two minutes).
* `/json?live=true` Identical to quering the device directly (returns the latest reading).
* `/get-version' Returns the version of the proxy command set (currently, '3').
* `/get-earliest-timestamp' Returns the the timestamp of the oldest record in the database.
* `/fetch-two-minute-record` Same as `/json` (see above).
* `/fetch-current-record` Same as `/json?live=true` (see above).
* `/fetch-archive-records?since_ts=<timestamp>` Fetches all archive records >= <timestamp> (i.e., seconds since the epoch).
* `/fetch-archive-records?since_ts=<since_ts>,max_ts=<max_ts>` Fetches all archive records > <since_ts> and <= <max_ts>.
* `/fetch-archive-records?since_ts=<since_ts>,limit=<count>` Fetches up to <count> records  > <since_ts>.
* `/fetch-archive-records?since_ts=<since_ts>,max_ts=<max_ts>,limit=<count>` Fetches up to <count> archive records > <since_ts> and <= <max_ts>.

### Json Specification
See the PurpleAir spec for the json.  In addition to that spec, the proxy adds `_avg` fields for devices with two sensors.

## Important Instruction for those Upgrading from Version 1 to 2.

You must run the `sudo update_db_columns.sh` script (found in the root directory of this repository) if you are upgrading
from any version prior to version `2.3`.  This script adds the new (BM680) columns (found in the Flex and Zen products) to the database.
It also adds columns missing from the original PurpleAir devices (`p_1_0_um`, `p_2_5_um`, `p_5_0_um`, `p_10_0_um`).
***You must run this script  even if you don't have a PurpleAir Flex or PurpleAir Zen!***

## Installation Instructions

Note: Tested under Debian and Raspbian.  For other platorms,
these instructions and the install script serve as a specification
for what steps are needed to install.

If running debian bookworm:
```
sudo apt install rsyslog
sudo systemctl enable rsyslog
sudo systemctl start rsyslog
```

In all cases:

```
sudo apt install python3-configobj
sudo <purple-proxy-src-dir>/install <purple-proxy-src-dir> <target-dir> <archive-interval-seconds> <purpleair-dns-name-or-ip-address>"
```

### Example installation commands:
```
cd ~/software/purple-proxy
sudo ./install . /home/purpleproxy 300 purple-air
```
