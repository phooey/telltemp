#!/usr/bin/env python3
# This program uses tellcore-py to receive sensor data from a Tellstick and write it to the terminal, a file or an SQLite database

import argparse
import csv
import os
import string
import sys
import time

import tellcore.telldus as td
import tellcore.constants as const

class Heartbeat:
    """Prints an alternating heartbeat character to the console on demand"""
    HEARTBEAT_CHARS = ['-', '\\', '|', '/']

    def __init__(self):
       self.current_char = 0
       self.flush_output = False

    def __print_next(self):
        self.erase()
        print(self.__get_next_char(), end="")
        sys.stdout.flush()

    def __get_next_char(self):
        char = self.HEARTBEAT_CHARS[self.current_char]
        self.current_char = (self.current_char + 1) % len(self.HEARTBEAT_CHARS)
        return char

    def dont_flush(self):
        self.flush_output = False

    def clean_up(self):
        for i in range(3):
            self.erase()

    def erase(self):
        if self.flush_output:
            print("\b", end="")
        else:
            self.flush_output = True

    def print_output(self):
        self.__print_next()

class Logger:
    """Dummy logger that does not log anything"""

    def __init__(self, logfile, force_create=False):
        pass

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        pass

    def log_sensor_data(self, protocol, model, id_, datatype, value, timestamp, cid):
        pass

class CSVLogger(Logger):
    """Logs sensor data to a logfile with comma-separated values."""

    def __init__(self, logfile, force_create=False):
        self.logfile = logfile
        self.force_create = force_create

    def __enter__(self):
        self.__open_log_file()
        return self

    def __exit__(self, type, value, traceback):
        self.__close_log_file()

    def __open_log_file(self):
        new_file = not os.path.exists(self.logfile)
        mode = 'w' if self.force_create else 'a'
        try:
            self.csvfile = open(self.logfile, mode, newline='')
            self.csvwriter = csv.writer(self.csvfile)
            if new_file or mode == 'w':
                self.csvwriter.writerow(["Timestamp", "ID", "Temperature", "Humidity"])
        except IOError as error:
            print("Could not open logfile %s: %s" % (self.logfile, error))
            exit(1)

    def __close_log_file(self):
        self.csvfile.close()

    def log_sensor_data(self, protocol, model, id_, datatype, value, timestamp, cid):
        temperature = ''
        humidity = ''
        if datatype == const.TELLSTICK_TEMPERATURE:
            temperature = value
        elif datatype == const.TELLSTICK_HUMIDITY:
            humidity = value
        else:
            return
        self.csvwriter.writerow([timestamp, id_, temperature, humidity])

class SensorData:
    """Container class for sensor data, with a string representation"""
    DATATYPE_MAP = {1: "temperature", 2: "humidity"}

    def __init__(self, protocol, model, id_, datatype, value, timestamp, cid):
        self.protocol, self.model, self.id_, self.datatype, self.value, self.timestamp, self.cid = \
            protocol, model, id_, datatype, value, timestamp, cid

    @staticmethod
    def datatype_to_string(datatype):
        if datatype in SensorData.DATATYPE_MAP:
            return SensorData.DATATYPE_MAP[datatype]
        else:
            return 'unknown'

    def __str__(self):
        # Format: 2015-02-16 13:37:00 SENSOR 123 [protocol/model] temperature/humidity value: -1.23
        return "{timestamp} SENSOR {id_} [{protocol}/{model}] {datatype} value: {value}".format(
            timestamp=time.strftime("%F %T", time.localtime(self.timestamp)),
            id_=self.id_,
            protocol=self.protocol,
            model=self.model,
            datatype=SensorData.datatype_to_string(self.datatype),
            value=self.value)

class SensorEventHandler:
    """Handles sensor data events and prints the data to console or logs it to logfile"""

    def __init__(self, logger, heartbeat, sensors, silent, verbose):
        self.logger = logger
        self.heartbeat = heartbeat
        self.sensors = sensors
        self.silent = silent
        self.verbose = verbose

    def print_sensor_data(self, sensor_data):
        if self.silent: return
        if self.heartbeat: self.heartbeat.erase()
        print(sensor_data)
        if self.heartbeat: self.heartbeat.dont_flush()

    def handle_sensor_event(self, protocol, model, id_, datatype, value, timestamp, cid):
        if not self.sensors or id_ in self.sensors:
            sensor_data = SensorData(protocol, model, id_, datatype, value, timestamp, cid)
            self.print_sensor_data(sensor_data)
            self.logger.log_sensor_data(protocol, model, id_, datatype, value, timestamp, cid)
        elif self.verbose:
            print("Ignoring sensor with ID %d" % id_)

    def handle_loop(self):
        if self.heartbeat: self.heartbeat.print_output()

    def handle_exit(self):
        if self.heartbeat: self.heartbeat.clean_up()

def list_sensors():
    core = td.TelldusCore()
    sensors = core.sensors()
    print("Number of sensors: %d\n" % len(sensors))
    print("{:<5} {:<15} {:<22} {:<8s} {:<8} {}".format(
            "ID", "PROTOCOL", "MODEL", "TEMP", "HUMIDITY", "LAST UPDATED"))

    for sensor in sensors:
        temperature, humidity, timestamp = ["", "", ""]
        if sensor.has_value(const.TELLSTICK_TEMPERATURE):
            sensor_value = sensor.value(const.TELLSTICK_TEMPERATURE)
            temperature = sensor_value.value
            timestamp = sensor_value.timestamp
        if sensor.has_value(const.TELLSTICK_HUMIDITY):
            sensor_value = sensor.value(const.TELLSTICK_TEMPERATURE)
            humidity = sensor_value.value
            if not timestamp:
                timestamp = sensor_value.timestamp
        if not (temperature or humidity):
            continue
        timestamp_formatted = time.strftime("%F %T", time.localtime(timestamp))
        output = "{:<5d} {:<15} {:<22} {:<9s}{:<9s}{}".format(
            sensor.id, sensor.protocol, sensor.model, temperature, humidity, timestamp_formatted)
        print(output)

def sensor_event_loop(sensor_event_handler):
    dispatcher = td.QueuedCallbackDispatcher()
    core = td.TelldusCore(callback_dispatcher=dispatcher)
    core.register_sensor_event(sensor_event_handler.handle_sensor_event)
    try:
        while True:
            core.callback_dispatcher.process_pending_callbacks()
            sensor_event_handler.handle_loop()
            time.sleep(0.5)
    except KeyboardInterrupt:
        sensor_event_handler.handle_exit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Get sensor values from Tellstick temperature and humidity sensors and print them or log them to a file or database')
    parser.add_argument(
            '--heartbeat', '-b', action='store_true', help="Will print an updating character to the terminal while waiting for sensor events.")
    parser.add_argument(
            '--list', '-l', action='store_true', help='List available sensors and exit')
    parser.add_argument(
            '--logfile', '-f', nargs=1, help='File to log sensor data to. Will be created if it does not exist.', metavar='FILENAME')
    parser.add_argument(
            '--logtype', '-t', nargs=1, default='CSV', choices=('CSV', 'SQLite'), help='Type of logfile (Default: CSV (comma-separated values)).')
    parser.add_argument(
            '--overwrite', '-w', action='store_true', help='Will overwrite the logfile if it exists and create a new one.')
    parser.add_argument(
            '--sensors', '-s', type=int, nargs='+', help='Device IDs of sensors to print values from (Default: All)', metavar='SENSOR_ID')
    parser.add_argument(
            '--silent', '-i', action='store_true', help="Will not print anything to the terminal")
    parser.add_argument(
            '--verbose', '-v', action='store_true', help='Print verbose output')

    args = parser.parse_args()

    if args.list:
        list_sensors()
        exit(0)

    sensors = args.sensors
    logfile = args.logfile if args.logfile else None
    logtype = args.logtype if args.logtype else 'CSV'
    silent = args.silent
    heartbeat = Heartbeat() if args.heartbeat else None
    overwrite = args.overwrite
    verbose = args.verbose
    if logfile:
        if logtype == 'CSV':
            logger = CSVLogger
        # TODO: Add SQLite support
        elif logtype == 'SQLite':
            print("SQLite support not yet implemented, sorry.")
            exit(1)
    else:
        logger = Logger

    with logger(logfile, overwrite) as sensor_data_logger:
        sensor_event_handler = SensorEventHandler(sensor_data_logger, heartbeat, sensors, silent, verbose)
        sensor_event_loop(sensor_event_handler)
