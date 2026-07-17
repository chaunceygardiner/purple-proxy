#!/usr/bin/python3

# Copyright (c) 2022-2026 John A Kline
# See the file LICENSE for your full rights.

"""sqlite storage for readings.  Rows are keyed by record type; CURRENT and
TWO_MINUTE are single-row record types (delete+insert), ARCHIVE accumulates.
"""

import os
import sqlite3

from datetime import datetime
from dateutil import tz
from itertools import islice
from json import dumps
from typing import Any, Iterator, List, Optional, Tuple

from monitor import log
from monitor.model import RGB, Reading, RecordType, Sensor, SensorData, convert_to_json

class DatabaseAlreadyExists(Exception):
    pass

class UnexpectedSensorRecord(Exception):
    pass

class Database(object):
    def __init__(self, db_file: str):
        self.db_file = db_file

    @staticmethod
    def create(db_file: str) -> 'Database':
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
                ' VALUES(?, ?, ?, ?, ?, ?);')
            insert_reading_values: Tuple[Any, ...] = (record_type, stamp, r.current_temp_f, r.current_humidity, r.current_dewpoint_f, r.pressure)
        else: # A PurpleAir Flex or Zen
            if r.current_temp_f_680 is not None and r.current_humidity_680 is not None and r.current_dewpoint_f_680 is not None and r.pressure_680 is not None:
                insert_reading_sql = ('INSERT INTO Reading ('
                    ' record_type, timestamp, current_temp_f, current_humidity, current_dewpoint_f, pressure, '
                    ' current_temp_f_680, current_humidity_680, current_dewpoint_f_680, pressure_680, gas_680)'
                    ' VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);')
                insert_reading_values = (
                    record_type, stamp, r.current_temp_f, r.current_humidity, r.current_dewpoint_f, r.pressure,
                    r.current_temp_f_680, r.current_humidity_680, r.current_dewpoint_f_680, r.pressure_680, r.gas_680)
            else:
                log.error('Skipping saving reading(%s): gas_680 present, but temp_f_680, humidity_680, dewpoint_f_680 or pressure_680 is None: %r' % (record_type, r))
                return
        with sqlite3.connect(self.db_file, timeout=15) as conn:
            cursor = conn.cursor()
            # if a current record or two minute record, delete previous current.
            if record_type == RecordType.CURRENT or record_type == RecordType.TWO_MINUTE:
                cursor.execute('DELETE FROM Reading where record_type = ?;', (record_type,))
                cursor.execute('DELETE FROM Sensor where record_type = ?;', (record_type,))
            # Now insert.
            cursor.execute(insert_reading_sql, insert_reading_values)
            # Save the sensor reading(s)
            self.save_sensor(cursor, record_type, stamp, Sensor.A, r.sensor)
            if r.sensor_b is not None:
                self.save_sensor(cursor, record_type, stamp, Sensor.B, r.sensor_b)

    def save_sensor(self, cursor: sqlite3.Cursor, record_type: int, stamp: int, sensor_number: int, sensor: SensorData) -> None:
        insert_sensor_sql: str = ('INSERT INTO Sensor ('
            ' record_type, timestamp, sensor,'
            ' pm1_0_cf_1, pm1_0_atm, pm2_5_cf_1, pm2_5_atm, pm10_0_cf_1, pm10_0_atm,'
            ' p_0_3_um, p_0_5_um, p_1_0_um, p_2_5_um, p_5_0_um, p_10_0_um,'
            ' pm2_5_aqi, p25aqi_red, p25aqi_green, p25aqi_blue)'
            ' VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);')
        insert_sensor_values: Tuple[Any, ...] = (
            record_type, stamp, sensor_number, sensor.pm1_0_cf_1, sensor.pm1_0_atm,
            sensor.pm2_5_cf_1, sensor.pm2_5_atm, sensor.pm10_0_cf_1, sensor.pm10_0_atm,
            sensor.p_0_3_um, sensor.p_0_5_um, sensor.p_1_0_um, sensor.p_2_5_um, sensor.p_5_0_um, sensor.p_10_0_um,
            sensor.pm2_5_aqi, sensor.p25aqic.red, sensor.p25aqic.green, sensor.p25aqic.blue)
        cursor.execute(insert_sensor_sql, insert_sensor_values)

    def fetch_current_readings(self) -> Iterator[Reading]:
        return self.fetch_readings(RecordType.CURRENT, 0)

    def fetch_current_reading_as_json(self) -> str:
        for reading in self.fetch_current_readings():
            log.info('fetch-current-record')
            return convert_to_json(reading)
        return '{}'

    def fetch_two_minute_readings(self) -> Iterator[Reading]:
        return self.fetch_readings(RecordType.TWO_MINUTE, 0)

    def fetch_two_minute_reading_as_json(self) -> str:
        for reading in self.fetch_two_minute_readings():
            log.info('fetch-two-minute-record')
            return convert_to_json(reading)
        return '{}'

    def get_earliest_timestamp_as_json(self) -> str:
        select: str = ('SELECT timestamp FROM Reading WHERE record_type = ?'
            ' ORDER BY timestamp LIMIT 1')
        log.debug('get-earliest-timestamp: select: %s' % select)
        resp = {}
        with sqlite3.connect(self.db_file, timeout=5) as conn:
            cursor = conn.cursor()
            for row in cursor.execute(select, (RecordType.ARCHIVE,)):
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
            contents += convert_to_json(reading)
        log.info('fetch-archive-records')
        return '[  %s ]' % contents

    def fetch_readings(self, record_type: int, since_ts: int = 0, max_ts: Optional[int] = None, limit: Optional[int] = None) -> Iterator[Reading]:
        readings: Iterator[Reading] = self.fetch_readings_unlimited(record_type, since_ts, max_ts)
        # A reading spans one Sensor row (or two for dual sensor devices), so
        # the limit must count assembled readings, not rows in the SQL (a SQL
        # LIMIT could even split a dual sensor reading, dropping its B half).
        return islice(readings, limit) if limit is not None else readings

    def fetch_readings_unlimited(self, record_type: int, since_ts: int = 0, max_ts: Optional[int] = None) -> Iterator[Reading]:
        select: str = ('SELECT Reading.timestamp, current_temp_f,'
            ' current_humidity, current_dewpoint_f, pressure, current_temp_f_680, current_humidity_680,'
            ' current_dewpoint_f_680, pressure_680, gas_680, sensor,'
            ' pm1_0_cf_1, pm1_0_atm, pm2_5_cf_1, pm2_5_atm, pm10_0_cf_1, pm10_0_atm,'
            ' p_0_3_um, p_0_5_um, p_1_0_um, p_2_5_um, p_5_0_um, p_10_0_um,'
            ' pm2_5_aqi, p25aqi_red, p25aqi_green,'
            ' p25aqi_blue FROM Reading, Sensor WHERE Reading.record_type = ?'
            ' AND Sensor.record_type = ? AND Reading.timestamp = Sensor.timestamp'
            ' AND Reading.timestamp > ?')
        select_values: List[Any] = [record_type, record_type, since_ts]
        if max_ts is not None:
            select += ' AND Reading.timestamp <= ?'
            select_values.append(max_ts)
        # Order on sensor so each reading's A row arrives before its B row,
        # which the pairing logic below depends on.
        select += ' ORDER BY Reading.timestamp, Sensor.sensor;'
        log.debug('fetch_readings: select: %s, values: %r' % (select, select_values))
        with sqlite3.connect(self.db_file, timeout=5) as conn:
            cursor = conn.cursor()
            reading = None
            for row in cursor.execute(select, select_values):
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
