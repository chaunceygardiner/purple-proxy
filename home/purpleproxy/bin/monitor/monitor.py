#!/usr/bin/python3

# Copyright (c) 2020 John A Kline
# See the file LICENSE for your full rights.

"""Make a rolling average of PurpleAir readings available.
Read from purple-air sensor every --poll-freq-secs seconds.
Write an average readings every --archive-interval-secs to a file.
"""

import calendar
import copy
import json
import optparse
import os
import requests
import shutil
import sqlite3
import sys
import syslog
import tempfile
import time
import traceback

import server.server

import configobj

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from dateutil import tz
from dateutil.parser import parse
from enum import Enum
from json import dumps
from time import sleep

from dataclasses import dataclass, field
from typing import Any, Dict, IO, Iterator, List, Optional, Tuple

PURPLEAIR_PROXY_VERSION = "1.0"

class Logger(object):
    def __init__(self, service_name: str, log_to_stdout: bool=False, debug_mode: bool=False):
        self.service_name = service_name
        self.log_to_stdout = log_to_stdout
        self.debug_mode = debug_mode
        if not log_to_stdout:
            syslog.openlog(service_name, syslog.LOG_PID | syslog.LOG_CONS)

    def logmsg(self, level: int, msg: str) -> None:
        if self.log_to_stdout:
            l: str
            if level == syslog.LOG_DEBUG:
                l = 'DEBUG'
            elif level == syslog.LOG_INFO:
                l = 'INFO'
            elif level == syslog.LOG_ERR:
                l = 'ERR'
            elif level == syslog.LOG_CRIT:
                l = 'CRIT'
            else:
                l = '%d' % level
            print('%s: %s: %s' % (l, self.service_name, msg))
        else:
            syslog.syslog(level, msg)

    def debug(self, msg: str) -> None:
        if self.debug_mode:
            self.logmsg(syslog.LOG_DEBUG, msg)

    def info(self, msg: str) -> None:
        self.logmsg(syslog.LOG_INFO, msg)

    def error(self, msg: str) -> None:
        self.logmsg(syslog.LOG_ERR, msg)

    def critical(self, msg: str) -> None:
        self.logmsg(syslog.LOG_CRIT, msg)

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
    p_0_3_um          : float
    pm2_5_cf_1        : float
    pm2_5_atm         : float
    p_0_5_um          : float
    pm10_0_cf_1       : float
    pm10_0_atm        : float
    pm2_5_aqi         : int
    p25aqic           : RGB

@dataclass
class Reading:
    time_of_reading   : datetime
    current_temp_f    : int
    current_humidity  : int
    current_dewpoint_f: int
    pressure          : float
    sensor            : SensorData
    sensor_b          : Optional[SensorData]

class DatabaseAlreadyExists(Exception):
    pass

class RecordType:
    CURRENT: int = 0
    ARCHIVE: int = 1

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
            ' record_type        INTEGER NOT NULL,'
            ' timestamp          INTEGER NOT NULL,'
            ' current_temp_f     INTEGER NOT NULL,'
            ' current_humidity   INTEGER NOT NULL,'
            ' current_dewpoint_f INTEGER NOT NULL,'
            ' pressure           REAL NOT NULL,'
            ' PRIMARY KEY (record_type, timestamp));')

        create_sensor_table: str = ('CREATE TABLE Sensor ('
            ' record_type  INTEGER NOT NULL,'
            ' timestamp    INTEGER NOT NULL,'
            ' sensor       INTEGER NOT NULL,'
            ' pm1_0_cf_1   REAL NOT NULL,'
            ' pm1_0_atm    REAL NOT NULL,'
            ' p_0_3_um     REAL NOT NULL,'
            ' pm2_5_cf_1   REAL NOT NULL,'
            ' pm2_5_atm    REAL NOT NULL,'
            ' p_0_5_um     REAL NOT NULL,'
            ' pm10_0_cf_1  REAL NOT NULL,'
            ' pm10_0_atm   REAL NOT NULL,'
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

    def save_archive_reading(self, r: Reading) -> None:
        self.save_reading(RecordType.ARCHIVE, r)

    def save_reading(self, record_type: int, r: Reading) -> None:
        stamp = int(r.time_of_reading.timestamp())
        insert_reading_sql: str = ('INSERT INTO Reading ('
            ' record_type, timestamp, current_temp_f, current_humidity, current_dewpoint_f, pressure)'
            ' VALUES(%d, %d, %d, %d, %d, %f);' % (record_type, stamp, r.current_temp_f, r.current_humidity, r.current_dewpoint_f, r.pressure))
        with sqlite3.connect(self.db_file, timeout=5) as conn:
            cursor = conn.cursor()
            # if a current record, delete previous current.
            if record_type == RecordType.CURRENT:
                cursor.execute('DELETE FROM Reading where record_type = %d;' % RecordType.CURRENT)
                cursor.execute('DELETE FROM Sensor where record_type = %d;' % RecordType.CURRENT)
            # Now insert.
            cursor.execute(insert_reading_sql)
            # Save the sensor reading(s)
            self.save_sensor(cursor, record_type, stamp, 0, r.sensor)
            if r.sensor_b is not None:
                self.save_sensor(cursor, record_type, stamp, 1, r.sensor_b)

    def save_sensor(self, cursor: sqlite3.Cursor, record_type: int, stamp: int, sensor_number: int, sensor: SensorData) -> None:
        insert_sensor_sql: str = ('INSERT INTO Sensor ('
            ' record_type, timestamp, sensor, pm1_0_cf_1, pm1_0_atm, p_0_3_um, pm2_5_cf_1,'
            ' pm2_5_atm, p_0_5_um, pm10_0_cf_1, pm10_0_atm, pm2_5_aqi,'
            ' p25aqi_red, p25aqi_green, p25aqi_blue)'
            ' VALUES(%d, %d, %d, %f, %f, %f, %f, %f, %f, %f, %f, %d, %d, %d, %d);' % (
            record_type, stamp, sensor_number, sensor.pm1_0_cf_1, sensor.pm1_0_atm, sensor.p_0_3_um,
            sensor.pm2_5_cf_1, sensor.pm2_5_atm, sensor.p_0_5_um, sensor.pm10_0_cf_1,
            sensor.pm10_0_atm, sensor.pm2_5_aqi, sensor.p25aqic.red, sensor.p25aqic.green, sensor.p25aqic.blue))
        cursor.execute(insert_sensor_sql)

    def fetch_current_readings(self) -> Iterator[Reading]:
        return self.fetch_readings(RecordType.CURRENT, 0)

    def fetch_current_reading_as_json(self) -> str:
        for reading in self.fetch_current_readings():
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
        log.debug('get-earliest-timestamp: returning: %s' % dumps(resp))
        return dumps(resp)

    def fetch_archive_readings(self, since_ts: int = 0, max_ts: Optional[int] = None, limit: Optional[int] = None) -> Iterator[Reading]:
        return self.fetch_readings(RecordType.ARCHIVE, since_ts, max_ts, limit)

    def fetch_archive_readings_as_json(self, since_ts: int = 0, max_ts: Optional[int] = None, limit: Optional[int] = None) -> str:
        contents = ''
        for reading in self.fetch_archive_readings(since_ts, max_ts, limit):
            if contents != '':
                contents += ','
            contents += Service.convert_to_json(reading)
        return '[  %s ]' % contents

    def fetch_readings(self, record_type: int, since_ts: int = 0, max_ts: Optional[int] = None, limit: Optional[int] = None) -> Iterator[Reading]:
        select: str = ('SELECT Reading.timestamp, current_temp_f,'
            ' current_humidity, current_dewpoint_f, pressure, sensor,'
            ' pm1_0_cf_1, pm1_0_atm, p_0_3_um, pm2_5_cf_1, pm2_5_atm, p_0_5_um,'
            ' pm10_0_cf_1, pm10_0_atm, pm2_5_aqi, p25aqi_red, p25aqi_green,'
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
                    if row[5] == 1: # a sensor b reading
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
        if row[5] == Sensor.B:
            raise UnexpectedSensorRecord('create_reading_from_row called with a B sensor row: %r' % row)
        return Reading(
            time_of_reading    = datetime.fromtimestamp(row[0], tz=tz.gettz('UTC')),
            current_temp_f     = row[1],
            current_humidity   = row[2],
            current_dewpoint_f = row[3],
            pressure           = row[4],
            sensor             = SensorData(
                pm1_0_cf_1     = row[6],
                pm1_0_atm      = row[7],
                p_0_3_um       = row[8],
                pm2_5_cf_1     = row[9],
                pm2_5_atm      = row[10],
                p_0_5_um       = row[11],
                pm10_0_cf_1    = row[12],
                pm10_0_atm     = row[13],
                pm2_5_aqi      = row[14],
                p25aqic        = RGB(
                    red        = row[15],
                    green      = row[16],
                    blue       = row[17])),
            sensor_b             = None)

    @staticmethod
    def add_to_reading_from_row(reading, row) -> Reading:
        if row[5] == Sensor.A:
            raise UnexpectedSensorRecord('add_to_reading_from_row called with an A sensor row: %r' % row)
        reading.sensor_b   = SensorData(
            pm1_0_cf_1     = row[6],
            pm1_0_atm      = row[7],
            p_0_3_um       = row[8],
            pm2_5_cf_1     = row[9],
            pm2_5_atm      = row[10],
            p_0_5_um       = row[11],
            pm10_0_cf_1    = row[12],
            pm10_0_atm     = row[13],
            pm2_5_aqi      = row[14],
            p25aqic        = RGB(
                red        = row[15],
                green      = row[16],
                blue       = row[17]))
        return reading

class Service(object):
    def __init__(self, hostname: str, port: int, timeout_secs: int,
                 pollfreq_secs: int, arcint_secs: int, database: Database) -> None:
        self.hostname = hostname
        self.port = port
        self.timeout_secs = timeout_secs
        self.pollfreq_secs = pollfreq_secs
        self.arcint_secs = arcint_secs
        self.database = database

        log.debug('Service created')

    @staticmethod
    def read_sensor(j: Dict[str, Any], suffix: str) -> SensorData:
        return SensorData(
            pm1_0_cf_1         = j['pm1_0_cf_1' + suffix],
            pm1_0_atm          = j['pm1_0_atm' + suffix],
            p_0_3_um           = j['p_0_3_um' + suffix],
            pm2_5_cf_1         = j['pm2_5_cf_1' + suffix],
            pm2_5_atm          = j['pm2_5_atm' + suffix],
            p_0_5_um           = j['p_0_5_um' + suffix],
            pm10_0_cf_1        = j['pm10_0_cf_1' + suffix],
            pm10_0_atm         = j['pm10_0_atm' + suffix],
            pm2_5_aqi          = j['pm2.5_aqi' + suffix],
            p25aqic            = Service.convert_str_to_rgb(j['p25aqic' + suffix]))

    @staticmethod
    def collect_data(hostname: str, port:int, timeout_secs:int) -> Reading:
        # fetch data
        # If the machine was just rebooted, a temporary failure in name
        # resolution is likely.  As such, try three times.
        for i in range(3):
            try:
                response: requests.Response = requests.get(url="http://%s:%s/json" % (hostname, port), timeout=timeout_secs)
                response.raise_for_status()
            except requests.exceptions.ConnectionError as e:
                if i < 2:
                    log.info('%s: Retrying request.' % e)
                    time.sleep(5)
                else:
                    raise e
        return Service.parse_response(response)

    @staticmethod
    def datetime_from_reading(dt_str: str) -> datetime:
        time_of_reading_str: str = dt_str.replace('z', 'UTC')
        tzinfos = {'CST': tz.gettz("UTC")}
        tmp = parse(time_of_reading_str, tzinfos=tzinfos)
        return parse(time_of_reading_str, tzinfos=tzinfos)

    @staticmethod
    def parse_response(response: requests.Response) -> Reading:
        # convert to json
        j: Dict[str, Any] = response.json()
        reading: Reading = Reading(
            time_of_reading    = Service.datetime_from_reading(j['DateTime']),
            current_temp_f     = j['current_temp_f'],
            current_humidity   = j['current_humidity'],
            current_dewpoint_f = j['current_dewpoint_f'],
            pressure           = j['pressure'],
            sensor             = Service.read_sensor(j, ''),
            # Read sensor_b if one exists.
            sensor_b           = Service.read_sensor(j, '_b') if 'pm1_0_cf_1_b' in j.keys() else None)
        return reading

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
            p_0_3_um    = sensor1.p_0_3_um      + sensor2.p_0_3_um,
            pm2_5_cf_1  = sensor1.pm2_5_cf_1    + sensor2.pm2_5_cf_1,
            pm2_5_atm   = sensor1.pm2_5_atm     + sensor2.pm2_5_atm,
            p_0_5_um    = sensor1.p_0_5_um      + sensor2.p_0_5_um,
            pm10_0_cf_1 = sensor1.pm10_0_cf_1   + sensor2.pm10_0_cf_1,
            pm10_0_atm  = sensor1.pm10_0_atm    + sensor2.pm10_0_atm,
            pm2_5_aqi   = sensor1.pm2_5_aqi     + sensor2.pm2_5_aqi,
            p25aqic     = Service.sum_rgb(sensor1.p25aqic, sensor2.p25aqic))

    @staticmethod
    def average_sensor(summed_sensor: SensorData, count: int) -> SensorData:
        return SensorData(
            pm1_0_cf_1  = summed_sensor.pm1_0_cf_1    / count,
            pm1_0_atm   = summed_sensor.pm1_0_atm     / count,
            p_0_3_um    = summed_sensor.p_0_3_um      / count,
            pm2_5_cf_1  = summed_sensor.pm2_5_cf_1    / count,
            pm2_5_atm   = summed_sensor.pm2_5_atm     / count,
            p_0_5_um    = summed_sensor.p_0_5_um      / count,
            pm10_0_cf_1 = summed_sensor.pm10_0_cf_1   / count,
            pm10_0_atm  = summed_sensor.pm10_0_atm    / count,
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
            summed_reading.sensor              = Service.sum_sensor(summed_reading.sensor, reading.sensor)
            summed_reading.sensor_b            = Service.sum_sensor(summed_reading.sensor_b, reading.sensor_b) if summed_reading.sensor_b is not None and reading.sensor_b is not None else None

        count: int = len(readings)

        return Reading(
            time_of_reading    = summed_reading.time_of_reading,
            current_temp_f     = int(summed_reading.current_temp_f / count + 0.5),
            current_humidity   = int(summed_reading.current_humidity / count + 0.5),
            current_dewpoint_f = int(summed_reading.current_dewpoint_f / count + 0.5),
            pressure           = summed_reading.pressure / float(count),
            sensor             = Service.average_sensor(summed_reading.sensor, count),
            sensor_b           = Service.average_sensor(summed_reading.sensor_b, count) if summed_reading.sensor_b is not None else None)

    @staticmethod
    def sensor_to_dict(sensor: SensorData, suffix: str) -> Dict[str, Any]:
        sensor_dict: Dict[str, Any] = {
            'pm1_0_cf_1' + suffix  : sensor.pm1_0_cf_1,
            'pm1_0_atm' + suffix   : sensor.pm1_0_atm,
            'p_0_3_um' + suffix    : sensor.p_0_3_um,
            'pm2_5_cf_1' + suffix  : sensor.pm2_5_cf_1,
            'pm2_5_atm' + suffix   : sensor.pm2_5_atm,
            'p_0_5_um' + suffix    : sensor.p_0_5_um,
            'pm10_0_cf_1' + suffix : sensor.pm10_0_cf_1,
            'pm10_0_atm' + suffix  : sensor.pm10_0_atm,
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
    def is_sensor_sane(sensor_data: SensorData) -> bool:
        if not isinstance(sensor_data.pm1_0_cf_1, float):
            return False
        if not isinstance(sensor_data.pm1_0_atm, float):
            return False
        if not isinstance(sensor_data.p_0_3_um, float):
            return False
        if not isinstance(sensor_data.pm2_5_cf_1, float):
            return False
        if not isinstance(sensor_data.pm2_5_atm, float):
            return False
        if not isinstance(sensor_data.p_0_5_um, float):
            return False
        if not isinstance(sensor_data.pm10_0_cf_1, float):
            return False
        if not isinstance(sensor_data.pm10_0_atm, float):
            return False
        if not isinstance(sensor_data.pm2_5_aqi, int):
            return False
        if not isinstance(sensor_data.p25aqic, RGB):
            return False
        return True

    @staticmethod
    def is_sane(reading: Reading) -> bool:
        if not isinstance(reading.time_of_reading, datetime):
            return False
        if not isinstance(reading.current_temp_f, int):
            return False
        if not isinstance(reading.current_humidity, int):
            return False
        if not isinstance(reading.current_dewpoint_f, int):
            return False
        if not isinstance(reading.pressure, float):
            return False
        if not Service.is_sensor_sane(reading.sensor):
            return False
        if reading.sensor_b is not None and not Service.is_sensor_sane(reading.sensor_b):
            return False
        return True

    def compute_next_event(self, first_time: bool) -> Tuple[Event, float]:
        now = time.time()
        next_poll_event = int(now / self.pollfreq_secs) * self.pollfreq_secs + self.pollfreq_secs
        next_arc_event = int(now / self.arcint_secs) * self.arcint_secs + self.arcint_secs
        event = Event.ARCHIVE if next_poll_event == next_arc_event else Event.POLL
        secs_to_event = next_poll_event - now
        log.debug('Next event: %r in %f seconds' % (event, secs_to_event))
        if not first_time and secs_to_event < 24.0:
            log.info('Event took longer than expected.  Next event in %f seconds.' % secs_to_event)
        return event, secs_to_event

    def do_loop(self) -> None:
        readings: List[Reading] = []

        first_time: bool = True
        log.debug('Started main loop.')
        while True:
            # sleep until next event
            event, secs_to_event = self.compute_next_event(first_time)
            first_time = False
            sleep(secs_to_event)

            # Write a reading and possibly write an archive record.
            try:
                # collect another reading and add it to readings
                start = Service.utc_now()
                reading: Reading = Service.collect_data(self.hostname, self.port, self.timeout_secs)
                log.debug('Read sensor in %d seconds.' % (Service.utc_now() - start).seconds)
                if Service.is_sane(reading):
                    readings.append(reading)
                else:
                    log.error('Reading found insane: %s' % reading)
            except Exception as e:
                log.error('Skipping reading because of: %s' % e)
                if len(readings) == 0 and event == event.ARCHIVE:
                    log.error('Skipping archive record because there have been zero readings this archive period.')

            # May or may not have a new reading.  If reading not sane or
            # exception, the reading isn't added to readings.

            # compute averages from records and write to database
            # if archive time, also write an archive record
            if len(readings) > 0:
                avg_reading: Reading = Service.compute_avg(readings)
                avg_reading.time_of_reading = Service.utc_now()
                # We care more about the timestamp for archive cycles as we
                # are writing permanent archive records.  As such, we
                # want these times to align exactly with the archive cycle.
                # ARCHIVE cycles might be used for backfilling.
                if event == event.ARCHIVE:
                    # The plus five seconds is to guard against this routine
                    # running a few seconds early.
                    reading_plus_5s_ts = calendar.timegm(
                        (avg_reading.time_of_reading + timedelta(seconds=5)).utctimetuple())
                    archive_ts = int(reading_plus_5s_ts / self.arcint_secs) * self.arcint_secs
                    avg_reading.time_of_reading = datetime.fromtimestamp(archive_ts, tz=tz.gettz('UTC'))
                json_reading: str = Service.convert_to_json(avg_reading)
                try:
                    start = Service.utc_now()
                    self.database.save_current_reading(avg_reading)
                    log.debug('Saved current reading in %d seconds.' % (Service.utc_now() - start).seconds)
                    log.debug('Saved current reading %s to database.  Reading contains %d samples.'
                        % (Service.datetime_display(avg_reading.time_of_reading), len(readings)))
                except Exception as e:
                    log.critical('Could not save current reading to database: %s: %s' % (self.database, e))
                if event == event.ARCHIVE:
                    try:
                        start = Service.utc_now()
                        self.database.save_archive_reading(avg_reading)
                        log.debug('Saved archive reading in %d seconds.' % (Service.utc_now() - start).seconds)
                        log.info('Added record %s to archive (%d samples).'
                            % (Service.datetime_display(avg_reading.time_of_reading), len(readings)))
                        # Reset readings for new archive cycle.
                        readings.clear()
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

def collect_two_readings_one_second_apart(hostname: str, port: int, timeout_secs:int) -> Tuple[Reading, Reading]:
    try:
        print('collect_two_readings_one_seconds_apart...', end='')
        reading1: Reading = Service.collect_data(hostname, port, timeout_secs)
        sleep(1) # to get a different time (to the second) on reading2
        reading2: Reading = Service.collect_data(hostname, port, timeout_secs)
        print_passed()
        return reading1, reading2
    except Exception as e:
        print_failed(e)
        raise e

def run_tests(service_name: str, hostname: str, port: int, timeout_secs: int) -> None:
    reading, reading2 = collect_two_readings_one_second_apart(hostname, port, timeout_secs)
    test_db_archive_records(service_name, reading)
    test_db_current_records(service_name, reading, reading2)
    sanity_check_reading(reading)
    test_compute_avg(reading)
    test_convert_to_json(reading, reading2)

def sanity_check_sensor(sensor: SensorData, suffix: str) -> None:
    assert sensor.pm1_0_cf_1 >= 0.0 and sensor.pm1_0_cf_1 < 10000.0, 'Reading returned insane pm1_0_atm%s: %f' % (suffix, sensor.pm1_0_cf_1)
    assert sensor.pm1_0_atm >= 0.0 and sensor.pm1_0_atm < 10000.0, 'Reading returned insane pm1_0_atm%s: %f' % (suffix, sensor.pm1_0_atm)
    assert sensor.p_0_3_um >= 0.0 and sensor.p_0_3_um < 10000.0, 'Reading returned insane p_0_3_um %s: %f' % (suffix, sensor.p_0_3_um)
    assert sensor.pm2_5_cf_1 >= 0.0 and sensor.pm2_5_cf_1 < 10000.0, 'Reading returned insane pm2_5_cf_1 %s: %f' % (suffix, sensor.pm2_5_cf_1)
    assert sensor.pm2_5_atm >= 0.0 and sensor.pm2_5_atm < 10000.0, 'Reading returned insane pm2_5_atm %s: %f' % (suffix, sensor.pm2_5_atm)
    assert sensor.p_0_5_um >= 0.0 and sensor.p_0_5_um < 10000.0, 'Reading returned insane p_0_5_um %s: %f' % (suffix, sensor.p_0_5_um)
    assert sensor.pm10_0_cf_1 >= 0.0 and sensor.pm10_0_cf_1 < 10000.0, 'Reading returned insane %s: %f' % (suffix, sensor.pm10_0_cf_1)
    assert sensor.pm10_0_atm >= 0.0 and sensor.pm10_0_atm < 10000.0, 'Reading returned insane pm10_0_atm %s: %f' % (suffix, sensor.pm10_0_atm)
    assert sensor.pm2_5_aqi >= 0 and sensor.pm2_5_aqi < 10000, 'Reading returned insane pm2_5_aqi %s: %d' % (suffix, sensor.pm2_5_aqi)
    # sensor.p25aqic

def sanity_check_reading(reading: Reading) -> None:
    try:
        print('sanity_check_reading....', end='')
        now: datetime = datetime.now(tz=tz.gettz('UTC')) + timedelta(seconds=2) # add 2s buffer as purpleair device time may be off a bit
        one_minute_ago: datetime = datetime.now(tz=tz.gettz('UTC')) - timedelta(seconds=60)

        assert reading.time_of_reading > one_minute_ago and reading.time_of_reading < now, 'Reading returned insane time (%r).' % reading.time_of_reading
        assert reading.current_temp_f > -40.0 and reading.current_temp_f < 160.0, 'Reading returned insane temp (%f).' % reading.current_temp_f
        assert reading.current_humidity >= 0 and reading.current_humidity <= 100, 'Reading returned insane humidity (%d).' % reading.current_humidity
        assert reading.current_dewpoint_f > -40.0 and reading.current_dewpoint_f < 160.0, 'Reading returned insane dewpoint (%f).' % reading.current_dewpoint_f
        assert reading.pressure > 900.0 and reading.pressure < 1084.0, 'Reading returned insane pressure (%f).' % reading.pressure
        sanity_check_sensor(reading.sensor, '')
        if reading.sensor_b is not None:
            sanity_check_sensor(reading.sensor_b, '_b')
        print_passed()
    except Exception as e:
        print_failed(e)

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

        reading1.sensor.pm1_0_cf_1  = 0.12
        reading2.sensor.pm1_0_cf_1  = 0.36

        reading1.sensor.pm1_0_atm   = 0.10
        reading2.sensor.pm1_0_atm   = 0.00

        reading1.sensor.p_0_3_um    = 195.13
        reading2.sensor.p_0_3_um    = 195.17

        reading1.sensor.pm2_5_cf_1  = 0.58
        reading2.sensor.pm2_5_cf_1  = 0.78

        reading1.sensor.pm2_5_atm   = 0.77
        reading2.sensor.pm2_5_atm   = 0.88

        reading1.sensor.p_0_5_um    = 51.85
        reading2.sensor.p_0_5_um    = 47.28

        reading1.sensor.pm10_0_cf_1 = 0.88
        reading2.sensor.pm10_0_cf_1 = 1.03

        reading1.sensor.pm10_0_atm  = 0.99
        reading2.sensor.pm10_0_atm  = 1.05

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

        assert float_eq(avg_reading.sensor.pm1_0_cf_1, 0.24), 'Expected sensor.pm1_0_cf_1: 0.24, got %f.' % avg_reading.sensor.pm1_0_cf_1
        assert float_eq(avg_reading.sensor.pm1_0_atm, 0.05), 'Expected sensor.pm1_0_atm: 0.05, got %f.' % avg_reading.sensor.pm1_0_atm
        assert float_eq(avg_reading.sensor.p_0_3_um, 195.15), 'Expected sensor.p_0_3_um: 195.15, got %f.' % avg_reading.sensor.p_0_3_um
        assert float_eq(avg_reading.sensor.pm2_5_cf_1, 0.68), 'Expected sensor.pm2_5_cf_1: 0.68, got %f.' % avg_reading.sensor.pm2_5_cf_1
        assert float_eq(avg_reading.sensor.pm2_5_atm, 0.825), 'Expected sensor.pm2_5_atm: 0.825, got %f.' % avg_reading.sensor.pm2_5_atm
        assert float_eq(avg_reading.sensor.p_0_5_um, 49.565), 'Expected sensor.p_0_5_um: 49.565, got %f.' % avg_reading.sensor.p_0_5_um
        assert float_eq(avg_reading.sensor.pm10_0_cf_1, 0.955), 'Expected sensor.pm10_0_cf_1: 0.955, got %f.' % avg_reading.sensor.pm10_0_cf_1
        assert float_eq(avg_reading.sensor.pm10_0_atm, 1.02), 'Expected sensor.pm10_0_atm: 1.02, got %f.' % avg_reading.sensor.pm10_0_atm

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
        sensor = SensorData(
            pm1_0_cf_1  = 0.1,
            pm1_0_atm   = 0.2,
            p_0_3_um    = 0.3,
            pm2_5_cf_1  = 0.4,
            pm2_5_atm   = 0.5,
            p_0_5_um    = 0.6,
            pm10_0_cf_1 = 0.7,
            pm10_0_atm  = 0.8,
            pm2_5_aqi   = 9,
            p25aqic     = RGB(10,15,20)),
        sensor_b = SensorData(
            pm1_0_cf_1  = 1.1,
            pm1_0_atm   = 1.2,
            p_0_3_um    = 1.3,
            pm2_5_cf_1  = 1.4,
            pm2_5_atm   = 1.5,
            p_0_5_um    = 1.6,
            pm10_0_cf_1 = 1.7,
            pm10_0_atm  = 1.8,
            pm2_5_aqi   = 19,
            p25aqic     = RGB(110,120,130)))

def float_eq(v1: float, v2: float) -> bool:
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

        expected = '{"DateTime": "2019/12/15T03:43:05z", "current_temp_f": 100, "current_humidity": 90, "current_dewpoint_f": 80, "pressure": 1234.5, "pm1_0_cf_1": 0.1, "pm1_0_atm": 0.2, "p_0_3_um": 0.3, "pm2_5_cf_1": 0.4, "pm2_5_atm": 0.5, "p_0_5_um": 0.6, "pm10_0_cf_1": 0.7, "pm10_0_atm": 0.8, "pm2.5_aqi": 9, "p25aqic": "rgb(10,15,20)", "pm1_0_cf_1_b": 1.1, "pm1_0_atm_b": 1.2, "p_0_3_um_b": 1.3, "pm2_5_cf_1_b": 1.4, "pm2_5_atm_b": 1.5, "p_0_5_um_b": 1.6, "pm10_0_cf_1_b": 1.7, "pm10_0_atm_b": 1.8, "pm2.5_aqi_b": 19, "p25aqic_b": "rgb(110,120,130)"}'

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
    except configobj.ConfigObjError as e:
        raise CantParseConfigFile("Error parsing configuration file %s", config_file)

    return config_dict

def start(args):
    usage = """%prog [--help] [--test | --dump] [--pidfile <pidfile>] <purpleproxy-conf-file>"""
    parser: str = optparse.OptionParser(usage=usage)

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

    debug         : bool           = int(config_dict.get('debug', 0))
    log_to_stdout : bool           = int(config_dict.get('log-to-stdout', 0))
    service_name  : str            = config_dict.get('service-name', 'purple-proxy')
    hostname      : Optional[str]  = config_dict.get('hostname', None)
    port          : int            = int(config_dict.get('port', 80))
    server_port   : int            = int(config_dict.get('server-port', 8000))
    timeout_secs  : int            = int(config_dict.get('timeout-secs', 15))
    pollfreq_secs : int            = int(config_dict.get('poll-freq-secs', 30))
    arcint_secs   : int            = int(config_dict.get('archive-interval-secs', 300))
    db_file       : Optional[str]  = config_dict.get('database-file', None)

    global log
    log = Logger(service_name, log_to_stdout=log_to_stdout, debug_mode=debug)

    log.info('debug         : %r'    % debug)
    log.info('log_to_stdout : %r'    % log_to_stdout)
    log.info('conf_file     : %s'    % conf_file)
    log.info('Version       : %s'    % PURPLEAIR_PROXY_VERSION)
    log.info('host:port     : %s:%s' % (hostname, port))
    log.info('server_port   : %s'    % server_port)
    log.info('timeout_secs  : %d'    % timeout_secs)
    log.info('pollfreq_secs : %d'    % pollfreq_secs)
    log.info('arcint_secs   : %d'    % arcint_secs)
    log.info('db_file       : %s'    % db_file)
    log.info('service_name  : %s'    % service_name)
    log.info('pidfile       : %s'    % options.pidfile)

    if options.test and options.dump:
        parser.error('At most one of --test and --dump can be specified.')

    if options.test is True:
        if not hostname:
            parser.error('hostname must be specified in the config file')
        run_tests(service_name, hostname, port, timeout_secs)
        sys.exit(0)

    if options.dump is True:
        if not db_file:
            parser.error('database-file must be specified in the config file')
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
    if not os.path.exists(db_file):
        log.debug('Creating database: %s' % db_file)
        database: Database = Database.create(db_file)
    else:
        database: Database = Database(db_file)

    purpleproxy_service = Service(hostname, port, timeout_secs, pollfreq_secs,
                                  arcint_secs, database)

    log.debug('Staring server on port %d.' % server_port)
    server.server.serve_requests(server_port, db_file)

    log.debug('Staring mainloop.')
    purpleproxy_service.do_loop()
