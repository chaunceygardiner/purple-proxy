#!/usr/bin/python3

# Copyright (c) 2026 John A Kline
# See the file LICENSE for your full rights.

"""Shared test helpers.  The importing test script must first put
home/purpleproxy/bin on sys.path (running a script from tests/ puts this
directory on the path, so `import fixtures` then works).
"""

import os
import sys
import traceback

from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'home', 'purpleproxy', 'bin'))

from monitor.model import RGB, Reading, SensorData

class InsaneReading(Exception):
    pass

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

failure_count: int = 0

def print_passed() -> None:
    print(bcolors.OKGREEN + 'PASSED' + bcolors.ENDC)

def print_failed(e: Exception) -> None:
    global failure_count
    failure_count += 1
    print(bcolors.FAIL + 'FAILED' + bcolors.ENDC)
    print(traceback.format_exc())

def float_eq(v1: Optional[float], v2: Optional[float]) -> bool:
    if v1 is None and v2 is None:
        return True
    elif v1 is None or v2 is None:
        return False
    else:
        return abs(v1 - v2) < 0.0001

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
