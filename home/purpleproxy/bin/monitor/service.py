#!/usr/bin/python3

# Copyright (c) 2022-2026 John A Kline
# See the file LICENSE for your full rights.

"""The polling service: read the sensor every poll-freq-secs, sanity check
each reading, maintain rolling averages, and write current/two-minute/archive
records to the database.
"""

import calendar
import copy
import gc
import time

import requests

from datetime import datetime
from datetime import timedelta
from dateutil import tz
from time import sleep
from typing import Any, List, Optional, Tuple

from monitor import log
from monitor.database import Database
from monitor.model import RGB, Reading, SensorData, datetime_from_reading, read_sensor

class Service(object):
    def __init__(self, hostname: str, port: int, timeout_secs: int,
                 long_read_secs: int, pollfreq_secs: int,
                 pollfreq_offset: int, arcint_secs: int,
                 gc_interval_secs: int, database: Database) -> None:
        self.hostname = hostname
        self.port = port
        self.timeout_secs     = timeout_secs
        self.long_read_secs   = long_read_secs
        self.pollfreq_secs    = pollfreq_secs
        self.pollfreq_offset  = pollfreq_offset
        self.arcint_secs      = arcint_secs
        self.gc_interval_secs = gc_interval_secs
        self.database         = database

        log.debug('Service created')

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
    def parse_response(response: requests.Response) -> Reading:
        try:
            # convert to json
            j = response.json()
            reading: Reading = Reading(
                time_of_reading        = datetime_from_reading(j['DateTime']),
                current_temp_f         = j['current_temp_f'],
                current_humidity       = j['current_humidity'],
                current_dewpoint_f     = j['current_dewpoint_f'],
                pressure               = j['pressure'],
                current_temp_f_680     = j['current_temp_f_680'] if 'current_temp_f_680' in j.keys() else None,
                current_humidity_680   = j['current_humidity_680'] if 'current_humidity_680' in j.keys() else None,
                current_dewpoint_f_680 = j['current_dewpoint_f_680'] if 'current_dewpoint_f_680' in j.keys() else None,
                pressure_680           = j['pressure_680'] if 'pressure_680' in j.keys() else None,
                gas_680                = j['gas_680'] if 'gas_680' in j.keys() else None,
                sensor                 = read_sensor(j, ''),
                # Read sensor_b if one exists.
                sensor_b               = read_sensor(j, '_b') if 'pm1_0_cf_1_b' in j.keys() else None)
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
    def utc_now() -> datetime:
        return datetime.now(tz=tz.gettz('UTC'))

    @staticmethod
    def is_int(value: Any) -> bool:
        # bool is a subclass of int; a JSON true/false must not pass as an int reading.
        return isinstance(value, int) and not isinstance(value, bool)

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
        if not Service.is_int(sensor_data.pm2_5_aqi):
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
        if not Service.is_int(reading.current_temp_f):
            return False, 'current_temp_f not instance of int'
        if not Service.is_int(reading.current_humidity):
            return False, 'current_humidity not instance of int'
        if not Service.is_int(reading.current_dewpoint_f):
            return False, 'current_dewpoint_f not instance of int'
        if not isinstance(reading.pressure, float):
            return False, 'pressure not instance of float'
        if reading.current_temp_f_680 is not None and not Service.is_int(reading.current_temp_f_680):
            return False, 'current_temp_f_680 not instance of int'
        if reading.current_humidity_680 is not None and not Service.is_int(reading.current_humidity_680):
            return False, 'current_humidity_680 not instance of int'
        if reading.current_dewpoint_f_680 is not None and not Service.is_int(reading.current_dewpoint_f_680):
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

    def secs_to_next_poll(self) -> float:
        now = time.time()
        next_poll_event = int(now / self.pollfreq_secs) * self.pollfreq_secs + self.pollfreq_secs
        secs_to_event = next_poll_event - now
        # Add pollfreq_offset to computed next event.
        secs_to_event += self.pollfreq_offset
        log.debug('Next poll in %f seconds' % secs_to_event)
        return secs_to_event

    def next_archive_boundary(self) -> float:
        return (int(time.time() / self.arcint_secs) + 1) * self.arcint_secs

    def do_loop(self) -> None:
        archive_readings   : List[Reading] = []
        two_minute_readings: List[Reading] = []

        first_time: bool = True
        log.debug('Started main loop.')
        session: Optional[requests.Session] = None
        next_gc_ts: float = time.time() + self.gc_interval_secs
        # The archive record is written by the first poll at or past the
        # boundary (rather than scheduling ARCHIVE as its own event), so a
        # slow sensor read that straddles the boundary delays the record
        # instead of skipping it.
        next_arc_ts: float = self.next_archive_boundary()

        while True:
            if first_time:
                first_time = False
            else:
                # sleep until next poll
                sleep(self.secs_to_next_poll())

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
            # if at or past an archive boundary, also write an archive record
            archive_due: bool = time.time() >= next_arc_ts
            if archive_due:
                next_arc_ts = self.next_archive_boundary()
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

            # Periodically collect cyclic garbage, but only on a non-archive
            # poll: the loop is about to go idle, and the pause never stacks
            # on top of archive processing.
            if self.gc_interval_secs != 0 and not archive_due and time.time() >= next_gc_ts:
                gc_start = time.time()
                unreachable: int = gc.collect()
                log.info('Garbage collected %d objects in %.3f seconds.' % (unreachable, time.time() - gc_start))
                next_gc_ts = time.time() + self.gc_interval_secs
