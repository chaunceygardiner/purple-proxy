#!/usr/bin/python3

# Copyright (c) 2026 John A Kline
# See the file LICENSE for your full rights.

"""Offline tests for the monitor and server code: database round trips,
fetch semantics (since_ts/max_ts/limit), sanity checks and REST request
parsing.  Needs no live sensor (the live-sensor path is covered by
tests/test-live.py).

    python3 tests/test-monitor.py

Exits non-zero if any test fails.
"""

import os
import sys
import tempfile

from datetime import datetime, timedelta
from dateutil import tz

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'home', 'purpleproxy', 'bin'))

from fixtures import create_test_reading
from monitor.database import Database
from monitor.service import Service
import server.server as srv

failures = []

def check(label: str, cond: bool, detail: str = '') -> None:
    if cond:
        print('PASS: %s' % label)
    else:
        failures.append(label)
        print('FAIL: %s %s' % (label, detail))

now = datetime.now(tz=tz.gettz('UTC')).replace(microsecond=0)

# --- build a database holding 5 dual-sensor archive readings 60s apart ---
tmp = tempfile.NamedTemporaryFile(prefix='purple-proxy-test', suffix='.sdb', delete=False)
tmp.close()
os.unlink(tmp.name)
db = Database.create(tmp.name)

readings_in = []
for i in range(5):
    r = create_test_reading(now + timedelta(seconds=60 * i))
    db.save_archive_reading(r)
    readings_in.append(r)

# 1. since_ts=0 returns everything, in order, with both sensors present.
out = list(db.fetch_archive_readings(0))
check('fetch all (since_ts=0) returns 5 readings', len(out) == 5, 'got %d' % len(out))
check('all readings have sensor_b', all(r.sensor_b is not None for r in out))
check('readings in timestamp order',
      [r.time_of_reading for r in out] == [r.time_of_reading for r in readings_in])
check('round trip equality', all(a == b for a, b in zip(readings_in, out)))

# 2. limit counts readings, not sensor rows (an odd limit must not split a
#    dual sensor reading and drop its B half).
out = list(db.fetch_archive_readings(0, limit=3))
check('limit=3 returns 3 readings', len(out) == 3, 'got %d' % len(out))
check('limit=3: every reading keeps its B sensor', all(r.sensor_b is not None for r in out))
out = list(db.fetch_archive_readings(0, limit=1))
check('limit=1 returns 1 reading with B sensor', len(out) == 1 and out[0].sensor_b is not None)

# 3. max_ts is honored, alone and alongside limit.
cutoff = int(readings_in[2].time_of_reading.timestamp())
out = list(db.fetch_archive_readings(0, max_ts=cutoff))
check('max_ts returns 3 readings', len(out) == 3, 'got %d' % len(out))
out = list(db.fetch_archive_readings(0, max_ts=cutoff, limit=2))
check('max_ts+limit returns 2 readings', len(out) == 2, 'got %d' % len(out))

# 4. since_ts is exclusive.
first_ts = int(readings_in[0].time_of_reading.timestamp())
out = list(db.fetch_archive_readings(first_ts))
check('since_ts exclusive', len(out) == 4, 'got %d' % len(out))

# 5. get_earliest_timestamp.
js = db.get_earliest_timestamp_as_json()
check('earliest timestamp', ('"timestamp": %d' % first_ts) in js, js)

# 6. save_reading skip path: gas_680 present but a companion field None must
#    log and skip, not crash, and must save nothing.
bad = create_test_reading(now + timedelta(seconds=600))
bad.pressure_680 = None
before = len(list(db.fetch_archive_readings(0)))
try:
    db.save_archive_reading(bad)
    after = len(list(db.fetch_archive_readings(0)))
    check('gas_680 skip path: no crash, nothing saved', after == before,
          'before=%d after=%d' % (before, after))
except Exception as e:
    check('gas_680 skip path: no crash, nothing saved', False, repr(e))

# 7. CURRENT stays single-row via delete+insert.
db.save_current_reading(readings_in[0])
db.save_current_reading(readings_in[1])
cur = list(db.fetch_current_readings())
check('current reading single row, latest wins',
      len(cur) == 1 and cur[0].time_of_reading == readings_in[1].time_of_reading)

# 8. is_sane rejects a bool masquerading as an int.
sane_r = create_test_reading(datetime.now(tz=tz.gettz('UTC')))
ok, _ = Service.is_sane(sane_r)
check('sane reading passes', ok)
sane_r.current_temp_f = True
ok, reason = Service.is_sane(sane_r)
check('bool temp rejected', not ok and reason == 'current_temp_f not instance of int', reason)
sane_r.current_temp_f = 70
sane_r.sensor.pm2_5_aqi = False
ok, reason = Service.is_sane(sane_r)
check('bool aqi rejected', not ok and 'pm2_5_aqi not instance of int' in reason, reason)

# 9. REST request parsing.
req = srv.Handler.parse_requestline('GET /fetch-archive-records?since_ts=0 HTTP/1.1')
check('since_ts=0 parses as FETCH_ARCHIVE_RECORDS',
      req.request_type == srv.RequestType.FETCH_ARCHIVE_RECORDS and req.since_ts == 0)
req = srv.Handler.parse_requestline('GET /fetch-archive-records?since_ts=5,max_ts=9,limit=2 HTTP/1.1')
check('full args parse', req.since_ts == 5 and req.max_ts == 9 and req.limit == 2)
req = srv.Handler.parse_requestline('GET /fetch-archive-records HTTP/1.1')
check('missing since_ts is an error', req.request_type == srv.RequestType.ERROR)
req = srv.Handler.parse_requestline('GET /fetch-archive-records?since_ts=abc HTTP/1.1')
check('non-integer since_ts is an error', req.request_type == srv.RequestType.ERROR)
req = srv.Handler.parse_requestline('GET /json?live=true HTTP/1.1')
check('/json?live=true is fetch-current', req.request_type == srv.RequestType.FETCH_CURRENT_RECORD)
req = srv.Handler.parse_requestline('GET /json HTTP/1.1')
check('/json is fetch-two-minute', req.request_type == srv.RequestType.FETCH_TWO_MINUTE_RECORD)
req = srv.Handler.parse_requestline('GET /nonsense HTTP/1.1')
check('unknown command is an error', req.request_type == srv.RequestType.ERROR)

os.unlink(tmp.name)
print()
if failures:
    print('%d FAILURES: %s' % (len(failures), failures))
    sys.exit(1)
print('ALL PASSED')
