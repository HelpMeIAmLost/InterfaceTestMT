#!/usr/bin/env python3

# coding: utf-8

from __future__ import print_function
from time import sleep
from common_util import *
from pathlib import Path

import can.interfaces.vector
import time
import logging
import threading
import sys
import numpy as np

MIN_PYTHON = (3, 7)


class InterfaceTestMT(object):
    def __init__(self, variant, map_folder, dbc_folder):
        self.variant = variant
        self.map_folder = Path(map_folder)
        self.dbc_folder = Path(dbc_folder)
        # Connect to database for error-checking
        self.conn = create_connection('interface.db')
        # self.c = self.conn.cursor()
        # For XCP
        self.bus = None
        # For CAN
        self.bus1 = None
        self.bus2 = None
        self.bus3 = None
        self.bus4 = None
        self.can_log = None
        self.asc_writer = None
        self.notifier = None
        self.can1_log = None
        self.can1_asc_writer = None
        self.can1_notifier = None
        self.can2_log = None
        self.can2_asc_writer = None
        self.can2_notifier = None
        self.can3_log = None
        self.can3_asc_writer = None
        self.can3_notifier = None
        self.can4_log = None
        self.can4_asc_writer = None
        self.can4_notifier = None

        # configure logging settings
        logging.basicConfig(filename='run.log',
                            filemode='w',
                            level=logging.INFO,
                            format=' %(asctime)s - %(levelname)s - %(message)s')

    def update_internal_signals(self):
        internal_signal_address_count = 0
        if self.conn is not None:
            print('Updating the internal_signals table of the interface database..', flush=True)
            sql_select = '''SELECT link FROM internal_signals ORDER BY link;'''
            rows, internal_signals_count = execute_sql(self.conn, sql_select, select=True, count=True)
            sql_update_internal_signal = '''UPDATE internal_signals
                      SET address = ?
                      WHERE link = ?;'''
            for row in rows:
                address_header_found = False
                with open(self.map_folder / 'application.map', 'r') as fp:
                    for line in fp:
                        if line.find('* Symbols (sorted on name)') != -1:
                            address_header_found = True
                        elif line.find('* Symbols (sorted on address)') != -1:
                            print('{} not found in application.map, '
                                  'could be declared but unreferenced/unused..'.format(row[0]),
                                  flush=True)
                            break

                        if address_header_found:
                            temp_line = line.split()
                            if len(temp_line) > 3:
                                if temp_line[1] == row[0]:
                                    internal_signal_name = row[0]
                                    internal_signal_address = int(temp_line[3], 16)
                                    result = execute_sql(self.conn, sql_update_internal_signal,
                                                         (internal_signal_address, internal_signal_name)
                                                         )
                                    if result < 0:
                                        return result
                                    internal_signal_address_count += 1
                                    break
                fp.close()

            self.conn.commit()
            print('Done!', flush=True)
            print('{} of {} signal addresses were updated'.format(internal_signal_address_count,
                                                                  internal_signals_count), flush=True)
        else:
            print("Error! Cannot create the database connection.")

        return internal_signal_address_count

    def update_external_signals(self):
        external_signal_address_count = 0
        if self.conn is not None:
            print('Updating the external_signals table of the interface database..')
            # Sorting link names will group VP signals from others
            sql_select = '''SELECT * FROM external_signals ORDER BY link;'''
            rows, external_signals_count = execute_sql(self.conn, sql_select, select=True, count=True)

            if self.variant == 'GC7' or self.variant == 'RE7':
                variant_index = 0
            else:
                # HR3
                variant_index = 1
            # DBC list for CAN
            #          CAN 1   CAN 2   CAN 3   CAN 4
            # GC7/RE7    *       *       *      *
            # HR3        *       *       *      *
            dbc_list = [
                ['LOCAL1', 'LOCAL2', 'SA', 'PU'],
                ['LOCAL1', 'LOCAL2', 'LOCAL', 'MAIN']
            ]

            signal_attributes = []
            dbc_name = ''
            for row in rows:
                signal_found = False
                can_ch = 0
                if row[1] == 'CAN' or row[1] == 'DBG':
                    for dbc_name in dbc_list[variant_index]:
                        can_ch += 1
                        signal_found, signal_attributes = self.search_signal_in_dbc(row[0], self.variant,
                                                                                    self.dbc_folder, dbc_name)
                        if signal_found:
                            break
                    # if not signal_found:
                    #     print('{} not found'.format(row[0]))
                else:
                    signal_found, signal_attributes = self.search_signal_in_dbc(row[0], self.variant,
                                                                                self.dbc_folder, 'IPC')
                if signal_found:
                    print('Found a match for {} in {}'.format(row[0], dbc_name))
                    sql_update_external_signal = '''UPDATE external_signals
                              SET node = ?, ch = ?, length = ?, factor = ?, offset = ?, min = ?, max = ?, cycle_ms = ?
                              WHERE link = ?;'''
                    external_signal_data = (signal_attributes[0],
                                            can_ch,
                                            signal_attributes[1][3][
                                                signal_attributes[1][3].find('|')+1:signal_attributes[1][3].find('@')
                                            ],
                                            signal_attributes[1][4][1:signal_attributes[1][4].find(',')],
                                            signal_attributes[1][4][signal_attributes[1][4].find(',') + 1:-1],
                                            signal_attributes[1][5][1:signal_attributes[1][5].find('|')],
                                            signal_attributes[1][5][signal_attributes[1][5].find('|') + 1:-1],
                                            signal_attributes[2],
                                            row[2])
                    execute_sql(self.conn, sql_update_external_signal, external_signal_data)
                    external_signal_address_count += 1
                else:
                    print('{} not found'.format(row[0]))
            # commit_disconnect_database(self.conn)
            self.conn.commit()
            print('Done!')
            print('{} of {} signal addresses were updated'.format(external_signal_address_count,
                                                                  external_signals_count))
        else:
            print("Error! Cannot create the database connection.", flush=True)

        return external_signal_address_count

    @staticmethod
    def search_signal_in_dbc(signal_name, variant, dbc_folder, dbc_name):
        signal_found = False
        signal_attributes = []
        for root, dirs, files in os.walk(dbc_folder):
            if root.find(variant) != -1:
                for file in files:
                    if file.endswith(".dbc") and file.find(dbc_name) != -1:
                        current_dbc_file = open(os.path.join(root, file), 'r')
                        message_header_found = False
                        node_name = ''
                        can_id = ''
                        for line in current_dbc_file:
                            if line.find('BO_ ') == 0 and not signal_found:
                                message_name = line.split()[2][:-1]
                                # Extract the node in the signal name
                                node_in_signal_name = message_name[:-3]
                                node_name = line.split()[4]
                                if node_name == 'EYE' and node_in_signal_name != 'EYE':
                                    continue
                                else:
                                    can_id = line.split()[1]
                                    message_header_found = True
                            if message_header_found and not signal_found:
                                if line.find(' SG_ ') == 0:
                                    # Extract signal name from the list of signals under the same message
                                    dbc_signal_name = line.split()[1]
                                    # Look for this signal name in the external_signals table
                                    if signal_name == dbc_signal_name:
                                        signal_attributes.append(node_name)
                                        signal_attributes.append(line.split())
                                        signal_found = True
                                    # table_match
                                elif line == '\n':
                                    message_header_found = False
                            # Search for message cycle
                            if signal_found and line.find('BA_ \"GenMsgCycleTime\" BO_ {}'.format(can_id)) != -1:
                                signal_attributes.append(line.split()[4][:-1])
                                break
                        current_dbc_file.close()
                    else:
                        continue

                    if signal_found:
                        break
                if signal_found:
                    break
            else:
                continue

        return signal_found, signal_attributes

    def connect(self):
        global start_s

        try:
            self.bus1 = can.ThreadSafeBus(bustype='vector', channel=0, receive_own_messages=False, bitrate=500000,
                                          app_name='CANoe')
            self.bus2 = can.ThreadSafeBus(bustype='vector', channel=1, receive_own_messages=False, bitrate=500000,
                                          app_name='CANoe')
            self.bus3 = can.ThreadSafeBus(bustype='vector', channel=2, receive_own_messages=False, bitrate=500000,
                                          app_name='CANoe')
            self.bus4 = can.ThreadSafeBus(bustype='vector', channel=3, receive_own_messages=False, bitrate=500000,
                                          app_name='CANoe')
            # self.bus2 = can.interface.Bus(bustype='vector', channel=1,
            #                               can_filters=[{"can_id": 0x7e1, "can_mask": 0x7ef, "extended": False}],
            #                               receive_own_messages=True, bitrate=500000, app_name='InterfaceTest')
            self.bus = can.ThreadSafeBus(bustype='vector', channel=1,
                                         can_filters=[{"can_id": 0x7e1, "can_mask": 0x7e1, "extended": False}],
                                         receive_own_messages=True, bitrate=500000, app_name='CANoe')
            # self.bus3 = can.interface.Bus(bustype='vector', channel=2, bitrate=500000, app_name='InterfaceTest')
            # self.bus4 = can.interface.Bus(bustype='vector', channel=3, bitrate=500000, app_name='InterfaceTest')

            # Connect using the can.ini file
            # self.bus1 = Bus(config_section='CAN1')
            # self.bus2 = Bus(config_section='CAN2')
            # self.bus3 = Bus(config_section='CAN3')
            # self.bus4 = Bus(config_section='CAN4')
        except can.CanError as message:
            # logging.error(message)
            print(message, flush=True)
            sys.exit()

        # CAN logger
        self.can_log = open('XCP.asc', 'w+')
        self.asc_writer = can.ASCWriter('XCP.asc')
        self.notifier = can.Notifier(self.bus, [self.asc_writer])
        self.can1_log = open('CAN1.asc', 'w+')
        self.can1_asc_writer = can.ASCWriter('CAN1.asc')
        self.can1_notifier = can.Notifier(self.bus1, [self.can1_asc_writer])
        self.can2_log = open('CAN2.asc', 'w+')
        self.can2_asc_writer = can.ASCWriter('CAN2.asc')
        self.can2_notifier = can.Notifier(self.bus2, [self.can2_asc_writer])
        self.can3_log = open('CAN3.asc', 'w+')
        self.can3_asc_writer = can.ASCWriter('CAN3.asc')
        self.can3_notifier = can.Notifier(self.bus3, [self.can3_asc_writer])
        self.can4_log = open('CAN4.asc', 'w+')
        self.can4_asc_writer = can.ASCWriter('CAN4.asc')
        self.can4_notifier = can.Notifier(self.bus4, [self.can4_asc_writer])
        # self.notifier.add_bus(self.bus1)
        # self.notifier.add_bus(self.bus3)
        # self.notifier.add_bus(self.bus4)

        logging.info("(InterfaceTestMT) Connecting to XCP slave..")
        print('Connecting to XCP slave..', flush=True)
        msg = can.Message(arbitration_id=master_id,
                          data=[0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                          extended_id=False)
        start_s = time.time()
        self.send_once(self.bus, msg)
        sleep(1)

    def send_once(self, bus, msg):
        tries = 0
        bus.send(msg)
        response_message = self.check_xcp_response(bus, slave_id)
        # Retry connect/disconnect request 10 times
        while response_message is None and tries < 10:
            if msg.data[0] == 0xFF:
                logging.info("(InterfaceTestMT) XCP slave connect retry {}".format(tries))
                print('Failed connecting to the XCP slave! Connect retry #{}'.format(tries + 1), flush=True)
            elif msg.data[0] == 0xFE:
                logging.info("(InterfaceTestMT) XCP slave disconnect retry {}".format(tries))
                print('Failed disconnecting from the XCP slave! Disconnect retry #{}'.format(tries + 1), flush=True)
            bus.send(msg)
            response_message = self.check_xcp_response(bus, slave_id)
            tries += 1
            sleep(1)

        if tries == 10:
            # Connect
            if msg.data[0] == 0xFF:
                logging.error("(InterfaceTestMT) Failed to connect to the XCP slave!")
            # Disconnect
            else:
                logging.error("(InterfaceTestMT) Failed to disconnect from the XCP slave!")
            sys.exit()
        else:
            command = hex(msg.data[0])

            # PID: RES
            if response_message.data[0] == 0xFF:
                # Connect
                if msg.data[0] == 0xFF:
                    logging.info('(InterfaceTestMT) Connected to XCP slave through {}'.format(bus))
                # Disconnect
                else:
                    logging.info('(InterfaceTestMT) Disconnected from XCP slave')
                # else:
                #     logging.info('(InterfaceTestMT) Command: {} Response: Success'.format(hex(command)))
            # PID: ERR
            elif response_message.data[0] == 0xFE:
                # response indicates error, report error
                error_code = response_message.data[1]
                # self.c.execute("SELECT * FROM error_array WHERE error_code=?", (error_code,))
                # error_info = self.c.fetchone()
                error_info = execute_sql(self.conn, 'SELECT * FROM error_array WHERE error_code=?',
                                         (error_code,), select=True, just_one=True
                                         )
                if error_info is not None:
                    logging.error('(InterfaceTestMT) Command: {} Response: {} {}'.format(command, error_info[1],
                                                                                         error_info[2].strip()))
                else:
                    logging.error('(InterfaceTestMT) Command: {} Response: {}'.format(command,
                                                                                      hex(response_message.data[1])))
                if msg.data[0] == 0xFF:
                    logging.error('(InterfaceTestMT) Unable to connect to XCP slave through {}'.format(bus))
                else:
                    logging.error('(InterfaceTestMT) Unable to disconnect from XCP slave through {}'.format(bus))
                sys.exit()
            else:
                logging.info('(InterfaceTestMT) Command: {} Response: {}'.format(command,
                                                                                 hex(response_message.data[0])))
                sys.exit()

    def end_logging(self):
        # self.log_to_output.close()
        self.can_log.close()
        logging.shutdown()

    def disconnect(self, bus):
        self.conn.close()
        logging.info('(InterfaceTestMT) Closed SQLite3 database connection')
        self.notifier.stop()
        self.can1_notifier.stop()
        self.can2_notifier.stop()
        self.can3_notifier.stop()
        self.can4_notifier.stop()
        logging.info('(InterfaceTestMT) Stopped CAN bus notifier')
        self.asc_writer.stop()
        self.can1_asc_writer.stop()
        self.can2_asc_writer.stop()
        self.can3_asc_writer.stop()
        self.can4_asc_writer.stop()
        logging.info('(InterfaceTestMT) Stopped ASCWriter')

        msg = can.Message(arbitration_id=master_id,
                          data=[0xFE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                          extended_id=False)
        self.send_once(bus, msg)
        bus.shutdown()
        self.bus1.shutdown()
        self.bus2.shutdown()
        self.bus3.shutdown()
        self.bus4.shutdown()
        logging.info('(InterfaceTestMT) Shut down CAN bus')

    @staticmethod
    def check_xcp_response(bus, xcp_rx_id):
        try:
            # Set timeout for response message
            received_msg = bus.recv(0.05)
            if received_msg is not None:
                if received_msg.arbitration_id == xcp_rx_id:
                    return received_msg

        except can.CanError as message:
            # logging.error(message)
            print(message, flush=True)
            sys.exit()


class UpdateTimeout(threading.Thread):
    def __init__(self, thread_id, name, duration_s):
        # Thread
        threading.Thread.__init__(self)
        self.thread_id = thread_id
        self.name = name
        self.duration = duration_s

    def run(self):
        # The updating of input values is finished
        global g_input_updated
        global g_output_updated

        timeout_ms = 0

        while not g_update_finished:
            # Start the timer
            if g_input_updated:
                sleep(0.001)
                timeout_ms += 1
            else:
                timeout_ms = 0

            if timeout_ms == (self.duration * 1000):
                print('Timer: {}'.format(time.time() - start_s))
                thread_lock.acquire()
                g_output_updated = True
                log_to_output.write("{}  Output signal update failed!\n".format(round(g_input_timestamp_s + 1, 4)))
                thread_lock.release()

                print("{}  Output signal update failed!".format(round(g_input_timestamp_s + 1, 4)), flush=True)


class ApplicationIOStream(threading.Thread):
    def __init__(self, thread_id, name, bus, signal):
        # Thread
        threading.Thread.__init__(self)
        self.thread_id = thread_id
        self.name = name
        self.bus = bus
        self.signal_name = signal['signal']
        self.data_size = signal['data_size']
        self.message = can.Message(arbitration_id=master_id, data=[0xF4, self.data_size, 0x0, 0x0,
                                                                   signal['address'] & 0xFF,
                                                                   (signal['address'] >> 8) & 0xFF,
                                                                   (signal['address'] >> 16) & 0xFF,
                                                                   (signal['address'] >> 24) & 0xFF],
                                   extended_id=False)
        self.cycle = signal['cycle_ms']
        # Connect to database for error-checking
        self.conn = create_connection('interface.db')

        # configure logging settings
        logging.basicConfig(filename='run.log', level=logging.INFO, format=' %(asctime)s - %(levelname)s - %(message)s')

    def run(self):
        global g_update_finished
        global g_value_updated
        global g_expected_value
        global g_input_updated
        global g_input_timestamp_s
        global g_output_updated
        global g_output_timestamp_s
        global g_test_passed
        global g_output_timeout_counter

        logging.info(
            "(ApplicationIOStream) Starting polling thread for {} signal {}...".format(self.name, self.signal_name))

        while not g_update_finished:
            # The request to update the value of the input signal has been sent
            self.bus.send(self.message)

            response_message = self.check_xcp_response(self.bus, slave_id)
            if response_message is not None:
                # PID: RES
                if response_message.data[0] == 0xFF:
                    if g_value_updated and \
                            ((self.name == "input" and not g_input_updated) or
                             (self.name == "output" and g_input_updated and not g_output_updated)):
                        # The input/output signal has been updated, check if they are equal to the requested value
                        actual_value = response_message.data[1]
                        if self.data_size == 2:
                            actual_value = (actual_value << 8) | response_message.data[2]
                        elif self.data_size == 4:
                            actual_value = (actual_value << 8) | response_message.data[2]
                            actual_value = (actual_value << 8) | response_message.data[3]
                            actual_value = (actual_value << 8) | response_message.data[4]
                        if actual_value == g_expected_value:
                            if self.name == "input" and not g_input_updated:
                                # print('In: {}'.format(time.time() - start_s))
                                g_output_timeout_counter = 0
                                thread_lock.acquire()
                                # Input signal update timestamp relative to start of execution, not current time
                                g_input_timestamp_s = response_message.timestamp - start_s
                                g_input_updated = True
                                thread_lock.release()
                                # Log to output file
                                actual_value = hex(actual_value)
                                if self.data_size == 4:
                                    actual_value = hex_to_float(actual_value)
                                    # if actual_value == '0x0':
                                    #     actual_value = 0.0
                                    # else:
                                    #     actual_value = hex_to_float(actual_value)
                                log_to_output.write("{}  {}: {}\n".format(round(g_input_timestamp_s, 4),
                                                                          self.signal_name,
                                                                          actual_value))
                                print("{}  {}: {}".format(
                                    round(g_input_timestamp_s, 4),
                                    self.signal_name,
                                    actual_value,
                                    flush=True)
                                )
                            elif self.name == "output" and g_input_updated and not g_output_updated:
                                # print('Out: {}'.format(time.time() - start_s))
                                thread_lock.acquire()
                                g_output_timestamp_s = response_message.timestamp - start_s
                                timestamp_difference_s = abs(g_output_timestamp_s - g_input_timestamp_s) * 1000
                                if timestamp_difference_s <= self.cycle:
                                    g_test_passed |= True
                                else:
                                    g_test_passed |= False
                                    # thread_lock.release()
                                actual_value = hex(actual_value)
                                if self.data_size == 4:
                                    actual_value = hex_to_float(actual_value)
                                log_to_output.write("{}  {}: {}\n".format(round(g_output_timestamp_s, 4),
                                                                          self.signal_name,
                                                                          actual_value))
                                if g_test_passed:
                                    log_to_output.write("Update successful! ")
                                else:
                                    log_to_output.write("Update failed! ")
                                log_to_output.write(
                                    "Expected Update Cycle: {} ms -> Actual Update Cycle: {} ms\n".format(
                                        self.cycle,
                                        round(timestamp_difference_s))
                                )
                                print("{}  {}: {}".format(
                                    round(g_output_timestamp_s, 4),
                                    self.signal_name,
                                    actual_value,
                                    flush=True)
                                )
                                g_output_updated = True
                                g_output_timeout_counter = 0
                                thread_lock.release()
                        else:
                            if self.name == 'output' and g_input_updated:
                                g_output_timeout_counter += 1

                            if g_output_timeout_counter == 10:
                                current_time = response_message.timestamp - start_s
                                thread_lock.acquire()
                                log_to_output.write(
                                    "{}  Output signal update failed!\n".format(round(current_time, 4))
                                )
                                g_output_updated = True
                                g_output_timeout_counter = 0
                                thread_lock.release()

                                print("{}  Output signal update failed!".format(round(current_time, 4)), flush=True)

            sleep(0.01)

        logging.info("(ApplicationIOStream) Exiting {} polling thread for {}".format(self.name, self.signal_name))

    @staticmethod
    def check_xcp_response(bus, xcp_rx_id):
        try:
            # Set timeout for response message
            received_msg = bus.recv(0.05)
            if received_msg is not None:
                if received_msg.arbitration_id == xcp_rx_id:
                    return received_msg

        except can.CanError as message:
            # logging.error(message)
            print(message, flush=True)
            sys.exit()


class CANIOStream(threading.Thread):
    def __init__(self, thread_id, name, bus, signal_info):
        # Thread
        threading.Thread.__init__(self)
        self.thread_id = thread_id
        self.name = name
        self.bus = bus
        self.signal_info = signal_info
        # Connect to database for error-checking
        self.conn = create_connection('interface.db')

        # configure logging settings
        logging.basicConfig(filename='run.log', level=logging.INFO, format=' %(asctime)s - %(levelname)s - %(message)s')

        # self.start_timestamp = 0.0

        # # Data check
        # if self.name == "input":
        #     self.input_timestamp = 0.0
        #     self.input_value = 0.0
        # else:
        #     self.output_timestamp = 0.0
        #     self.output_value = 0.0

    def run(self):
        # The updating of input values is finished
        global g_update_finished
        # The input value has been updated
        global g_value_updated
        # Expected value
        global g_expected_value
        # Check if the input signal has been updated
        global g_input_updated
        # Timestamp when the input signal has been updated
        global g_input_timestamp_s
        # Check if the output signal has been updated
        global g_output_updated
        # Timestamp when the output signal has been updated
        global g_output_timestamp_s
        # The test passed
        global g_test_passed
        # Initial value of the signal
        global g_initial_value

        logging.info(
            "(CANIOStream) Starting polling thread for {} signal {}...".format(self.name, self.signal_info['signal']))

        while g_update_finished is False:
            # The request to update the value of the input signal has been sent
            received_msg = self.bus.recv()
            if received_msg is not None:
                if received_msg.arbitration_id == self.signal_info['can_id']:
                    actual_value = 0
                    # Get the correct byte number, bit number and bit length
                    current_bit = 0
                    byte_number = self.signal_info['byte']
                    bit_number = self.signal_info['bit']
                    bit_length = self.signal_info['length']
                    # Read the number of bits for the signal, output is raw value
                    while bit_length > 0:
                        actual_value = actual_value | (
                                ((received_msg.data[byte_number] & (0x1 << bit_number)) >> bit_number) << current_bit)
                        bit_length -= 1
                        bit_number += 1
                        if bit_number == 8:
                            bit_number = 0
                            byte_number += 1
                        current_bit += 1

                    # # Convert the raw value to physical value
                    # actual_value = (actual_value * self.signal_info['factor']) + self.signal_info['offset']

                    # Get the initial value of the CAN signal
                    if g_initial_value is None:
                        g_initial_value = actual_value

                    if g_value_updated:
                        # The input/output signal has been updated, check if they are equal to the requested value
                        # Get the correct byte number, bit number and bit length
                        # actual_value = 0
                        # current_bit = 0
                        # byte_number = self.signal_info['byte']
                        # bit_number = self.signal_info['bit']
                        # bit_length = self.signal_info['length']
                        # Read the number of bits for the signal
                        # while bit_length > 0:
                        #     actual_value = actual_value | (
                        #         ((received_msg.data[byte_number] & (0x1 << bit_number)) >> bit_number) << current_bit)
                        #     bit_length -= 1
                        #     bit_number += 1
                        #     if bit_number == 8:
                        #         bit_number = 0
                        #         byte_number += 1
                        #     current_bit += 1
                        #
                        # actual_value = (actual_value * self.signal_info['factor']) + self.signal_info['offset']

                        # Convert the value to raw value before comparing it to the expected value
                        if self.signal_info['data_type'] == 'float':
                            actual_value = int(float_to_hex(actual_value), 16)

                        if actual_value == g_expected_value:
                            if self.name == "input" and not g_input_updated:
                                # print('In: {}'.format(time.time() - start_s))
                                thread_lock.acquire()
                                # Input signal update timestamp relative to start of execution, not current time
                                g_input_timestamp_s = received_msg.timestamp - start_s
                                g_input_updated = True
                                thread_lock.release()
                                # Log to output file
                                actual_value = hex(actual_value)
                                # if self.data_size == 4:
                                #     actual_value = hex_to_float(actual_value)
                                log_to_output.write("{}  {}: {}\n".format(round(g_input_timestamp_s, 4),
                                                                          self.signal_info['signal'],
                                                                          actual_value))
                                print("{}  {}: {}".format(
                                    round(g_input_timestamp_s, 4),
                                    self.signal_info['signal'],
                                    actual_value,
                                    flush=True)
                                )
                            elif self.name == "output" and g_input_updated and not g_output_updated:
                                # print('Out: {}'.format(time.time() - start_s))
                                thread_lock.acquire()
                                g_output_timestamp_s = received_msg.timestamp - start_s
                                if g_output_timestamp_s >= g_input_timestamp_s:
                                    timestamp_difference_s = abs(g_output_timestamp_s - g_input_timestamp_s) * 1000
                                    if timestamp_difference_s <= self.signal_info['cycle_ms']:
                                        g_test_passed |= True
                                    else:
                                        g_test_passed |= False
                                        # thread_lock.release()
                                    # actual_value = hex(actual_value)
                                    log_to_output.write("{}  {}: {}\n".format(round(g_output_timestamp_s, 4),
                                                                              self.signal_info['signal'],
                                                                              hex(actual_value)))
                                    if g_test_passed:
                                        log_to_output.write("Update successful! ")
                                    else:
                                        log_to_output.write("Update failed! ")
                                    log_to_output.write(
                                        "Expected Update Cycle: {} ms -> Actual Update Cycle: {} ms\n".format(
                                            self.signal_info['cycle_ms'],
                                            round(timestamp_difference_s))
                                    )
                                    g_output_updated = True
                                    print("{}  {}: {}".format(
                                        round(g_output_timestamp_s, 4),
                                        self.signal_info['signal'],
                                        hex(actual_value),
                                        flush=True)
                                    )
                                thread_lock.release()
                        # else:
                        #     if self.name == "output" and g_input_updated and not g_output_updated:
                        #         g_output_timestamp_s = received_msg.timestamp - start_s
                        #         thread_lock.acquire()
                        #         g_test_passed &= False
                        #         log_to_output.write("Update failed! ")
                        #         log_to_output.write("The output signal failed to update!\n")
                        #         g_output_updated = True
                        #         thread_lock.release()
                        #         print("{}  {}: {}".format(
                        #             round(g_output_timestamp_s, 4),
                        #             self.signal_info['signal'],
                        #             hex(actual_value),
                        #             flush=True)
                        #         )

            # sleep(0.001)

        logging.info("(CANIOStream) Exiting {} polling thread for {}".format(self.name, self.signal_info['signal']))


class UpdateValues(threading.Thread):
    def __init__(self, thread_id, name, bus, signal, values):
        # Thread
        threading.Thread.__init__(self)
        self.thread_id = thread_id
        self.name = name
        self.bus = bus
        self.signal_name = signal['signal']
        self.input_address = signal['address']
        self.mta_data = [0xF6, 0x00, 0x00, 0x00,
                         self.input_address & 0xFF,
                         (self.input_address >> 8) & 0xFF,
                         (self.input_address >> 16) & 0xFF,
                         (self.input_address >> 24) & 0xFF]
        self.data_size = signal['data_size']
        self.update_values = values
        self.download_data = [0xF0, self.data_size]
        self.conn = create_connection('interface.db')

    def run(self):
        global g_update_finished
        global g_value_updated
        global g_expected_value
        global g_input_updated
        global g_input_timestamp_s
        global g_output_updated
        global g_output_timestamp_s
        global g_test_passed
        # global g_initial_value
        # global g_destination_can

        set_mta = can.Message(arbitration_id=master_id,
                              data=self.mta_data,
                              extended_id=False)

        if g_destination_can:
            # g_initial_value is only updated by the CANIOStream thread
            # Check if it changed and it's equal to the first value in the update_values list (usually max value)
            # Rearrange the list if true
            if g_initial_value is not None and g_initial_value == self.update_values[0]:
                temp_value = self.update_values[0]
                self.update_values[0] = self.update_values[1]
                self.update_values[1] = temp_value

        for data in self.update_values:
            # g_test_passed = False
            if self.data_size == 1:
                self.download_data.append(data & 0xFF)
                self.download_data.append(0x00)
                self.download_data.append(0x00)
                self.download_data.append(0x00)
                self.download_data.append(0x00)
                self.download_data.append(0x00)
            elif self.data_size == 2:
                self.download_data.append((data >> 8) & 0xFF)
                self.download_data.append(data & 0xFF)
                self.download_data.append(0x00)
                self.download_data.append(0x00)
                self.download_data.append(0x00)
                self.download_data.append(0x00)
            elif self.data_size == 4:
                self.download_data.append((data >> 24) & 0xFF)
                self.download_data.append((data >> 16) & 0xFF)
                self.download_data.append((data >> 8) & 0xFF)
                self.download_data.append(data & 0xFF)
                self.download_data.append(0x00)
                self.download_data.append(0x00)
            else:
                logging.error("(UpdateValues) Invalid input signal data_size!")

            cmd_download = can.Message(arbitration_id=master_id,
                                       data=self.download_data,
                                       extended_id=False)
            thread_lock.acquire()
            g_value_updated = False
            g_input_timestamp_s = 0.0
            g_output_timestamp_s = 0.0
            g_input_updated = False
            g_output_updated = False
            thread_lock.release()
            # Keep updating the input signal until the output signal has been updated
            while not g_output_updated:
                if not g_input_updated:
                    self.bus.send(set_mta)
                    response_message = self.check_xcp_response(self.bus, slave_id)
                    if response_message is not None:
                        if response_message.data[0] == 0xFF:
                            # DOWNLOAD
                            self.bus.send(cmd_download)
                            response_message = self.check_xcp_response(self.bus, slave_id)
                            # In XCP, there's no way to know if the response is for the request sent
                            if response_message is not None:
                                thread_lock.acquire()
                                g_expected_value = cmd_download.data[2]
                                if self.data_size == 2:
                                    g_expected_value = (g_expected_value << 8) | cmd_download.data[3]
                                elif self.data_size == 4:
                                    g_expected_value = (g_expected_value << 8) | cmd_download.data[3]
                                    g_expected_value = (g_expected_value << 8) | cmd_download.data[4]
                                    g_expected_value = (g_expected_value << 8) | cmd_download.data[5]
                                g_value_updated = True
                                thread_lock.release()
            # # Try
            # g_input_updated = False
            # g_output_updated = False
            # g_value_updated = False
            # # Try
            sleep(1)
            self.download_data = [0xF0, self.data_size]

        # This thread has finished updating the input signal, end the ApplicationIOStream/CANIOStream threads
        thread_lock.acquire()
        g_update_finished = True
        thread_lock.release()

    @staticmethod
    def check_xcp_response(bus, xcp_rx_id):
        try:
            # Set timeout for response message
            received_msg = bus.recv(0.05)
            if received_msg is not None:
                if received_msg.arbitration_id == xcp_rx_id:
                    return received_msg

        except can.CanError as message:
            # logging.error(message)
            print(message, flush=True)
            sys.exit()


'''
Way of testing:
    Each module/software component (SWC)'s interface signals will be checked through their input
    Example:
        Module under test (destination): VDC
        Module signal: ACCSelectObj
        Source signal: ACCSelectObj (from ACC_Main)
        Procedure:
            Update ACCSelectObj from ACC_Main and check the value of ACCSelectObj in VDC 
'''
if sys.version_info < MIN_PYTHON:
    sys.exit("Python %s.%s or later is required. Please check your Python version.\n" % MIN_PYTHON)

debug = True
parser = argparse.ArgumentParser()
if debug:
    parser.add_argument('-v', dest='variant', help='set to GC7, for debugging', default='GC7')
    parser.add_argument('-r', dest='retries', help='set to 0, for debugging', default=0)
    parser.add_argument('-u', dest='update_address', help='set to no, for debugging', default='no')
else:
    parser.add_argument("variant", help='variant to be tested', choices=['GC7', 'HR3'])
    parser.add_argument('-r', dest='retries', help='number of test retries for failed test results, default is 0',
                        default=0)
    parser.add_argument('-u', dest='update_address',
                        help='option to update internal and external signal information, default is yes',
                        choices=['yes', 'no'],
                        default='yes')
parser.add_argument('-m', dest="map_folder", help='path of the MAP file, default is Build/', default='Build/')
parser.add_argument('-d', dest="dbc_folder", help='path of the DBC folders for each variant, default is DBC/',
                    default='DBC/')
args = parser.parse_args()

if not os.path.exists(args.map_folder):
    print('{} folder not found!'.format(args.map_folder), flush=True)
elif not os.path.exists(os.path.join(args.map_folder, 'application.map')):
    print('application.map file not found in {} folder!'.format(args.map_folder), flush=True)
elif not os.path.exists(args.dbc_folder):
    print('DBC folder not found!', flush=True)
else:
    dbc_variant_folder_found = False
    dbc_files_found = False
    for dbc_root, dbc_dirs, dbc_files in os.walk(args.dbc_folder):
        if str(dbc_root).lower().find(str(args.variant).lower()) != -1:
            dbc_variant_folder_found = True
            for dbc_file in dbc_files:
                if dbc_file.endswith(".dbc"):
                    dbc_files_found = True
                    break
            break

    if not dbc_variant_folder_found:
        print('{} folder not found in the DBC folder!'.format(str(args.variant).upper()), flush=True)
    elif not dbc_files_found:
        print('DBC files for {} not found in the DBC folder!'.format(str(args.variant).upper()), flush=True)
    else:
        max_retry = 0
        if args.retries is not None and args.retries > 0:
            max_retry = args.retries
        # Update the interface database for interface test
        interface_test = InterfaceTestMT(str(args.variant).upper(), args.map_folder, args.dbc_folder)
        # Update internal signal information
        if str(args.update_address).lower() == 'yes':
            if interface_test.update_internal_signals() == 0:
                print('Internal signals information were not updated! Aborting test..', flush=True)
                sys.exit()
            sys.exit()
            # # Update external signal information
            # if interface_test.update_external_signals() == 0:
            #     print('External signals information were not updated! Aborting test..', flush=True)
            #     sys.exit()
            # sys.exit()

        db_connection = create_connection('interface.db')
        if debug:
            # io_pairing, io_pairing_count = execute_sql(db_connection,
            #                                            '''SELECT * FROM io_pairing WHERE (
            #                                            destination_signal='EYE324_6_0_COMPLEMENTARY_IND_C');''',
            #                                            select=True, count=True)
            io_pairing, io_pairing_count = execute_sql(db_connection,
                                                       '''SELECT * FROM io_pairing WHERE (
                                                       source_module<>'CAN' AND
                                                       source_module<>'VP' AND
                                                       destination_module<>'CAN' AND
                                                       destination_module<>'DebugCAN' AND
                                                       destination_module<>'VP'
                                                       ORDER BY destination_module ASC);''',
                                                       select=True, count=True)
        else:
            io_pairing, io_pairing_count = execute_sql(db_connection,
                                                       '''SELECT * FROM io_pairing ORDER BY destination_module ASC;''',
                                                       select=True, count=True)
        passed_count = 0
        tested_count = 0
        skipped_count = 0
        master_id = 0x7E0
        slave_id = 0x7E1

        # Connect to the XCP slave
        interface_test.connect()
        xcp_bus = interface_test.bus
        can_bus = [interface_test.bus1, interface_test.bus2, interface_test.bus3, interface_test.bus4]

        # Values that will be used for testing the interface in the following order:
        # max, min and any value (if applicable)
        update_values = {
            'boolean': [1, 0],
            'uint8': data_type_info(np.uint8),
            'uint16': data_type_info(np.uint16),
            'uint32': data_type_info(np.uint32),
            'sint8': data_type_info(np.int8),
            'sint16': data_type_info(np.int16),
            'sint32': data_type_info(np.int32),
            'float32': data_type_info(np.float32)
                         }
        IF_test_finished = False
        retry_count = 0

        while not IF_test_finished:
            module_name_o = ''
            log_to_output = None
            first_entry = False
            for io_pairing_row in io_pairing:
                if module_name_o != io_pairing_row[3]:
                    if retry_count == 0:
                        if module_name_o != '' and log_to_output is not None:
                            log_to_output.close()
                            print('Finished tests for {}'.format(module_name_o), flush=True)
                        print('Starting tests for {}'.format(io_pairing_row[3]), flush=True)
                    else:
                        if module_name_o != '' and log_to_output is not None:
                            log_to_output.close()
                            print('Finished re-tests for {}'.format(module_name_o), flush=True)
                        print('Re-testing failed test items for {}'.format(io_pairing_row[3]), flush=True)
                    first_entry = True

                # print('Extracting source and destination signal information from the database..')
                # Get more information about the input signal from the database
                source = None
                source_signal_info = None
                if io_pairing_row[1] == 'CAN':
                    source = {'signal': 'CAN_{}'.format(io_pairing_row[2])}
                    source_signal_info = execute_sql(db_connection,
                                                     '''SELECT * FROM external_signals WHERE link=?''',
                                                     (source['signal'],),
                                                     select=True, just_one=True
                                                     )
                elif io_pairing_row[1] != 'VP':  # Input signal is from APP
                    source = {'signal': '{}_{}'.format(io_pairing_row[1], io_pairing_row[2])}
                    source_signal_info = execute_sql(db_connection,
                                                     '''SELECT * FROM internal_signals WHERE link=?''',
                                                     (source['signal'],),
                                                     select=True, just_one=True
                                                     )

                # Get more information about the output signal from the database
                destination = None
                destination_signal_info = None
                if io_pairing_row[3] == 'CAN' or io_pairing_row[3] == 'DebugCAN':
                    if io_pairing_row[3] == 'CAN':
                        destination = {'signal': 'CAN_{}'.format(io_pairing_row[4])}
                    else:
                        destination = {'signal': 'DBG_{}'.format(io_pairing_row[4])}
                    destination_signal_info = execute_sql(db_connection,
                                                          '''SELECT * FROM external_signals WHERE link=?''',
                                                          (destination['signal'],),
                                                          select=True, just_one=True
                                                          )
                else:
                    destination = {'signal': '{}_{}'.format(io_pairing_row[3], io_pairing_row[4])}
                    destination_signal_info = execute_sql(db_connection,
                                                          '''SELECT * FROM internal_signals WHERE link=?''',
                                                          (destination['signal'],),
                                                          select=True, just_one=True
                                                          )
                # Check for test items that need to be skipped to avoid errors (insufficient signal information, etc.)
                if retry_count == 0:
                    skip_this_test_item = False
                    skip_reason = ''
                    # No information found for the source signal
                    if source_signal_info is None:
                        skip_this_test_item = True
                        skip_reason = 'No information found for the source signal in the database'
                    # No information found for the destination signal
                    elif destination_signal_info is None:
                        skip_this_test_item = True
                        skip_reason = 'No information found for the destination signal'
                    # For test items with VP source signals
                    elif io_pairing_row[1] == 'VP':
                        skip_this_test_item = True
                        skip_reason = 'Test items with VP input not yet being tested'
                    # For test items with CAN, VP or DebugCAN destination signals
                    elif io_pairing_row[3] == 'CAN' or io_pairing_row[3] == 'VP' or io_pairing_row[3] == 'DebugCAN':
                        # VP source signal
                        if io_pairing_row[3] == 'VP':
                            skip_this_test_item = True
                            skip_reason = 'Test items with VP output not yet being tested'

                        # No CAN channel assigned
                        if str(destination_signal_info[4]) == '0':
                            skip_this_test_item = True
                            skip_reason = 'CAN channel set to 0 (should be 1, 2, 3 or 4), could be an IPC signal'

                        # CAN output with single precision input
                        elif source_signal_info[4] == 'float32':
                            skip_this_test_item = True
                            skip_reason = 'Floating point input to CAN output signal not yet being tested'

                    elif (io_pairing[1] != 'CAN' and io_pairing[1] != 'VP') and \
                            (io_pairing[3] != 'CAN' and io_pairing[3] != 'VP' and io_pairing[3] != 'DebugCAN'):
                        # No address found for the source signal
                        if int(source_signal_info[2]) == 0:
                            skip_this_test_item = True
                            skip_reason = 'No address found for the source signal'

                        # No address found for the destination signal
                        if int(destination_signal_info[2]) == 0:
                            skip_this_test_item = True
                            skip_reason = 'No address found for the destination signal'

                        # Input and output signals have different data types (APP I/O)
                        if source_signal_info[4] != destination_signal_info[4]:
                            if source_signal_info[4] == 'float32':
                                skip_this_test_item = True
                                skip_reason = 'Single precision input to integer output not yet being tested'
                            elif destination_signal_info[4] == 'float32':
                                skip_this_test_item = True
                                skip_reason = 'Integer input to single precision output not yet being tested'

                        # Arrays, maps and tables for now
                        if source['signal'].find('[') != -1 or destination['signal'].find('[') != -1:
                            skip_this_test_item = True
                            skip_reason = 'Array, maps and tables not yet being tested'

                    if skip_this_test_item:
                        print('{}: Skipped {} -> {} - {}'.format(
                            io_pairing_row[3], io_pairing_row[2], io_pairing_row[4], skip_reason), flush=True)
                        execute_sql(db_connection, '''UPDATE io_pairing SET status=?, result=?, notes=? WHERE id=?;''',
                                    ('Skipped', 'N/A', skip_reason,
                                     io_pairing_row[0]))
                        db_connection.commit()
                        module_name_o = io_pairing_row[3]
                        skipped_count += 1
                        continue

                # Add input signal information in the source dictionary
                # Input from CAN
                if io_pairing_row[1] == 'CAN':
                    # destination['data_type'] = temp_data_type
                    source['can_id'] = int(source_signal_info[3])
                    source['can_ch'] = int(source_signal_info[4])
                    source['byte'] = int(source_signal_info[5])
                    source['bit'] = int(source_signal_info[6])
                    source['length'] = int(source_signal_info[7])
                    source['factor'] = float(source_signal_info[8]) \
                        if str(source_signal_info[8]).find('.') != -1 else int(source_signal_info[8])
                    source['offset'] = int(source_signal_info[9])
                    source['min'] = float(source_signal_info[10]) \
                        if str(source_signal_info[10]).find('.') != -1 else int(source_signal_info[10])
                    source['max'] = float(source_signal_info[11]) \
                        if str(source_signal_info[11]).find('.') != -1 else int(source_signal_info[11])
                    source['cycle_ms'] = int(source_signal_info[12])

                    # Skip if there is insufficient information about the CAN signal (e.g. no min/max values)
                    if (source['min'] == 0 and source['max'] == 0) or source['factor'] == 0:
                        print(
                            '{}: Skipped {} -> {} - Incomplete CAN signal information (e.g. min, max, factor)'.format(
                                io_pairing_row[3], io_pairing_row[2],
                                io_pairing_row[4]), flush=True
                        )
                        execute_sql(db_connection,
                                    '''UPDATE io_pairing SET status=?, result=?, notes=? WHERE id=?;''',
                                    ('Skipped',
                                     'N/A',
                                     'Incomplete CAN signal information (e.g. min, max, factor)',
                                     io_pairing_row[0])
                                    )
                        db_connection.commit()
                        module_name_o = io_pairing_row[3]
                        skipped_count += 1
                        continue
                elif io_pairing_row[1] != 'VP':  # Input from APP
                    source['address'] = int(source_signal_info[2])
                    source['data_size'] = int(source_signal_info[5])
                    source['cycle_ms'] = int(source_signal_info[7])
                    source['data_type'] = source_signal_info[4]

                # Add output signal information in the destination dictionary
                # Output to CAN or DebugCAN
                if io_pairing_row[3] == 'CAN' or io_pairing_row[3] == 'DebugCAN':
                    temp_data_type = 'int'
                    # Check if the factor has a decimal point, signal must be floating-point
                    if str(destination_signal_info[8]).find('.') != -1:
                        temp_data_type = 'float'
                    # Check if the minimum value of the CAN signal is signed
                    elif str(destination_signal_info[10]).find('-') != -1 and \
                            destination_signal_info[9] == '0':
                        temp_data_type = 'sint'
                    else:
                        # Check if the bit length and the factor are 1, signal must be boolean/flag
                        if str(destination_signal_info[8]) == '1' and str(destination_signal_info[11]) == '1':
                            temp_data_type = 'boolean'

                    # -------------------
                    # Start here
                    # -------------------
                    # Unmatched I/O data types (conversion operation should be in the source)
                    if source['data_type'] == 'float32' and temp_data_type.find('int') != -1:
                        print(
                            '{}: Skipped {} -> {} - No tests yet for not matching data types ({} -> {})..'.format(
                                io_pairing_row[3], io_pairing_row[2],
                                io_pairing_row[4], source['data_type'], temp_data_type), flush=True)
                        execute_sql(db_connection,
                                    '''UPDATE io_pairing SET status=?, result=?, notes=? WHERE id=?;''',
                                    ('Skipped', 'N/A',
                                     'No tests yet for not matching data types ({} -> {})'.format(
                                         source['data_type'], temp_data_type),
                                     io_pairing_row[0])
                                    )
                        db_connection.commit()
                        module_name_o = io_pairing_row[3]
                        skipped_count += 1
                        continue

                    destination['data_type'] = temp_data_type
                    destination['can_id'] = int(destination_signal_info[3])
                    destination['can_ch'] = int(destination_signal_info[4])
                    destination['byte'] = int(destination_signal_info[5])
                    destination['bit'] = int(destination_signal_info[6])
                    destination['length'] = int(destination_signal_info[7])
                    destination['factor'] = float(destination_signal_info[8]) \
                        if str(destination_signal_info[8]).find('.') != -1 else int(destination_signal_info[8])
                    destination['offset'] = int(destination_signal_info[9])
                    destination['min'] = float(destination_signal_info[10]) \
                        if str(destination_signal_info[10]).find('.') != -1 else int(destination_signal_info[10])
                    destination['max'] = float(destination_signal_info[11]) \
                        if str(destination_signal_info[11]).find('.') != -1 else int(destination_signal_info[11])
                    destination['cycle_ms'] = int(destination_signal_info[12])

                    # Skip if there is insufficient information about the CAN signal (e.g. no min/max values)
                    if (destination['min'] == 0 and destination['max'] == 0) or destination['factor'] == 0:
                        print(
                            '{}: Skipped {} -> {} - Incomplete CAN signal information (e.g. min, max, factor)'.format(
                                io_pairing_row[3], io_pairing_row[2],
                                io_pairing_row[4]), flush=True
                        )
                        execute_sql(db_connection,
                                    '''UPDATE io_pairing SET status=?, result=?, notes=? WHERE id=?;''',
                                    ('Skipped',
                                     'N/A',
                                     'Incomplete CAN signal information (e.g. min, max, factor)',
                                     io_pairing_row[0])
                                    )
                        db_connection.commit()
                        module_name_o = io_pairing_row[3]
                        skipped_count += 1
                        continue
                else:
                    destination['address'] = int(destination_signal_info[2])
                    destination['data_size'] = int(destination_signal_info[5])
                    destination['cycle_ms'] = int(destination_signal_info[7])
                    destination['data_type'] = destination_signal_info[4]

                # For threading
                # The input signal comes from CAN
                g_source_can = False
                # The output signal is a CAN signal
                g_destination_can = False
                # The updating of input values is finished
                g_update_finished = False
                # The input value has been updated
                g_value_updated = False
                # Expected value
                g_expected_value = 0
                # Check if the input signal has been updated
                g_input_updated = False
                # Timestamp when the input signal has been updated
                g_input_timestamp_s = 0.0
                # Check if the output signal has been updated
                g_output_updated = False
                # Timestamp when the output signal has been updated
                g_output_timestamp_s = 0.0
                # The test passed
                g_test_passed = False
                # CAN signal's initial value
                g_initial_value = None
                # Timeout counter for the output signal
                g_output_timeout_counter = 0

                thread_lock = threading.Lock()
                threads = []

                # This iteration is the first entry in the output file
                if first_entry:
                    # Create a new one/overwrite an existing one if this iteration is not a re-test
                    # Otherwise, append to an existing file or create a new one
                    if retry_count == 0:
                        log_to_output = open('output_{}.txt'.format(io_pairing_row[3]), 'w+')
                    else:
                        log_to_output = open('output_{}.txt'.format(io_pairing_row[3]), 'a+')
                    first_entry = False

                # Create new threads
                # # Set update timeout in seconds
                # thread0 = UpdateTimeout(0, "timeout", 1)
                if io_pairing_row[1] == 'CAN':
                    # Input signal is from CAN, start the CAN stream
                    thread1 = CANIOStream(1, 'input', can_bus[source['can_ch']-1], source)
                else:
                    # ApplicationIOStream(self, thread_id, name, bus, signal_name, signal_address, data_size, cycle):
                    thread1 = ApplicationIOStream(1, "input", xcp_bus, source)

                # Determine the update values that will be set to the input signal
                # APP -> CAN/DebugCAN
                if io_pairing_row[3] == 'CAN' or io_pairing_row[3] == 'DebugCAN':
                    g_destination_can = True
                    # Set the update values based on the min, max and factor of the CAN signal
                    if destination['data_type'] == 'boolean':
                        update_values['others'] = [1, 0]
                    else:
                        # Convert min, max and factor to raw values
                        max_value = physical_to_raw(destination['max'], destination['factor'], destination['offset'])
                        min_value = physical_to_raw(destination['min'], destination['factor'], destination['offset'])
                        any_value = physical_to_raw(destination['factor'], destination['factor'], destination['offset'])

                        # Mask the values depending on the input data size
                        if source['data_size'] == 1:
                            max_value = max_value & 0xFF
                            min_value = min_value & 0xFF
                            any_value = any_value & 0xFF
                        elif source['data_size'] == 2:
                            max_value = max_value & 0xFFFF
                            min_value = min_value & 0xFFFF
                            any_value = any_value & 0xFFFF
                        elif source['data_size'] == 4:
                            max_value = max_value & 0xFFFFFFFF
                            min_value = min_value & 0xFFFFFFFF
                            any_value = any_value & 0xFFFFFFFF
                        # Add the update values to the dictionary
                        update_values['others'] = [max_value, min_value, any_value]
                    # Start the output stream thread
                    thread2 = CANIOStream(2, 'output', can_bus[destination['can_ch']-1], destination)
                    # Start the update values thread
                    thread3 = UpdateValues(3, "update", xcp_bus, source, update_values['others'])
                else:  # APP -> APP
                    thread2 = ApplicationIOStream(2, "output", xcp_bus, destination)
                    thread3 = UpdateValues(3, "update", xcp_bus, source, update_values[source['data_type']])

                # Start new threads
                print('{}: Testing {} -> {}'.format(io_pairing_row[3] if not g_destination_can else io_pairing_row[1],
                                                    io_pairing_row[2],
                                                    io_pairing_row[4]), flush=True)
                # thread0.start()
                thread1.start()
                thread2.start()
                sleep(3)
                thread3.start()

                # Add threads to thread list
                # threads.append(thread0)
                threads.append(thread1)
                threads.append(thread2)
                threads.append(thread3)

                # Wait for all threads to complete
                for t in threads:
                    t.join()

                if g_test_passed:
                    # Output to database
                    execute_sql(db_connection, '''UPDATE io_pairing SET status=?, result=?, notes=? WHERE id=?;''',
                                ('Done', 'Passed', '', io_pairing_row[0]))
                    db_connection.commit()
                    print("{}: {} -> {} PASSED".format(io_pairing_row[3], io_pairing_row[2], io_pairing_row[4]),
                          flush=True)
                    passed_count += 1
                else:
                    # Output to database
                    execute_sql(db_connection, '''UPDATE io_pairing SET status=?, result=?, notes=? WHERE id=?;''',
                                ('Done', 'Failed', 'Please check the output_{}.txt file'.format(io_pairing_row[3]),
                                 io_pairing_row[0]))
                    db_connection.commit()
                    print("{}: {} -> {} FAILED".format(io_pairing_row[3], io_pairing_row[2], io_pairing_row[4]),
                          flush=True)

                if retry_count == 0:
                    tested_count += 1
                module_name_o = io_pairing_row[3]

            if not first_entry and log_to_output is not None:
                log_to_output.close()

            print('-----------------------------------', flush=True)
            print('', flush=True)
            if max_retry > 0:
                retry_count += 1
                if retry_count > max_retry:
                    IF_test_finished = True
                else:
                    io_pairing = execute_sql(db_connection,
                                             '''SELECT * FROM io_pairing 
                                             WHERE result='Failed' 
                                             ORDER BY destination_module;''',
                                             select=True)
                    print('The script is set to re-test failed test items {} time(s)'.format(max_retry), flush=True)
                    print('Running retry {} of {}..'.format(retry_count, max_retry), flush=True)
            else:
                IF_test_finished = True

        db_connection.close()
        # Disconnect from XCP slave
        interface_test.disconnect(xcp_bus)
        # End logging (ASC and info)
        interface_test.end_logging()

        # print('', flush=True)
        print('Done!', flush=True)
        print('', flush=True)
        print('Test Results', flush=True)
        print('-----------------------------------', flush=True)
        print('{} of {} items tested'.format(tested_count, io_pairing_count), flush=True)
        print('{} Passed'.format(passed_count) +
              ', including {} re-tests'.format(max_retry) if max_retry > 0 else '',
              flush=True)
        print('{} Failed'.format(tested_count - passed_count) +
              ', including {} re-tests'.format(max_retry) if max_retry > 0 else '',
              flush=True)
        print('{} Skipped'.format(skipped_count), flush=True)
