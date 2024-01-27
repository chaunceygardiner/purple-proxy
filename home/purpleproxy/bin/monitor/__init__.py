#!/usr/bin/python3

# Copyright (c) 2020 John A Kline
# See the file LICENSE for your full rights.

import syslog

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
