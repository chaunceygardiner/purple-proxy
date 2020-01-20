# purple-proxy
Proxy server for PurpleAir air quality sensor.  Serves current and archived readings which are averaged over a specified interval.

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
