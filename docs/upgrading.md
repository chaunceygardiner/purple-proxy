---
title: Upgrading
layout: default
nav_order: 3
---

# Upgrading

[purple-proxy manual](https://chaunceygardiner.github.io/purple-proxy/) · [purple-proxy on GitHub](https://github.com/chaunceygardiner/purple-proxy) · [Report an issue](https://github.com/chaunceygardiner/purple-proxy/issues)

---

Upgrading is the same script, run again:

```sh
cd <purple-proxy-src-dir>
sudo ./install -y
```

An upgrade never prompts.  Settings come from the installed
`purpleproxy.conf`; anything given on the command line overrides them.

## What the upgrade touches

**`purpleproxy.conf` is migrated, never regenerated.**  Existing values are
kept, options given on the command line win, options new to this version are
added with their defaults, and options this version no longer knows about
are dropped.  The previous file is saved as `purpleproxy.conf.bak`.

{: .note }
Hand-written comments in `purpleproxy.conf` do not survive migration.  Values
do — a per-machine `poll-freq-offset` is carried across upgrades.

**Every other conf file is left alone.**  The rsyslog, logrotate and the two
logwatch conf files are installed only when they are absent; once installed
they are yours to customize and no upgrade overwrites them.  When the version
shipped in a release differs from the one installed, your file is left in
place and the shipped version is written next to it as `<file>.dpkg-new` for
you to merge by hand.  Once the installed file matches what ships, the
`.dpkg-new` file is removed.

**Program files are refreshed every time.**  So is the logwatch classifier
script, which matches the daemon's log messages verbatim and therefore has
to ship with the daemon that writes them.

**A symlinked destination is always left in place.**  Files symlinked to a
source checkout keep working, and a symlinked `purpleproxy.conf` is not
migrated — edit the file it points at.

**The daemon is disturbed as little as possible.**  It is not stopped up
front.  At the end it is started if it was not running, and restarted only
if the program files, `purpleproxy.conf` or the systemd unit actually
changed.  An install that changed nothing leaves the running daemon alone.
rsyslog is restarted only when its conf was newly installed.

## Upgrading from before 4.0

Version 4.0 replaced the SysV init script and its nohup wrapper with a
systemd unit running as the `purpleproxy` system user.  The install script
migrates such an installation automatically: it stops and removes the old
init script, then installs, enables and starts the unit.  Nothing is asked
of you.

## Upgrading from before 2.3

Run the column upgrade once, from the root of the source directory:

```sh
sudo ./update_db_columns.sh
```

This adds the columns newer versions expect: the BME680 columns used by the
PurpleAir Flex and Zen, and `p_1_0_um`, `p_2_5_um`, `p_5_0_um` and
`p_10_0_um`.

{: .important }
This is required even for sensors that never report those fields.  The
columns must exist whether or not anything ever writes to them.
