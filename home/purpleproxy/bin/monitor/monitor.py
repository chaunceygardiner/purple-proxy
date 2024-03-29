#!/usr/bin/python3

# Copyright (c) 2022-2023 John A Kline
# See the file LICENSE for your full rights.

"""Make a rolling average of PurpleAir readings available.
Read from purple-air sensor every --poll-freq-secs seconds.
Offset readins by --poll-freq-offset.
Write an average readings every --archive-interval-secs to a file.
"""

import calendar
import copy
import optparse
import os
import requests
import sqlite3
import sys
import tempfile
import time
import traceback

import server.server

import configobj

from monitor import Logger
from datetime import datetime
from datetime import timedelta
from dateutil import tz
from dateutil.parser import parse
from enum import Enum
from json import dumps
from time import sleep

from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

PURPLEAIR_PROXY_VERSION = "3.5"

# Log to stdout until logger info is known.
log: Logger = Logger('monitor', log_to_stdout=True, debug_mode=False)

class Event(Enum):
    POLL = 1
    ARCHIVE = 2

@dataclass
class RGB:
    red  : int
    green: int
    blue : int

@dataclass
class SensorData:
    pm1_0_cf_1        : float
    pm1_0_atm         : float
    pm2_5_cf_1        : float
    pm2_5_atm         : float
    pm10_0_cf_1       : float
    pm10_0_atm        : float
    p_0_3_um          : float
    p_0_5_um          : float
    p_1_0_um          : float
    p_2_5_um          : float
    p_5_0_um          : float
    p_10_0_um         : float
    pm2_5_aqi         : int
    p25aqic           : RGB

@dataclass
class Reading:
    time_of_reading       : datetime
    current_temp_f        : int
    current_humidity      : int
    current_dewpoint_f    : int
    pressure              : float
    current_temp_f_680    : Optional[int]
    current_humidity_680  : Optional[int]
    current_dewpoint_f_680: Optional[int]
    pressure_680          : Optional[float]
    gas_680               : Optional[float]
    sensor                : SensorData
    sensor_b              : Optional[SensorData]

class DatabaseAlreadyExists(Exception):
    pass

class InsaneReading(Exception):
    pass

class UnexpectedPass(Exception):
    pass

class RecordType:
    CURRENT   : int = 0
    ARCHIVE   : int = 1
    TWO_MINUTE: int = 2

class Sensor:
    A: int = 0
    B: int = 1

class Database(object):
    def __init__(self, db_file: str):
        self.db_file = db_file

    @staticmethod
    def create(db_file): # -> Database:
        if db_file != ':memory:' and os.path.exists(db_file):
            raise DatabaseAlreadyExists("Database %s already exists" % db_file)
        if db_file != ':memory:':
            # Create parent directories
            dir = os.path.dirname(db_file)
            if not os.path.exists(dir):
                os.makedirs(dir)

        create_reading_table: str = ('CREATE TABLE Reading ('
            ' record_type            INTEGER NOT NULL,'
            ' timestamp              INTEGER NOT NULL,'
            ' current_temp_f         INTEGER NOT NULL,'
            ' current_humidity       INTEGER NOT NULL,'
            ' current_dewpoint_f     INTEGER NOT NULL,'
            ' pressure               REAL NOT NULL,'
            ' current_temp_f_680     INTEGER,'
            ' current_humidity_680   INTEGER,'
            ' current_dewpoint_f_680 INTEGER,'
            ' pressure_680           REAL,'
            ' gas_680                REAL,'
            ' PRIMARY KEY (record_type, timestamp));')

        create_sensor_table: str = ('CREATE TABLE Sensor ('
            ' record_type  INTEGER NOT NULL,'
            ' timestamp    INTEGER NOT NULL,'
            ' sensor       INTEGER NOT NULL,'
            ' pm1_0_cf_1   REAL NOT NULL,'
            ' pm1_0_atm    REAL NOT NULL,'
            ' pm2_5_cf_1   REAL NOT NULL,'
            ' pm2_5_atm    REAL NOT NULL,'
            ' pm10_0_cf_1  REAL NOT NULL,'
            ' pm10_0_atm   REAL NOT NULL,'
            ' p_0_3_um     REAL NOT NULL,'
            ' p_0_5_um     REAL NOT NULL,'
            ' p_1_0_um     REAL NOT NULL,'
            ' p_2_5_um      REAL NOT NULL,'
            ' p_5_0_um      REAL NOT NULL,'
            ' p_10_0_um     REAL NOT NULL,'
            ' pm2_5_aqi    INTEGER NOT NULL,'
            ' p25aqi_red   INTEGER NOT NULL,'
            ' p25aqi_green INTEGER NOT NULL,'
            ' p25aqi_blue  INTEGER NOT NULL,'
            ' PRIMARY KEY (record_type, timestamp, sensor));')

        with sqlite3.connect(db_file, timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute(create_reading_table)
            cursor.execute(create_sensor_table)
            cursor.close()

        return Database(db_file)

    def save_current_reading(self, r: Reading) -> None:
        self.save_reading(RecordType.CURRENT, r)

    def save_two_minute_reading(self, r: Reading) -> None:
        self.save_reading(RecordType.TWO_MINUTE, r)

    def save_archive_reading(self, r: Reading) -> None:
        self.save_reading(RecordType.ARCHIVE, r)

    def save_reading(self, record_type: int, r: Reading) -> None:
        stamp = int(r.time_of_reading.timestamp())
        if r.gas_680 is None:
            insert_reading_sql: str = ('INSERT INTO Reading ('
                ' record_type, timestamp, current_temp_f, current_humidity, current_dewpoint_f, pressure)'
                ' VALUES(%d, %d, %d, %d, %d, %f);' % (record_type, stamp, r.current_temp_f, r.current_humidity, r.current_dewpoint_f, r.pressure))
        else: # A PurpleAir Flex or Zen
            if r.current_temp_f_680 is not None and r.current_humidity_680 is not None and r.current_dewpoint_f_680 is not None and r.pressure_680 is not None:
                insert_reading_sql = ('INSERT INTO Reading ('
                    ' record_type, timestamp, current_temp_f, current_humidity, current_dewpoint_f, pressure, '
                    ' current_temp_f_680, current_humidity_680, current_dewpoint_f_680, pressure_680, gas_680)'
                    ' VALUES(%d, %d, %d, %d, %d, %f, %d, %d, %d, %f, %f);' % (
                        record_type, stamp, r.current_temp_f, r.current_humidity, r.current_dewpoint_f, r.pressure,
                        r.current_temp_f_680, r.current_humidity_680, r.current_dewpoint_f_680, r.pressure_680, r.gas_680))
            else:
                log.error('Skipping saving reading(%s): gas_680 present, but temp_f_680, humidity_680, dewpoint_f_680 or pressure_680 is None: %r' % (record_type, r))
        with sqlite3.connect(self.db_file, timeout=15) as conn:
            cursor = conn.cursor()
            # if a current record or two minute record, delete previous current.
            if record_type == RecordType.CURRENT:
                cursor.execute('DELETE FROM Reading where record_type = %d;' % RecordType.CURRENT)
                cursor.execute('DELETE FROM Sensor where record_type = %d;' % RecordType.CURRENT)
            if record_type == RecordType.TWO_MINUTE:
                cursor.execute('DELETE FROM Reading where record_type = %d;' % RecordType.TWO_MINUTE)
                cursor.execute('DELETE FROM Sensor where record_type = %d;' % RecordType.TWO_MINUTE)
            # Now insert.
            cursor.execute(insert_reading_sql)
            # Save the sensor reading(s)
            self.save_sensor(cursor, record_type, stamp, 0, r.sensor)
            if r.sensor_b is not None:
                self.save_sensor(cursor, record_type, stamp, 1, r.sensor_b)

    def save_sensor(self, cursor: sqlite3.Cursor, record_type: int, stamp: int, sensor_number: int, sensor: SensorData) -> None:
        insert_sensor_sql: str = ('INSERT INTO Sensor ('
            ' record_type, timestamp, sensor,'
            ' pm1_0_cf_1, pm1_0_atm, pm2_5_cf_1, pm2_5_atm, pm10_0_cf_1, pm10_0_atm,'
            ' p_0_3_um, p_0_5_um, p_1_0_um, p_2_5_um, p_5_0_um, p_10_0_um,'
            ' pm2_5_aqi, p25aqi_red, p25aqi_green, p25aqi_blue)'
            ' VALUES(%d, %d, %d, %f, %f, %f, %f, %f, %f, %f, %f, %f, %f, %f, %f, %d, %d, %d, %d);' % (
            record_type, stamp, sensor_number, sensor.pm1_0_cf_1, sensor.pm1_0_atm,
            sensor.pm2_5_cf_1, sensor.pm2_5_atm, sensor.pm10_0_cf_1, sensor.pm10_0_atm,
            sensor.p_0_3_um, sensor.p_0_5_um, sensor.p_1_0_um, sensor.p_2_5_um, sensor.p_5_0_um, sensor.p_10_0_um,
            sensor.pm2_5_aqi, sensor.p25aqic.red, sensor.p25aqic.green, sensor.p25aqic.blue))
        cursor.execute(insert_sensor_sql)

    def fetch_current_readings(self) -> Iterator[Reading]:
        return self.fetch_readings(RecordType.CURRENT, 0)

    def fetch_current_reading_as_json(self) -> str:
        for reading in self.fetch_current_readings():
            log.info('fetch-current-record')
            return Service.convert_to_json(reading)
        return '{}'

    def fetch_two_minute_readings(self) -> Iterator[Reading]:
        return self.fetch_readings(RecordType.TWO_MINUTE, 0)

    def fetch_two_minute_reading_as_json(self) -> str:
        for reading in self.fetch_two_minute_readings():
            log.info('fetch-two-minute-record')
            return Service.convert_to_json(reading)
        return '{}'

    def get_earliest_timestamp_as_json(self) -> str:
        select: str = ('SELECT timestamp FROM Reading WHERE record_type = %d'
            ' ORDER BY timestamp LIMIT 1') % RecordType.ARCHIVE
        log.debug('get-earliest-timestamp: select: %s' % select)
        resp = {}
        with sqlite3.connect(self.db_file, timeout=5) as conn:
            cursor = conn.cursor()
            for row in cursor.execute(select):
                log.debug('get-earliest-timestamp: returned %s' % row[0])
                resp['timestamp'] = row[0]
                break
        log.info('get-earliest-timestamp: %s' % dumps(resp))
        return dumps(resp)

    def fetch_archive_readings(self, since_ts: int = 0, max_ts: Optional[int] = None, limit: Optional[int] = None) -> Iterator[Reading]:
        return self.fetch_readings(RecordType.ARCHIVE, since_ts, max_ts, limit)

    def fetch_archive_readings_as_json(self, since_ts: int = 0, max_ts: Optional[int] = None, limit: Optional[int] = None) -> str:
        contents = ''
        for reading in self.fetch_archive_readings(since_ts, max_ts, limit):
            if contents != '':
                contents += ','
            contents += Service.convert_to_json(reading)
        log.info('fetch-archive-records')
        return '[  %s ]' % contents

    def fetch_readings(self, record_type: int, since_ts: int = 0, max_ts: Optional[int] = None, limit: Optional[int] = None) -> Iterator[Reading]:
        select: str = ('SELECT Reading.timestamp, current_temp_f,'
            ' current_humidity, current_dewpoint_f, pressure, current_temp_f_680, current_humidity_680,'
            ' current_dewpoint_f_680, pressure_680, gas_680, sensor,'
            ' pm1_0_cf_1, pm1_0_atm, pm2_5_cf_1, pm2_5_atm, pm10_0_cf_1, pm10_0_atm,'
            ' p_0_3_um, p_0_5_um, p_1_0_um, p_2_5_um, p_5_0_um, p_10_0_um,'
            ' pm2_5_aqi, p25aqi_red, p25aqi_green,'
            ' p25aqi_blue FROM Reading, Sensor WHERE Reading.record_type = %d'
            ' AND Sensor.record_type = %d AND Reading.timestamp = Sensor.timestamp'
            ' AND Reading.timestamp > %d') % (record_type, record_type, since_ts)
        if max_ts is not None:
            select = '%s AND Reading.timestamp <= %d' % (select, max_ts)
        select += ' ORDER BY Reading.timestamp, Sensor.record_type'
        if limit is not None:
            select = '%s LIMIT %d' % (select, limit)
        select += ';'
        log.debug('fetch_readings: select: %s' % select)
        with sqlite3.connect(self.db_file, timeout=5) as conn:
            cursor = conn.cursor()
            reading = None
            for row in cursor.execute(select):
                if reading is None:
                    reading = Database.create_reading_from_row(row)
                else:
                    # We aleady have a reading.  If this row
                    # is a sensor_b reading, add it the exising
                    # reading, then yeild it; else yield before
                    # processing this row.
                    if row[10] == 1: # a sensor b reading
                        reading = Database.add_to_reading_from_row(reading, row)
                        yield reading
                        reading = None
                    else:
                        # yield the last reading, this is a new reading
                        yield reading
                        reading = Database.create_reading_from_row(row)
            # There might be one not yet yielded
            if reading is not None:
                yield reading

    @staticmethod
    def create_reading_from_row(row) -> Reading:
        if row[10] == Sensor.B:
            raise UnexpectedSensorRecord('create_reading_from_row called with a B sensor row: %r' % row)
        return Reading(
            time_of_reading        = datetime.fromtimestamp(row[0], tz=tz.gettz('UTC')),
            current_temp_f         = row[1],
            current_humidity       = row[2],
            current_dewpoint_f     = row[3],
            pressure               = row[4],
            current_temp_f_680     = row[5],
            current_humidity_680   = row[6],
            current_dewpoint_f_680 = row[7],
            pressure_680           = row[8],
            gas_680                = row[9],
            sensor                 = SensorData(
                pm1_0_cf_1         = row[11],
                pm1_0_atm          = row[12],
                pm2_5_cf_1         = row[13],
                pm2_5_atm          = row[14],
                pm10_0_cf_1        = row[15],
                pm10_0_atm         = row[16],
                p_0_3_um           = row[17],
                p_0_5_um           = row[18],
                p_1_0_um           = row[19],
                p_2_5_um           = row[20],
                p_5_0_um           = row[21],
                p_10_0_um           = row[22],
                pm2_5_aqi          = row[23],
                p25aqic            = RGB(
                    red            = row[24],
                    green          = row[25],
                    blue           = row[26])),
            sensor_b               = None)

    @staticmethod
    def add_to_reading_from_row(reading, row) -> Reading:
        if row[10] == Sensor.A:
            raise UnexpectedSensorRecord('add_to_reading_from_row called with an A sensor row: %r' % row)
        reading.sensor_b   = SensorData(
            pm1_0_cf_1     = row[11],
            pm1_0_atm      = row[12],
            pm2_5_cf_1     = row[13],
            pm2_5_atm      = row[14],
            pm10_0_cf_1    = row[15],
            pm10_0_atm     = row[16],
            p_0_3_um       = row[17],
            p_0_5_um       = row[18],
            p_1_0_um       = row[19],
            p_2_5_um       = row[20],
            p_5_0_um       = row[21],
            p_10_0_um       = row[22],
            pm2_5_aqi      = row[23],
            p25aqic        = RGB(
                red        = row[24],
                green      = row[25],
                blue       = row[26]))
        return reading

class Service(object):
    def __init__(self, hostname: str, port: int, timeout_secs: int,
                 long_read_secs: int, pollfreq_secs: int,
                 pollfreq_offset: int, arcint_secs: int,
                 database: Database) -> None:
        self.hostname = hostname
        self.port = port
        self.timeout_secs    = timeout_secs
        self.long_read_secs  = long_read_secs
        self.pollfreq_secs   = pollfreq_secs
        self.pollfreq_offset = pollfreq_offset
        self.arcint_secs     = arcint_secs
        self.database        = database

        log.debug('Service created')

    @staticmethod
    def read_sensor(j: Dict[str, Any], suffix: str) -> SensorData:
        return SensorData(
            pm1_0_cf_1         = j['pm1_0_cf_1' + suffix],
            pm1_0_atm          = j['pm1_0_atm' + suffix],
            pm2_5_cf_1         = j['pm2_5_cf_1' + suffix],
            pm2_5_atm          = j['pm2_5_atm' + suffix],
            pm10_0_cf_1        = j['pm10_0_cf_1' + suffix],
            pm10_0_atm         = j['pm10_0_atm' + suffix],
            p_0_3_um           = j['p_0_3_um' + suffix],
            p_0_5_um           = j['p_0_5_um' + suffix],
            p_1_0_um           = j['p_1_0_um' + suffix],
            p_2_5_um           = j['p_2_5_um' + suffix],
            p_5_0_um           = j['p_5_0_um' + suffix],
            p_10_0_um           = j['p_10_0_um' + suffix],
            pm2_5_aqi          = j['pm2.5_aqi' + suffix],
            p25aqic            = Service.convert_str_to_rgb(j['p25aqic' + suffix]))

    @staticmethod
    def collect_data(session: requests.Session, hostname: str, port:int, timeout_secs: int, long_read_secs: int) -> Reading:
        # fetch data
        try:
            start_time = time.time()
            response: requests.Response = session.get(url="http://%s:%s/json?live=true" % (hostname, port), timeout=timeout_secs)
            response.raise_for_status()
            elapsed_time = time.time() - start_time
            log.debug('collect_data: elapsed time: %f seconds.' % elapsed_time)
            if elapsed_time > long_read_secs:
                log.info('Event took longer than expected: %f seconds.' % elapsed_time)
        except Exception as e:
            raise e
        return Service.parse_response(response)

    @staticmethod
    def datetime_from_reading(dt_str: str) -> datetime:
        time_of_reading_str: str = dt_str.replace('z', 'UTC')
        tzinfos = {'CST': tz.gettz("UTC")}
        return parse(time_of_reading_str, tzinfos=tzinfos)

    @staticmethod
    def parse_response(response: requests.Response) -> Reading:
        try:
            # convert to json
            j: Dict[str, Any] = response.json()
            reading: Reading = Reading(
                time_of_reading        = Service.datetime_from_reading(j['DateTime']),
                current_temp_f         = j['current_temp_f'],
                current_humidity       = j['current_humidity'],
                current_dewpoint_f     = j['current_dewpoint_f'],
                pressure               = j['pressure'],
                current_temp_f_680     = j['current_temp_f_680'] if 'current_temp_f_680' in j.keys() else None,
                current_humidity_680   = j['current_humidity_680'] if 'current_humidity_680' in j.keys() else None,
                current_dewpoint_f_680 = j['current_dewpoint_f_680'] if 'current_dewpoint_f_680' in j.keys() else None,
                pressure_680           = j['pressure_680'] if 'pressure_680' in j.keys() else None,
                gas_680                = j['gas_680'] if 'gas_680' in j.keys() else None,
                sensor                 = Service.read_sensor(j, ''),
                # Read sensor_b if one exists.
                sensor_b               = Service.read_sensor(j, '_b') if 'pm1_0_cf_1_b' in j.keys() else None)
            return reading
        except Exception as e:
            log.info('parse_response: %r raised exception %r' % (response.text, e))
            raise e

    @staticmethod
    def sum_rgb(rgb1: RGB, rgb2: RGB) -> RGB:
        return RGB(
            red   = rgb1.red   + rgb2.red,
            green = rgb1.green + rgb2.green,
            blue  = rgb1.blue  + rgb2.blue)

    @staticmethod
    def datetime_display(dt: datetime) -> str:
        ts = dt.timestamp()
        return "%s (%d)" % (time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(ts)), ts)

    @staticmethod
    def sum_sensor(sensor1: SensorData, sensor2: SensorData) -> SensorData:
        return SensorData(
            pm1_0_cf_1  = sensor1.pm1_0_cf_1    + sensor2.pm1_0_cf_1,
            pm1_0_atm   = sensor1.pm1_0_atm     + sensor2.pm1_0_atm,
            pm2_5_cf_1  = sensor1.pm2_5_cf_1    + sensor2.pm2_5_cf_1,
            pm2_5_atm   = sensor1.pm2_5_atm     + sensor2.pm2_5_atm,
            pm10_0_cf_1 = sensor1.pm10_0_cf_1   + sensor2.pm10_0_cf_1,
            pm10_0_atm  = sensor1.pm10_0_atm    + sensor2.pm10_0_atm,
            p_0_3_um    = sensor1.p_0_3_um      + sensor2.p_0_3_um,
            p_0_5_um    = sensor1.p_0_5_um      + sensor2.p_0_5_um,
            p_1_0_um    = sensor1.p_1_0_um      + sensor2.p_1_0_um,
            p_2_5_um    = sensor1.p_2_5_um      + sensor2.p_2_5_um,
            p_5_0_um    = sensor1.p_5_0_um      + sensor2.p_5_0_um,
            p_10_0_um    = sensor1.p_10_0_um    + sensor2.p_10_0_um,
            pm2_5_aqi   = sensor1.pm2_5_aqi     + sensor2.pm2_5_aqi,
            p25aqic     = Service.sum_rgb(sensor1.p25aqic, sensor2.p25aqic))

    @staticmethod
    def average_sensor(summed_sensor: SensorData, count: int) -> SensorData:
        return SensorData(
            pm1_0_cf_1  = summed_sensor.pm1_0_cf_1    / count,
            pm1_0_atm   = summed_sensor.pm1_0_atm     / count,
            pm2_5_cf_1  = summed_sensor.pm2_5_cf_1    / count,
            pm2_5_atm   = summed_sensor.pm2_5_atm     / count,
            pm10_0_cf_1 = summed_sensor.pm10_0_cf_1   / count,
            pm10_0_atm  = summed_sensor.pm10_0_atm    / count,
            p_0_3_um    = summed_sensor.p_0_3_um      / count,
            p_0_5_um    = summed_sensor.p_0_5_um      / count,
            p_1_0_um    = summed_sensor.p_1_0_um      / count,
            p_2_5_um    = summed_sensor.p_2_5_um      / count,
            p_5_0_um    = summed_sensor.p_5_0_um      / count,
            p_10_0_um   = summed_sensor.p_10_0_um     / count,
            pm2_5_aqi   = int(summed_sensor.pm2_5_aqi / count + 0.5),
            p25aqic     = RGB(
                int(summed_sensor.p25aqic.red / count + 0.5),
                int(summed_sensor.p25aqic.green / count + 0.5),
                int(summed_sensor.p25aqic.blue / count + 0.5)))

    @staticmethod
    def compute_avg(readings: List[Reading]) -> Reading:
        # We are gauranteed at least one reading.
        summed_reading: Reading = copy.deepcopy(readings[0])

        for reading in readings[1:]:
            summed_reading.time_of_reading    = reading.time_of_reading # This will be overwritten until we reach the latest time.
            summed_reading.current_temp_f     += reading.current_temp_f
            summed_reading.current_humidity   += reading.current_humidity
            summed_reading.current_dewpoint_f += reading.current_dewpoint_f
            summed_reading.pressure           += reading.pressure
            if (summed_reading.current_temp_f_680 is not None and reading.current_temp_f_680 is not None
                    and summed_reading.current_humidity_680 is not None and reading.current_humidity_680 is not None
                    and summed_reading.current_dewpoint_f_680 is not None and reading.current_dewpoint_f_680 is not None
                    and summed_reading.pressure_680 is not None and reading.pressure_680 is not None
                    and summed_reading.gas_680 is not None and reading.gas_680 is not None):
                summed_reading.current_temp_f_680     += reading.current_temp_f_680
                summed_reading.current_humidity_680   += reading.current_humidity_680
                summed_reading.current_dewpoint_f_680 += reading.current_dewpoint_f_680
                summed_reading.pressure_680           += reading.pressure_680
                summed_reading.gas_680        += reading.gas_680
            else:
                summed_reading.current_temp_f_680     = None
                summed_reading.current_humidity_680   = None
                summed_reading.current_dewpoint_f_680 = None
                summed_reading.pressure_680           = None
                summed_reading.gas_680                = None
            summed_reading.sensor              = Service.sum_sensor(summed_reading.sensor, reading.sensor)
            summed_reading.sensor_b            = Service.sum_sensor(summed_reading.sensor_b, reading.sensor_b) if summed_reading.sensor_b is not None and reading.sensor_b is not None else None

        count: int = len(readings)

        return Reading(
            time_of_reading        = summed_reading.time_of_reading,
            current_temp_f         = int(summed_reading.current_temp_f / count + 0.5),
            current_humidity       = int(summed_reading.current_humidity / count + 0.5),
            current_dewpoint_f     = int(summed_reading.current_dewpoint_f / count + 0.5),
            pressure               = summed_reading.pressure / float(count),
            current_temp_f_680     = int(summed_reading.current_temp_f_680 / count + 0.5) if summed_reading.current_temp_f_680 is not None else None,
            current_humidity_680   = int(summed_reading.current_humidity_680 / count + 0.5) if summed_reading.current_humidity_680 is not None else None,
            current_dewpoint_f_680 = int(summed_reading.current_dewpoint_f_680 / count + 0.5) if summed_reading.current_dewpoint_f_680 is not None else None,
            pressure_680           = summed_reading.pressure_680 / float(count) if summed_reading.pressure_680 is not None else None,
            gas_680                = summed_reading.gas_680 / float(count) if summed_reading.gas_680 is not None else None,
            sensor                 = Service.average_sensor(summed_reading.sensor, count),
            sensor_b               = Service.average_sensor(summed_reading.sensor_b, count) if summed_reading.sensor_b is not None else None)

    @staticmethod
    def sensor_to_dict(sensor: SensorData, suffix: str) -> Dict[str, Any]:
        sensor_dict: Dict[str, Any] = {
            'pm1_0_cf_1' + suffix  : sensor.pm1_0_cf_1,
            'pm1_0_atm' + suffix   : sensor.pm1_0_atm,
            'pm2_5_cf_1' + suffix  : sensor.pm2_5_cf_1,
            'pm2_5_atm' + suffix   : sensor.pm2_5_atm,
            'pm10_0_cf_1' + suffix : sensor.pm10_0_cf_1,
            'pm10_0_atm' + suffix  : sensor.pm10_0_atm,
            'p_0_3_um' + suffix    : sensor.p_0_3_um,
            'p_0_5_um' + suffix    : sensor.p_0_5_um,
            'p_1_0_um' + suffix    : sensor.p_1_0_um,
            'p_2_5_um' + suffix    : sensor.p_2_5_um,
            'p_5_0_um' + suffix    : sensor.p_5_0_um,
            'p_10_0_um' + suffix   : sensor.p_10_0_um,
            'pm2.5_aqi' + suffix   : sensor.pm2_5_aqi,
            'p25aqic' + suffix     : Service.convert_rgb_to_str(sensor.p25aqic)}
        return sensor_dict

    @staticmethod
    def convert_to_json(reading: Reading) -> str:
        reading_dict: Dict[str, Any] = {
            'DateTime'          : reading.time_of_reading.strftime('%Y/%m/%dT%H:%M:%Sz'),
            'current_temp_f'    : reading.current_temp_f,
            'current_humidity'  : reading.current_humidity,
            'current_dewpoint_f': reading.current_dewpoint_f,
            'pressure'          : reading.pressure}

        if reading.gas_680 is not None:
            reading_dict['current_temp_f_680']     = reading.current_temp_f_680
            reading_dict['current_humidity_680']   = reading.current_humidity_680
            reading_dict['current_dewpoint_f_680'] = reading.current_dewpoint_f_680
            reading_dict['pressure_680']           = reading.pressure_680
            reading_dict['gas_680']                = reading.gas_680

        reading_dict.update(Service.sensor_to_dict(reading.sensor, ''))
        if reading.sensor_b is not None:
            reading_dict.update(Service.sensor_to_dict(reading.sensor_b, '_b'))

        return dumps(reading_dict)

    @staticmethod
    def convert_rgb_to_str(rgb: RGB) -> str:
        return 'rgb(%d,%d,%d)' % (rgb.red, rgb.green, rgb.blue)

    @staticmethod
    def convert_str_to_rgb(rgb_string) -> RGB:
        # rgb(61,234,0)
        rgb_string = rgb_string.replace('rgb(', '')
        # 61,234,0)
        rgb_string = rgb_string.replace(')', '')
        # 61,234,0
        rgbs: List[str] = rgb_string.split(',')
        # [61, 234, 0]
        return RGB(red=int(rgbs[0]), green=int(rgbs[1]), blue=int(rgbs[2]))

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(tz=tz.gettz('UTC'))

    @staticmethod
    def is_sensor_sane(sensor_data: SensorData) -> Tuple[bool, str]:
        if not isinstance(sensor_data.pm1_0_cf_1, float):
            return False, 'pm1_0_cf_1 not instance of float'
        if not isinstance(sensor_data.pm1_0_atm, float):
            return False, 'pm1_0_atm not instance of float'
        if not isinstance(sensor_data.pm2_5_cf_1, float):
            return False, 'pm2_5_cf_1 not instance of float'
        if not isinstance(sensor_data.pm2_5_atm, float):
            return False, 'pm2_5_atm not instance of float'
        if not isinstance(sensor_data.pm10_0_cf_1, float):
            return False, 'pm10_0_cf_1 not instance of float'
        if not isinstance(sensor_data.pm10_0_atm, float):
            return False, 'pm10_0_atm not instance of float'
        if not isinstance(sensor_data.p_0_3_um, float):
            return False, 'p_0_3_um not instance of float'
        if not isinstance(sensor_data.p_0_5_um, float):
            return False, 'p_0_5_um not instance of float'
        if not isinstance(sensor_data.p_1_0_um, float):
            return False, 'p_1_0_um not instance of float'
        if not isinstance(sensor_data.p_2_5_um, float):
            return False, 'p_2_5_um not instance of float'
        if not isinstance(sensor_data.p_5_0_um, float):
            return False, 'p_5_0_um not instance of float'
        if not isinstance(sensor_data.p_10_0_um, float):
            return False, 'p_10_0_um not instance of float'
        if not isinstance(sensor_data.pm2_5_aqi, int):
            return False, 'pm2_5_aqi not instance of int'
        if not isinstance(sensor_data.p25aqic, RGB):
            return False, 'p25aqic not instance of RGB'
        return True, ''

    @staticmethod
    def trim_two_minute_readings(two_minute_readings: List[Reading]) -> None:
        two_minutes_ago: datetime = datetime.now(tz=tz.gettz('UTC')) - timedelta(seconds=120)
        while len(two_minute_readings) > 0 and two_minute_readings[0].time_of_reading < two_minutes_ago:
            two_minute_readings.pop(0)

    @staticmethod
    def exhibits_twenty_fold_delta(val_1: float, val_2: float) -> bool:
        # If either value is zero, skip this check.
        if val_1 == 0.0 or val_2 == 0.0:
            return False
        twenty_fold_diff = (val_1 * 20.0) < val_2 or (val_2 * 20.0) < val_1
        if twenty_fold_diff:
            # The twenty_fold_diff could be because 1 reading is close to zero.
            # As sush, return False if the delta between the readings is < 10.0
            if abs(val_1 - val_2) < 10.0:
                return False
        return twenty_fold_diff

    @staticmethod
    def is_sane(reading: Reading) -> Tuple[bool, str]:
        if not isinstance(reading.time_of_reading, datetime):
            return False, 'time_of_reading not instance of datetime'
        # Reject reading time that differs from now by more than 20s.
        delta_seconds = Service.utc_now().timestamp() - reading.time_of_reading.timestamp()
        if abs(delta_seconds) > 20.0:
            return False, 'time_of_reading more than 20s off: %f' % delta_seconds
        if not isinstance(reading.current_temp_f, int):
            return False, 'current_temp_f not instance of int'
        if not isinstance(reading.current_humidity, int):
            return False, 'current_humidity not instance of int'
        if not isinstance(reading.current_dewpoint_f, int):
            return False, 'current_dewpoint_f not instance of int'
        if not isinstance(reading.pressure, float):
            return False, 'pressure not instance of float'
        if reading.current_temp_f_680 is not None and not isinstance(reading.current_temp_f_680, int):
            return False, 'current_temp_f_680 not instance of int'
        if reading.current_humidity_680 is not None and not isinstance(reading.current_humidity_680, int):
            return False, 'current_humidity_680 not instance of int'
        if reading.current_dewpoint_f_680 is not None and not isinstance(reading.current_dewpoint_f_680, int):
            return False, 'current_dewpoint_f_680 not instance of int'
        if reading.pressure_680 is not None and not isinstance(reading.pressure_680, float):
            return False, 'pressure_680 not instance of float'
        if reading.gas_680 is not None and not isinstance(reading.gas_680, float):
            return False, 'gas_680 not instance of float'
        sane, reason = Service.is_sensor_sane(reading.sensor)
        if not sane:
            return False, 'sensor: %s' % reason
        if reading.sensor_b is not None:
            sane, reason = Service.is_sensor_sane(reading.sensor_b)
            if not sane:
                return False, 'sensor b: %s' % reason
            # Check on agreement between the sensors
            if Service.exhibits_twenty_fold_delta(reading.sensor.pm2_5_cf_1, reading.sensor_b.pm2_5_cf_1):
                return False, 'Sensors disagree wildly for pm2_5_cf_1 (%f, %f))' % (reading.sensor.pm2_5_cf_1, reading.sensor_b.pm2_5_cf_1)
            if Service.exhibits_twenty_fold_delta(reading.sensor.pm1_0_cf_1, reading.sensor_b.pm1_0_cf_1):
                return False, 'Sensors disagree wildly for pm1_0_cf_1 (%f, %f)' % (reading.sensor.pm1_0_cf_1, reading.sensor_b.pm1_0_cf_1)
            if Service.exhibits_twenty_fold_delta(reading.sensor.pm10_0_cf_1, reading.sensor_b.pm10_0_cf_1):
                return False, 'Sensors disagree wildly for pm10_0_cf_1 (%f, %f)' % (reading.sensor.pm10_0_cf_1, reading.sensor_b.pm10_0_cf_1)
        return True, ''

    def compute_next_event(self, first_time: bool) -> Tuple[Event, float]:
        now = time.time()
        next_poll_event = int(now / self.pollfreq_secs) * self.pollfreq_secs + self.pollfreq_secs
        next_arc_event = int(now / self.arcint_secs) * self.arcint_secs + self.arcint_secs
        event = Event.ARCHIVE if next_poll_event == next_arc_event else Event.POLL
        secs_to_event = next_poll_event - now
        # Add pollfreq_offset to computed next event.
        secs_to_event += self.pollfreq_offset
        log.debug('Next event: %r in %f seconds' % (event, secs_to_event))
        return event, secs_to_event

    def do_loop(self) -> None:
        archive_readings   : List[Reading] = []
        two_minute_readings: List[Reading] = []

        first_time: bool = True
        log.debug('Started main loop.')
        session: Optional[requests.Session] = None

        while True:
            if first_time:
                first_time = False
                event = Event.POLL
            else:
                # sleep until next event
                event, secs_to_event = self.compute_next_event(first_time)
                sleep(secs_to_event)

            # Always trim two_minute_readings
            Service.trim_two_minute_readings(two_minute_readings)

            # Write a reading and possibly write an archive record.
            try:
                # collect another reading and add it to archive_readings, two_minute_readings
                start = Service.utc_now()
                if session is None:
                    session= requests.Session()
                reading: Reading = Service.collect_data(session, self.hostname, self.port, self.timeout_secs, self.long_read_secs)
                log.debug('Read sensor in %d seconds.' % (Service.utc_now() - start).seconds)
                sane, reason = Service.is_sane(reading)
                if sane:
                    archive_readings.append(reading)
                    two_minute_readings.append(reading)
                    # Save this reading as the current reading
                    try:
                        start = Service.utc_now()
                        self.database.save_current_reading(reading)
                        log.info('Saved current reading %s in %d seconds.' %
                            (Service.datetime_display(reading.time_of_reading), (Service.utc_now() - start).seconds))
                    except Exception as e:
                        log.critical('Could not save current reading to database: %s: %s' % (self.database, e))
                else:
                    log.error('Reading found insane due to:  %s: %s' % (reason, reading))
            except Exception as e:
                log.error('Skipping reading because of: %r' % e)
                # It's probably a good idea to reset the session
                try:
                    if session is not None:
                        session.close()
                except Exception as e:
                    log.info('Non-fatal: calling session.close(): %s' % e)
                finally:
                    session = None

            # Write two minute avg reading.
            if len(two_minute_readings) == 0:
                log.error('Skipping two_minute record because there have been zero readings this two minute period.')
            else:
                avg_reading: Reading = Service.compute_avg(two_minute_readings)
                avg_reading.time_of_reading = two_minute_readings[-1].time_of_reading
                try:
                    start = Service.utc_now()
                    self.database.save_two_minute_reading(avg_reading)
                    log.info('Saved two minute reading %s in %d seconds (%d samples).' %
                        (Service.datetime_display(avg_reading.time_of_reading), (Service.utc_now() - start).seconds, len(two_minute_readings)))
                except Exception as e:
                    log.critical('Could not save two minute reading to database: %s: %s' % (self.database, e))

            # compute averages from records and write to database
            # if archive time, also write an archive record
            if event == event.ARCHIVE:
                if len(archive_readings) == 0:
                    log.error('Skipping archive record because there have been zero readings this archive period.')
                else: 
                    avg_reading = Service.compute_avg(archive_readings)
                    avg_reading.time_of_reading = Service.utc_now()
                    # We care more about the timestamp for archive cycles as we
                    # are writing permanent archive records.  As such, we
                    # want these times to align exactly with the archive cycle.
                    # ARCHIVE cycles might be used for backfilling.
                    # The plus five seconds is to guard against this routine
                    # running a few seconds early.
                    reading_plus_5s_ts = calendar.timegm(
                        (avg_reading.time_of_reading + timedelta(seconds=5)).utctimetuple())
                    archive_ts = int(reading_plus_5s_ts / self.arcint_secs) * self.arcint_secs
                    avg_reading.time_of_reading = datetime.fromtimestamp(archive_ts, tz=tz.gettz('UTC'))
                    try:
                        start = Service.utc_now()
                        self.database.save_archive_reading(avg_reading)
                        log.debug('Saved archive reading in %d seconds.' % (Service.utc_now() - start).seconds)
                        log.info('Added record %s to archive (%d samples).'
                            % (Service.datetime_display(avg_reading.time_of_reading), len(archive_readings)))
                        # Reset archive_readings for new archive cycle.
                        archive_readings.clear()
                    except Exception as e:
                        log.critical('Could not save archive reading to database: %s: %s' % (self.database, e))

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_passed() -> None:
    print(bcolors.OKGREEN + 'PASSED' + bcolors.ENDC)

def print_failed(e: Exception) -> None:
    print(bcolors.FAIL + 'FAILED' + bcolors.ENDC)
    print(traceback.format_exc())

def collect_two_readings_one_second_apart(hostname: str, port: int, timeout_secs: int, long_read_secs: int) -> Tuple[Reading, Reading]:
    try:
        session: requests.Session = requests.Session()
        print('collect_two_readings_one_seconds_apart...', end='')
        reading1: Reading = Service.collect_data(session, hostname, port, timeout_secs, long_read_secs)
        sleep(1) # to get a different time (to the second) on reading2
        reading2: Reading = Service.collect_data(session, hostname, port, timeout_secs, long_read_secs)
        print_passed()
        return reading1, reading2
    except Exception as e:
        print_failed(e)
        raise e

def run_tests(service_name: str, hostname: str, port: int, timeout_secs: int, long_read_secs: int) -> None:
    reading, reading2 = collect_two_readings_one_second_apart(hostname, port, timeout_secs, long_read_secs)
    test_db_archive_records(service_name, reading)
    test_db_current_records(service_name, reading, reading2)
    sanity_check_reading(reading)
    test_compute_avg(reading)
    test_convert_to_json(reading, reading2)
    check_sensor_agreement(reading, True)
    if reading.sensor_b is not None:
        reading.sensor_b.pm2_5_cf_1 = reading.sensor.pm2_5_cf_1 * 21.0
    check_sensor_agreement(reading, False)

def sanity_check_reading(reading: Reading) -> None:
    print('sanity_check_reading....', end='')
    sane, reason = Service.is_sane(reading)
    if sane:
        print_passed()
    else:
        print_failed(InsaneReading(reason))

def check_sensor_agreement(reading: Reading, should_agree: bool) -> None:
    print('check_sensor_agreement....', end='')
    sane, reason = Service.is_sane(reading)
    if sane and should_agree or not sane and not should_agree:
        print_passed()
    else:
        print_failed(InsaneReading(reason))

def test_compute_avg(reading: Reading) -> None:
    try:
        print('test_compute_avg....', end='')
        reading1: Reading = copy.deepcopy(reading)
        reading2: Reading = copy.deepcopy(reading)

        reading1.time_of_reading = datetime.now(tz=tz.gettz('UTC')) - timedelta(seconds=15)
        reading2.time_of_reading = datetime.now(tz=tz.gettz('UTC'))

        reading1.current_temp_f = 50
        reading2.current_temp_f = 100

        reading1.current_humidity = 40
        reading2.current_humidity = 20

        reading1.current_dewpoint_f = 30
        reading2.current_dewpoint_f = 40

        reading1.pressure = 1026.0
        reading2.pressure = 1024.0

        reading1.current_temp_f_680 = 40
        reading2.current_temp_f_680 = 90

        reading1.current_humidity_680 = 30
        reading2.current_humidity_680 = 10

        reading1.current_dewpoint_f_680 = 20
        reading2.current_dewpoint_f_680 = 30

        reading1.pressure_680 = 1022.0
        reading2.pressure_680 = 1020.0

        reading1.gas_680 = 50.0
        reading2.gas_680 = 100.0

        reading1.sensor.pm1_0_cf_1  = 0.12
        reading2.sensor.pm1_0_cf_1  = 0.36

        reading1.sensor.pm1_0_atm   = 0.10
        reading2.sensor.pm1_0_atm   = 0.00

        reading1.sensor.pm2_5_cf_1  = 0.58
        reading2.sensor.pm2_5_cf_1  = 0.78

        reading1.sensor.pm2_5_atm   = 0.77
        reading2.sensor.pm2_5_atm   = 0.88

        reading1.sensor.pm10_0_cf_1 = 0.88
        reading2.sensor.pm10_0_cf_1 = 1.03

        reading1.sensor.pm10_0_atm  = 0.99
        reading2.sensor.pm10_0_atm  = 1.05

        reading1.sensor.p_0_3_um    = 195.13
        reading2.sensor.p_0_3_um    = 195.17

        reading1.sensor.p_0_5_um    = 51.85
        reading2.sensor.p_0_5_um    = 47.28

        reading1.sensor.p_1_0_um    = 22.6
        reading2.sensor.p_1_0_um    = 22.8

        reading1.sensor.p_2_5_um    = 52.6
        reading2.sensor.p_2_5_um    = 52.8

        reading1.sensor.p_5_0_um    = 62.6
        reading2.sensor.p_5_0_um    = 62.8

        reading1.sensor.p_10_0_um    = 72.6
        reading2.sensor.p_10_0_um    = 72.8

        reading1.sensor.pm2_5_aqi   = 9
        reading2.sensor.pm2_5_aqi   = 2

        reading1.sensor.p25aqic.red   = 249
        reading1.sensor.p25aqic.green = 149
        reading1.sensor.p25aqic.blue  =  49
        reading2.sensor.p25aqic.red   = 200
        reading2.sensor.p25aqic.green = 100
        reading2.sensor.p25aqic.blue  =  10

        readings: List[Reading] = []
        readings.append(reading1)
        readings.append(reading2)

        avg_reading: Reading = Service.compute_avg(readings)

        assert avg_reading.time_of_reading == reading2.time_of_reading, 'Expected time_of_reading: %r, got %r.' % (reading2.time_of_reading, avg_reading.time_of_reading)
        assert avg_reading.current_temp_f == 75, 'Expected current_temp_f: 75, got %d.' % avg_reading.current_temp_f
        assert avg_reading.current_humidity == 30, 'Expected current_humidity: 30, got %d.' % avg_reading.current_humidity
        assert avg_reading.current_dewpoint_f == 35, 'Expected current_dewpoint_f: 35, got %d.' % avg_reading.current_dewpoint_f
        assert float_eq(avg_reading.pressure, 1025.0), 'Expected pressure: 1025.0, got %f.' % avg_reading.pressure

        assert avg_reading.current_temp_f_680 == 65, 'Expected current_temp_f_680: 65, got %r.' % avg_reading.current_temp_f_680
        assert avg_reading.current_humidity_680 == 20, 'Expected current_humidity_680: 20, got %r.' % avg_reading.current_humidity_680
        assert avg_reading.current_dewpoint_f_680 == 25, 'Expected current_dewpoint_f_680: 25, got %r.' % avg_reading.current_dewpoint_f_680
        assert float_eq(avg_reading.pressure_680, 1021.0), 'Expected pressure: 1021.0_680, got %r.' % avg_reading.pressure_680
        assert float_eq(avg_reading.gas_680, 75.0), 'Expected gas_680: 75.0, got %r.' % avg_reading.gas_680

        assert float_eq(avg_reading.sensor.pm1_0_cf_1, 0.24), 'Expected sensor.pm1_0_cf_1: 0.24, got %f.' % avg_reading.sensor.pm1_0_cf_1
        assert float_eq(avg_reading.sensor.pm1_0_atm, 0.05), 'Expected sensor.pm1_0_atm: 0.05, got %f.' % avg_reading.sensor.pm1_0_atm
        assert float_eq(avg_reading.sensor.pm2_5_cf_1, 0.68), 'Expected sensor.pm2_5_cf_1: 0.68, got %f.' % avg_reading.sensor.pm2_5_cf_1
        assert float_eq(avg_reading.sensor.pm2_5_atm, 0.825), 'Expected sensor.pm2_5_atm: 0.825, got %f.' % avg_reading.sensor.pm2_5_atm
        assert float_eq(avg_reading.sensor.pm10_0_cf_1, 0.955), 'Expected sensor.pm10_0_cf_1: 0.955, got %f.' % avg_reading.sensor.pm10_0_cf_1
        assert float_eq(avg_reading.sensor.pm10_0_atm, 1.02), 'Expected sensor.pm10_0_atm: 1.02, got %f.' % avg_reading.sensor.pm10_0_atm

        assert float_eq(avg_reading.sensor.p_0_3_um, 195.15), 'Expected sensor.p_0_3_um: 195.15, got %f.' % avg_reading.sensor.p_0_3_um
        assert float_eq(avg_reading.sensor.p_0_5_um, 49.565), 'Expected sensor.p_0_5_um: 49.565, got %f.' % avg_reading.sensor.p_0_5_um
        assert float_eq(avg_reading.sensor.p_1_0_um, 22.7), 'Expected sensor.p_1_0_um: 22.7, got %f.' % avg_reading.sensor.p_1_0_um
        assert float_eq(avg_reading.sensor.p_2_5_um, 52.7), 'Expected sensor.p_2_5_um: 52.7, got %f.' % avg_reading.sensor.p_2_5_um
        assert float_eq(avg_reading.sensor.p_5_0_um, 62.7), 'Expected sensor.p_5_0_um: 62.7, got %f.' % avg_reading.sensor.p_5_0_um
        assert float_eq(avg_reading.sensor.p_10_0_um, 72.7), 'Expected sensor.p_10_0_um: 72.7, got %f.' % avg_reading.sensor.p_10_0_um

        assert avg_reading.sensor.pm2_5_aqi == 6, 'Expected sensor.pm2_5_aqi: 6, got %d.' % avg_reading.sensor.pm2_5_aqi
        assert avg_reading.sensor.p25aqic.red == 225, 'Expected sensor.p25aqic.red: 225, got %d.' % avg_reading.sensor.p25aqic.red
        assert avg_reading.sensor.p25aqic.green == 125, 'Expected sensor.p25aqic.green: 125, got %d.' % avg_reading.sensor.p25aqic.green
        assert avg_reading.sensor.p25aqic.blue == 30, 'Expected sensor.p25aqic.blue: 30, got %d.' % avg_reading.sensor.p25aqic.blue
        print_passed()
    except Exception as e:
        print_failed(e)

def create_test_reading(time_of_reading: datetime) -> Reading:
    return Reading(
        time_of_reading = time_of_reading,
        current_temp_f = 100,
        current_humidity = 90,
        current_dewpoint_f = 80,
        pressure = 1234.5,
        current_temp_f_680 = 105,
        current_humidity_680 = 95,
        current_dewpoint_f_680 = 85,
        pressure_680 = 1235.6,
        gas_680 = 42.0,
        sensor = SensorData(
            pm1_0_cf_1  = 0.1,
            pm1_0_atm   = 0.2,
            pm2_5_cf_1  = 0.3,
            pm2_5_atm   = 0.4,
            pm10_0_cf_1 = 0.5,
            pm10_0_atm  = 0.6,
            p_0_3_um    = 0.7,
            p_0_5_um    = 0.8,
            p_1_0_um    = 0.9,
            p_2_5_um    = 0.91,
            p_5_0_um    = 0.92,
            p_10_0_um   = 0.93,
            pm2_5_aqi   = 9,
            p25aqic     = RGB(10,15,20)),
        sensor_b = SensorData(
            pm1_0_cf_1  = 1.1,
            pm1_0_atm   = 1.2,
            pm2_5_cf_1  = 1.3,
            pm2_5_atm   = 1.4,
            pm10_0_cf_1 = 1.5,
            pm10_0_atm  = 1.6,
            p_0_3_um    = 1.7,
            p_0_5_um    = 1.8,
            p_1_0_um    = 1.9,
            p_2_5_um    = 1.91,
            p_5_0_um    = 1.92,
            p_10_0_um   = 1.93,
            pm2_5_aqi   = 19,
            p25aqic     = RGB(110,120,130)))

def float_eq(v1: Optional[float], v2: Optional[float]) -> bool:
    if v1 is None and v2 is None:
        return True
    elif v1 is None or v2 is None:
        return False
    else:
        return abs(v1 - v2) < 0.0001

def test_db_archive_records(service_name: str, reading_in: Reading) -> None:
    try:
        print('test_db_archive_records....', end='')
        tmp_db = tempfile.NamedTemporaryFile(
            prefix='tmp-test-db-archive-%s.sdb' % service_name, delete=False)
        tmp_db.close()
        os.unlink(tmp_db.name)
        db = Database.create(tmp_db.name)
        db.save_archive_reading(reading_in)
        cnt = 0
        for reading_out in db.fetch_archive_readings(0):
            #print(reading_out)
            if reading_in != reading_out:
                print('test_db_archive_records failed: in: %r, out: %r' % (reading_in, reading_out))
            cnt += 1
        if cnt != 1:
            print('test_db_archive_records failed with count: %d' % cnt)
        print_passed()
    except Exception as e:
        print('test_db_archive_records failed: %s' % e)
        raise e
    finally:
        os.unlink(tmp_db.name)

def test_db_current_records(service_name: str, reading_in_1: Reading, reading_in_2: Reading) -> None:
    try:
        print('test_db_current_records....', end='')
        tmp_db = tempfile.NamedTemporaryFile(
            prefix='tmp-test-db-current-%s.sdb' % service_name, delete=False)
        tmp_db.close()
        os.unlink(tmp_db.name)
        db = Database.create(tmp_db.name)
        db.save_current_reading(reading_in_1)
        db.save_current_reading(reading_in_2)
        cnt = 0
        for reading_out in db.fetch_current_readings():
            #print(reading_out)
            if reading_in_2 != reading_out:
                print('test_db_current_records failed: in: %r, out: %r' % (reading_in_2, reading_out))
            cnt += 1
        if cnt != 1:
            print('test_db_current_records failed with count: %d' % cnt)
        print_passed()
    except Exception as e:
        print('test_db_current_records failed: %s' % e)
        raise e
    finally:
        os.unlink(tmp_db.name)

def test_convert_to_json(reading1: Reading, reading2: Reading) -> None:
    try:
        print('test_convert_to_json....', end='')

        Service.convert_to_json(reading1)
        Service.convert_to_json(reading2)

        tzinfos = {'CST': tz.gettz("UTC")}
        reading = create_test_reading(parse('2019/12/15T03:43:05UTC', tzinfos=tzinfos))
        json_reading: str = Service.convert_to_json(reading)

        expected = '{"DateTime": "2019/12/15T03:43:05z", "current_temp_f": 100, "current_humidity": 90, "current_dewpoint_f": 80, "pressure": 1234.5, "current_temp_f_680": 105, "current_humidity_680": 95, "current_dewpoint_f_680": 85, "pressure_680": 1235.6, "gas_680": 42.0, "pm1_0_cf_1": 0.1, "pm1_0_atm": 0.2, "pm2_5_cf_1": 0.3, "pm2_5_atm": 0.4, "pm10_0_cf_1": 0.5, "pm10_0_atm": 0.6, "p_0_3_um": 0.7, "p_0_5_um": 0.8, "p_1_0_um": 0.9, "p_2_5_um": 0.91, "p_5_0_um": 0.92, "p_10_0_um": 0.93, "pm2.5_aqi": 9, "p25aqic": "rgb(10,15,20)", "pm1_0_cf_1_b": 1.1, "pm1_0_atm_b": 1.2, "pm2_5_cf_1_b": 1.3, "pm2_5_atm_b": 1.4, "pm10_0_cf_1_b": 1.5, "pm10_0_atm_b": 1.6, "p_0_3_um_b": 1.7, "p_0_5_um_b": 1.8, "p_1_0_um_b": 1.9, "p_2_5_um_b": 1.91, "p_5_0_um_b": 1.92, "p_10_0_um_b": 1.93, "pm2.5_aqi_b": 19, "p25aqic_b": "rgb(110,120,130)"}'

        assert json_reading == expected, 'Expected json: %s, found: %s' % (expected, json_reading)
        print_passed()
    except Exception as e:
        print_failed(e)

def dump_database(db_file: str) -> None:
    start = Service.utc_now()
    database: Database = Database(db_file)
    print('----------------------------')
    print('* Dumping current reading  *')
    print('----------------------------')
    for reading in database.fetch_current_readings():
        print(reading)
        print('---')
    print('----------------------------')
    print('* Dumping archive readings *')
    print('----------------------------')
    for reading in database.fetch_archive_readings():
        print(reading)
        print('---')
    print('Dumped database in %d seconds.' % (Service.utc_now() - start).seconds)

class UnexpectedSensorRecord(Exception):
    pass

class CantOpenConfigFile(Exception):
    pass

class CantParseConfigFile(Exception):
    pass

def get_configuration(config_file):
    try:
        config_dict = configobj.ConfigObj(config_file, file_error=True, encoding='utf-8')
    except IOError:
        raise CantOpenConfigFile("Unable to open configuration file %s" % config_file)
    except configobj.ConfigObjError:
        raise CantParseConfigFile("Error parsing configuration file %s", config_file)

    return config_dict

def start(args):
    usage = """%prog [--help] [--test | --dump] [--pidfile <pidfile>] <purpleproxy-conf-file>"""
    parser: optparse.OptionParser = optparse.OptionParser(usage=usage)

    parser.add_option('-p', '--pidfile', dest='pidfile', action='store',
                      type=str, default=None,
                      help='When running as a daemon, pidfile in which to write pid.  Default is None.')
    parser.add_option('-t', '--test', dest='test', action='store_true', default=False,
                      help='Run tests and then exit. Default is False')
    parser.add_option('-d', '--dump', dest='dump', action='store_true', default=False,
                      help='Dump database and then exit. Default is False')

    (options, args) = parser.parse_args()

    if len(args) != 1:
        parser.error('Usage: [--pidfile <pidfile>] [--test | --dump] <purpleproxy-conf-file>')

    conf_file: str = os.path.abspath(args[0])
    config_dict    = get_configuration(conf_file)

    debug          : bool           = int(config_dict.get('debug', 0))
    log_to_stdout  : bool           = int(config_dict.get('log-to-stdout', 0))
    service_name   : str            = config_dict.get('service-name', 'purple-proxy')
    hostname       : Optional[str]  = config_dict.get('hostname', None)
    port           : int            = int(config_dict.get('port', 80))
    server_port    : int            = int(config_dict.get('server-port', 8000))
    timeout_secs   : int            = int(config_dict.get('timeout-secs', 25))
    long_read_secs : int            = int(config_dict.get('long-read-secs', 10))
    pollfreq_secs  : int            = int(config_dict.get('poll-freq-secs', 30))
    pollfreq_offset: int            = int(config_dict.get('poll-freq-offset', 0))
    arcint_secs    : int            = int(config_dict.get('archive-interval-secs', 300))
    db_file        : Optional[str]  = config_dict.get('database-file', None)

    global log
    log = Logger(service_name, log_to_stdout=log_to_stdout, debug_mode=debug)

    log.info('debug          : %r'    % debug)
    log.info('log_to_stdout  : %r'    % log_to_stdout)
    log.info('conf_file      : %s'    % conf_file)
    log.info('Version        : %s'    % PURPLEAIR_PROXY_VERSION)
    log.info('host:port      : %s:%s' % (hostname, port))
    log.info('server_port    : %s'    % server_port)
    log.info('timeout_secs   : %d'    % timeout_secs)
    log.info('long_read_secs : %d'    % long_read_secs)
    log.info('pollfreq_secs  : %d'    % pollfreq_secs)
    log.info('pollfreq_offset: %d'    % pollfreq_offset)
    log.info('arcint_secs    : %d'    % arcint_secs)
    log.info('db_file        : %s'    % db_file)
    log.info('service_name   : %s'    % service_name)
    log.info('pidfile        : %s'    % options.pidfile)

    if options.test and options.dump:
        parser.error('At most one of --test and --dump can be specified.')

    if options.test is True:
        if not hostname:
            parser.error('hostname must be specified in the config file')
        assert(hostname)
        run_tests(service_name, hostname, port, timeout_secs, long_read_secs)
        sys.exit(0)

    if options.dump is True:
        if not db_file:
            parser.error('database-file must be specified in the config file')
        assert(db_file)
        dump_database(db_file)
        sys.exit(0)

    if not hostname:
        parser.error('hostname must be specified in the config file')

    if not db_file:
        parser.error('database-file must be specified in the config file')

    # arcint must be a multilpe of pollfreq
    if arcint_secs % pollfreq_secs != 0:
        parser.error('archive-interval-secs must be a multiple of poll-frequency-secs')

    if options.pidfile is not None:
        pid: str = str(os.getpid())
        with open(options.pidfile, 'w') as f:
            f.write(pid+'\n')
            os.fsync(f)

    # Create database if it does not yet exist.
    assert(db_file)
    if not os.path.exists(db_file):
        log.debug('Creating database: %s' % db_file)
        database: Database = Database.create(db_file)
    else:
        assert(db_file)
        database = Database(db_file)

    assert(hostname)
    purpleproxy_service = Service(hostname, port, timeout_secs, long_read_secs, pollfreq_secs,
                                  pollfreq_offset, arcint_secs, database)

    log.debug('Staring server on port %d.' % server_port)
    assert(db_file)
    server.server.serve_requests(server_port, db_file, log)

    log.debug('Staring mainloop.')
    purpleproxy_service.do_loop()
