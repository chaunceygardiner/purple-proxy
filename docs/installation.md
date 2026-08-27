---
title: Installation
layout: default
nav_order: 2
---

# Installation

[purple-proxy manual](https://chaunceygardiner.github.io/purple-proxy/) · [purple-proxy on GitHub](https://github.com/chaunceygardiner/purple-proxy) · [Report an issue](https://github.com/chaunceygardiner/purple-proxy/issues)

---

**Requirements:** Debian or Raspberry Pi OS, systemd, and Python 3 with
`python3-configobj`, `python3-dateutil` and `python3-requests`.  There is no
virtual environment and nothing is installed with pip.  rsyslog is strongly
recommended — it is what routes the daemon's log to
`/var/log/purple-proxy.log`; without it the log lives only in the systemd
journal.  logwatch is optional; if it is present, a log classifier is
installed with the daemon.

{: .note }
These instructions and the `install` script have been tested on Debian and
Raspberry Pi OS.  On another platform the script still serves as a precise
specification of the steps required.

## 1. Get the source

Clone the repository:

```sh
git clone https://github.com/chaunceygardiner/purple-proxy
```

or download
[purple-proxy.zip](https://github.com/chaunceygardiner/purple-proxy/releases/latest/download/purple-proxy.zip)
from the
[releases page](https://github.com/chaunceygardiner/purple-proxy/releases)
and unzip it.  Either way, the resulting directory (`purple-proxy` when
cloned, `purple-proxy-master` when unzipped) is the source directory below.

## 2. Install the packages

```sh
sudo apt install rsyslog python3-configobj python3-dateutil python3-requests
```

## 3. Run the install script

```sh
cd <purple-proxy-src-dir>
sudo ./install
```

Every setting is a named command line option; `./install -h` lists them all.
On a fresh install the script prompts for anything not given on the command
line, showing the default — press Enter to accept it.  `-y` accepts every
default silently.

```sh
# Fully interactive:
sudo ./install

# Scripted; defaults for everything not given:
sudo ./install --sensor purple-air --poll-freq-offset 15 -y
```

{: .important }
The pre-4.0 positional form of the command (`./install <dir> <sensor> …`) is
rejected.  If you use it, the script prints the equivalent flags and exits
without changing anything.

On a fresh install the script:

* creates a `purpleproxy` system user for the daemon to run as;
* copies the program to the target directory (default `/home/purpleproxy`)
  and chowns it to that user;
* generates `<target-dir>/purpleproxy.conf` from the settings chosen;
* installs the rsyslog, logrotate and logwatch configuration;
* installs, enables and starts the `purple-proxy` systemd service.

## 4. Check that it is running

```sh
sudo systemctl status purple-proxy
curl 'http://localhost:8000/get-version'
```

The second command should answer `{"version": "3"}`.  Within a couple of
minutes `curl 'http://localhost:8000/json'` will return a reading.  See
[Running the proxy](running.md) for the log and
[Troubleshooting](troubleshooting.md) if nothing arrives.

## Uninstalling

```sh
sudo ./install --uninstall [<target-dir>]
```

The target directory is left in place, with its configuration and its
database — the archive history is not thrown away by an uninstall.
