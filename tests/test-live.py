#!/usr/bin/python3

# Copyright (c) 2020-2026 John A Kline
# See the file LICENSE for your full rights.

"""Live-sensor self-tests (previously `purpleproxyd --test`): collect real
readings from the PurpleAir sensor named in the conf file, then exercise the
database, averaging, sanity checks and json conversion with them.

    python3 tests/test-live.py [<purpleproxy-conf-file>]

The conf file defaults to home/purpleproxy/purpleproxy.conf.  Requires a
reachable sensor.  Exits non-zero if any test fails.
"""

import copy
import os
import sys
import tempfile

import requests

from datetime import datetime, timedelta
from dateutil import tz
from dateutil.parser import parse
from time import sleep
from typing import List, Tuple

import fixtures

from fixtures import InsaneReading, create_test_reading, float_eq, print_failed, print_passed
from monitor.database import Database
from monitor.model import Reading, convert_to_json
from monitor.service import Service

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

        convert_to_json(reading1)
        convert_to_json(reading2)

        tzinfos = {'CST': tz.gettz("UTC")}
        reading = create_test_reading(parse('2019/12/15T03:43:05UTC', tzinfos=tzinfos))
        json_reading: str = convert_to_json(reading)

        expected = '{"DateTime": "2019/12/15T03:43:05z", "current_temp_f": 100, "current_humidity": 90, "current_dewpoint_f": 80, "pressure": 1234.5, "current_temp_f_680": 105, "current_humidity_680": 95, "current_dewpoint_f_680": 85, "pressure_680": 1235.6, "gas_680": 42.0, "pm1_0_cf_1": 0.1, "pm1_0_atm": 0.2, "pm2_5_cf_1": 0.3, "pm2_5_atm": 0.4, "pm10_0_cf_1": 0.5, "pm10_0_atm": 0.6, "p_0_3_um": 0.7, "p_0_5_um": 0.8, "p_1_0_um": 0.9, "p_2_5_um": 0.91, "p_5_0_um": 0.92, "p_10_0_um": 0.93, "pm2.5_aqi": 9, "p25aqic": "rgb(10,15,20)", "pm1_0_cf_1_b": 1.1, "pm1_0_atm_b": 1.2, "pm2_5_cf_1_b": 1.3, "pm2_5_atm_b": 1.4, "pm10_0_cf_1_b": 1.5, "pm10_0_atm_b": 1.6, "p_0_3_um_b": 1.7, "p_0_5_um_b": 1.8, "p_1_0_um_b": 1.9, "p_2_5_um_b": 1.91, "p_5_0_um_b": 1.92, "p_10_0_um_b": 1.93, "pm2.5_aqi_b": 19, "p25aqic_b": "rgb(110,120,130)"}'

        assert json_reading == expected, 'Expected json: %s, found: %s' % (expected, json_reading)
        print_passed()
    except Exception as e:
        print_failed(e)

def main() -> None:
    import configobj
    default_conf = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'home', 'purpleproxy', 'purpleproxy.conf')
    conf_file = sys.argv[1] if len(sys.argv) > 1 else default_conf
    config_dict = configobj.ConfigObj(conf_file, file_error=True, encoding='utf-8')

    service_name  : str = config_dict.get('service-name', 'purple-proxy')
    hostname      : str = config_dict.get('hostname', '')
    port          : int = int(config_dict.get('port', 80))
    timeout_secs  : int = int(config_dict.get('timeout-secs', 25))
    long_read_secs: int = int(config_dict.get('long-read-secs', 10))

    if not hostname:
        print('hostname must be specified in the config file: %s' % conf_file)
        sys.exit(2)

    run_tests(service_name, hostname, port, timeout_secs, long_read_secs)

    if fixtures.failure_count:
        print('%d FAILURES' % fixtures.failure_count)
        sys.exit(1)

if __name__ == '__main__':
    main()
