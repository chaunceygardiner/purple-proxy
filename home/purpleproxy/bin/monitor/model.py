#!/usr/bin/python3

# Copyright (c) 2022-2026 John A Kline
# See the file LICENSE for your full rights.

"""The data model: sensor readings, and their conversions to and from json
(both the json the PurpleAir device serves and the json this proxy serves).
"""

from dataclasses import dataclass
from datetime import datetime
from dateutil import tz
from dateutil.parser import parse
from json import dumps
from typing import Any, Dict, List, Optional

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

class RecordType:
    CURRENT   : int = 0
    ARCHIVE   : int = 1
    TWO_MINUTE: int = 2

class Sensor:
    A: int = 0
    B: int = 1

def datetime_from_reading(dt_str: str) -> datetime:
    time_of_reading_str: str = dt_str.replace('z', 'UTC')
    tzinfos = {'CST': tz.gettz("UTC")}
    return parse(time_of_reading_str, tzinfos=tzinfos)

def convert_str_to_rgb(rgb_string) -> RGB:
    # rgb(61,234,0)
    rgb_string = rgb_string.replace('rgb(', '')
    # 61,234,0)
    rgb_string = rgb_string.replace(')', '')
    # 61,234,0
    rgbs: List[str] = rgb_string.split(',')
    # [61, 234, 0]
    return RGB(red=int(rgbs[0]), green=int(rgbs[1]), blue=int(rgbs[2]))

def convert_rgb_to_str(rgb: RGB) -> str:
    return 'rgb(%d,%d,%d)' % (rgb.red, rgb.green, rgb.blue)

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
        p25aqic            = convert_str_to_rgb(j['p25aqic' + suffix]))

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
        'p25aqic' + suffix     : convert_rgb_to_str(sensor.p25aqic)}
    return sensor_dict

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

    reading_dict.update(sensor_to_dict(reading.sensor, ''))
    if reading.sensor_b is not None:
        reading_dict.update(sensor_to_dict(reading.sensor_b, '_b'))

    return dumps(reading_dict)
