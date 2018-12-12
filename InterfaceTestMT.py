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

MIN_PYTHON = (3, 7)


class InterfaceTestMT(object):
    def __init__(self, variant, map_folder, dbc_folder):
        self.variant = variant
        self.map_folder = Path(map_folder)
        self.dbc_folder = Path(dbc_folder)
        # Connect to database for error-checking
        self.conn = create_connection('interface.db')
        # self.c = self.conn.cursor()
        self.bus = None
        self.can_log = None
        self.asc_writer = None
        self.notifier = None

        # configure logging settings
        logging.basicConfig(filename='run.log',
                            filemode='w',
                            level=logging.INFO,
                            format=' %(asctime)s - %(levelname)s - %(message)s')

    def update_internal_signals(self):
        # conn = create_connection('interface.db')
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
                                                (internal_signal_address, internal_signal_name))
                                    if result < 0:
                                        return result
                                    internal_signal_address_count += 1
                                    break
                fp.close()
            # commit_disconnect_database(self.conn)
            self.conn.commit()
            print('Done!', flush=True)
            print('{} of {} signal addresses were updated'.format(internal_signal_address_count,
                                                                  internal_signals_count), flush=True)
        else:
            print("Error! Cannot create the database connection.")

        return internal_signal_address_count

    def update_external_signals(self):
        # conn = create_connection('interface.db')
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
                else: # VP
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
            # self.bus1 = can.interface.Bus(bustype='vector', channel=0, bitrate=500000, app_name='InterfaceTest')
            # self.bus2 = can.interface.Bus(bustype='vector', channel=1, receive_own_messages=True, bitrate=500000,
            #                               app_name='InterfaceTest')
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
        self.can_log = open('log.asc', 'w+')
        self.asc_writer = can.ASCWriter('log.asc')
        self.notifier = can.Notifier(self.bus, [self.asc_writer])
        # self.notifier.add_bus(self.bus1)
        # self.notifier.add_bus(self.bus3)
        # self.notifier.add_bus(self.bus4)

        logging.info("(InterfaceTestMT) Connecting to XCP slave..")
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
            elif msg.data[0] == 0xFE:
                logging.info("(InterfaceTestMT) XCP slave disconnect retry {}".format(tries))
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
        logging.info('(InterfaceTestMT) Stopped CAN bus notifier')
        self.asc_writer.stop()
        logging.info('(InterfaceTestMT) Stopped ASCWriter')

        msg = can.Message(arbitration_id=master_id,
                          data=[0xFE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                          extended_id=False)
        self.send_once(bus, msg)
        bus.shutdown()
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


class IOStream(threading.Thread):
    def __init__(self, thread_id, name, bus, signal_name, signal_address, data_size, cycle):
        # Thread
        threading.Thread.__init__(self)
        self.thread_id = thread_id
        self.name = name
        self.bus = bus
        self.signal_name = signal_name
        self.data_size = data_size
        self.message = can.Message(arbitration_id=master_id, data=[0xF4, self.data_size, 0x0, 0x0,
                                                                   signal_address & 0xFF,
                                                                   (signal_address >> 8) & 0xFF,
                                                                   (signal_address >> 16) & 0xFF,
                                                                   (signal_address >> 24) & 0xFF],
                                   extended_id=False)
        self.cycle = cycle
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

        logging.info(
            "(IOStream) Starting polling thread for {} signal {}...".format(self.name, self.signal_name))

        while g_update_finished is False:
            # The request to update the value of the input signal has been sent
            self.bus.send(self.message)

            response_message = self.check_xcp_response(self.bus, slave_id)
            if response_message is not None:
                # PID: RES
                if response_message.data[0] == 0xFF:
                    if g_value_updated:
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
                                thread_lock.acquire()
                                # Input signal update timestamp relative to start of execution, not current time
                                g_input_timestamp_s = response_message.timestamp - start_s
                                g_input_updated = True
                                thread_lock.release()
                                # Log to output file
                                actual_value = hex(actual_value)
                                if self.data_size == 4:
                                    actual_value = hex_to_float(actual_value)
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
                                # # Reset globals
                                print("{}  {}: {}".format(
                                    round(g_output_timestamp_s, 4),
                                    self.signal_name,
                                    actual_value,
                                    flush=True)
                                )
                                g_output_updated = True
                                thread_lock.release()

            sleep(0.01)

        logging.info("(IOStream) Exiting {} polling thread for {}".format(self.name, self.signal_name))

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


class UpdateValues(threading.Thread):
    def __init__(self, thread_id, name, bus, signal_name, input_address, data_size, update_values):
        # Thread
        threading.Thread.__init__(self)
        self.thread_id = thread_id
        self.name = name
        self.bus = bus
        self.signal_name = signal_name
        self.input_address = input_address
        self.mta_data = [0xF6, 0x00, 0x00, 0x00,
                         input_address & 0xFF,
                         (input_address >> 8) & 0xFF,
                         (input_address >> 16) & 0xFF,
                         (input_address >> 24) & 0xFF]
        self.data_size = data_size
        self.update_values = update_values
        self.download_data = [0xF0, self.data_size]
        self.conn = create_connection('interface.db')

    def run(self):
        global g_update_finished
        global g_value_updated
        global g_expected_value
        global g_update_state
        global g_input_updated
        global g_input_timestamp_s
        global g_output_updated
        global g_output_timestamp_s
        global g_test_passed

        set_mta = can.Message(arbitration_id=master_id,
                              data=self.mta_data,
                              extended_id=False)

        for data in self.update_values:
            # g_test_passed = False
            if self.data_size == 1:
                self.download_data.append(data)
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
            while not g_output_updated:
                # response_message = None
                # send_try = 0
                # while response_message is None or send_try < 10:
                #     self.bus.send(set_mta)
                #     response_message = self.check_xcp_response(self.bus, slave_id)
                #     send_try += 1
                self.bus.send(set_mta)
                response_message = self.check_xcp_response(self.bus, slave_id)
                if response_message is not None:
                    if response_message.data[0] == 0xFF:
                        # DOWNLOAD
                        self.bus.send(cmd_download)
                        response_message = self.check_xcp_response(self.bus, slave_id)
                        if response_message is not None:
                            thread_lock.acquire()
                            g_value_updated = True
                            g_expected_value = cmd_download.data[2]
                            if self.data_size == 2:
                                g_expected_value = (g_expected_value << 8) | cmd_download.data[3]
                            elif self.data_size == 4:
                                g_expected_value = (g_expected_value << 8) | cmd_download.data[3]
                                g_expected_value = (g_expected_value << 8) | cmd_download.data[4]
                                g_expected_value = (g_expected_value << 8) | cmd_download.data[5]
                            thread_lock.release()
            sleep(1)
            self.download_data = [0xF0, self.data_size]

        # This thread has finished updating the input signal, end the IOStream thread
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

debug = False
parser = argparse.ArgumentParser()
if debug:
    parser.add_argument('-v', dest='variant', help='set to GC7, for debugging', default='GC7')
    parser.add_argument('-r', dest='retries', help='set to 2, for debugging', default=2)
    parser.add_argument('-a', dest='update_address', help='set to no, for debugging', default='no')
else:
    parser.add_argument("variant", help='variant to be tested', choices=['GC7', 'HR3'])
    parser.add_argument('-r', dest='retries', help='number of test retries for failed test results, default is 0',
                        default=0)
    parser.add_argument('-a', dest='update_address',
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
        if dbc_root.find(args.variant) != -1:
            dbc_variant_folder_found = True
            for dbc_file in dbc_files:
                if dbc_file.endswith(".dbc"):
                    dbc_files_found = True
                    break
            break

    if not dbc_variant_folder_found:
        print('{} folder not found in the DBC folder!'.format(args.variant), flush=True)
    elif not dbc_files_found:
        print('DBC files for {} not found in the DBC folder!'.format(args.variant), flush=True)
    else:
        max_retry = 0
        if args.retries is not None and args.retries > 0:
            max_retry = args.retries
        # Update the interface database for interface test
        interface_test = InterfaceTestMT(args.variant, args.map_folder, args.dbc_folder)
        # Update internal signal information
        if not debug:
            if interface_test.update_internal_signals() == 0:
                print('Internal signals information were not updated! Aborting test..', flush=True)
                sys.exit()
            # Update external signal information
            if interface_test.update_external_signals() == 0:
                print('External signals information were not updated! Aborting test..', flush=True)
                sys.exit()
            sys.exit()

        db_connection = create_connection('interface.db')
        io_pairing, io_pairing_count = execute_sql(db_connection,
                                                   '''SELECT * FROM io_pairing ORDER BY destination_module;''',
                                                   select=True, count=True)
        passed_count = 0
        tested_count = 0
        skipped_count = 0
        master_id = 0x7E0
        slave_id = 0x7E1

        # Connect to the XCP slave
        interface_test.connect()
        xcp_bus = interface_test.bus

        update_values = {'boolean': [1, 0],
                         'uint8': [uint8_info('max'), uint8_info('min'), uint8_info('any')],
                         'float32': [int(float32_info('max', to_hex=True), 16), int(float32_info('min', to_hex=True), 16), int(float32_info('any', to_hex=True), 16)]
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
                        if module_name_o != '':
                            log_to_output.close()
                            print('Finished tests for {}'.format(module_name_o), flush=True)
                        print('Starting tests for {}'.format(io_pairing_row[3]), flush=True)
                    else:
                        if module_name_o != '':
                            log_to_output.close()
                            print('Finished re-tests for {}'.format(module_name_o), flush=True)
                        print('Re-testing failed test items for {}'.format(io_pairing_row[3]), flush=True)
                    first_entry = True

                source_signal = '{}_{}'.format(io_pairing_row[1], io_pairing_row[2])
                source_signal_info = execute_sql(db_connection,
                                                 '''SELECT * FROM internal_signals WHERE link=?''',
                                                 (source_signal,),
                                                 select=True, just_one=True
                                                 )
                destination_signal = '{}_{}'.format(io_pairing_row[3], io_pairing_row[4])
                destination_signal_info = execute_sql(db_connection,
                                                      '''SELECT * FROM internal_signals WHERE link=?''',
                                                      (destination_signal,),
                                                      select=True, just_one=True
                                                      )
                if retry_count == 0:
                    # 'Clean' the I/O pairing list
                    # For debugging, skip CAN for now
                    if io_pairing_row[1] == 'CAN' or io_pairing_row[3] == 'CAN' or io_pairing_row[1] == 'VP' or \
                            io_pairing_row[3] == 'VP' or io_pairing_row[3] == 'DebugCAN':
                        print('{}: Skipped {} -> {} - No tests yet for CAN and VP signals'.format(
                            io_pairing_row[3], io_pairing_row[2], io_pairing_row[4]), flush=True)
                        execute_sql(db_connection, '''UPDATE io_pairing SET status=?, result=?, notes=? WHERE id=?;''',
                                    ('Skipped', 'N/A', 'CAN and VP signals not yet being tested', io_pairing_row[0]))
                        db_connection.commit()
                        module_name_o = io_pairing_row[3]
                        skipped_count += 1
                        continue
                    # Skip array, maps and tables for now
                    if source_signal.find('[') != -1 or destination_signal.find('[') != -1:
                        print('{}: Skipped {} -> {} - No tests yet for arrays, tables and maps'.format(
                            io_pairing_row[3], io_pairing_row[2], io_pairing_row[4]), flush=True)
                        execute_sql(db_connection, '''UPDATE io_pairing SET status=?, result=?, notes=? WHERE id=?;''',
                                    ('Skipped', 'N/A', 'Arrays/tables/maps not yet being tested', io_pairing_row[0]))
                        db_connection.commit()
                        module_name_o = io_pairing_row[3]
                        skipped_count += 1
                        continue
                    # Skip if no information or address is found for the source signal
                    if source_signal_info is None or int(source_signal_info[2]) == 0x0:
                        print('{}: Skipped {} -> {} - No address found for the source signal'.format(
                            io_pairing_row[3], io_pairing_row[2], io_pairing_row[4]), flush=True)
                        execute_sql(db_connection, '''UPDATE io_pairing SET status=?, result=?, notes=? WHERE id=?;''',
                                    ('Skipped', 'N/A', 'No address found for the source signal', io_pairing_row[0]))
                        db_connection.commit()
                        module_name_o = io_pairing_row[3]
                        skipped_count += 1
                        continue
                    # Skip if no information or address is found for the destination signal
                    if destination_signal_info is None or int(destination_signal_info[2]) == 0x0:
                        print('{}: Skipped {} -> {} - No address found for the destination signal'.format(
                            io_pairing_row[3], io_pairing_row[2], io_pairing_row[4]), flush=True)
                        execute_sql(db_connection, '''UPDATE io_pairing SET status=?, result=?, notes=? WHERE id=?;''',
                                    ('Skipped', 'N/A', 'No address found for the destination signal', io_pairing_row[0]))
                        db_connection.commit()
                        module_name_o = io_pairing_row[3]
                        skipped_count += 1
                        continue
                    # # Skip float32 data type
                    # if source_signal_info[4] == 'float32' or destination_signal_info[4] == 'float32':
                    #     print('{}: Skipped {} -> {} - No tests yet for float32 data types..'.format(
                    #         io_pairing_row[3], io_pairing_row[2], io_pairing_row[4]))
                    #     execute_sql(db_connection, '''UPDATE io_pairing SET status=?, result=?, notes=? WHERE id=?;''',
                    #                 ('Skipped', 'N/A', 'float32 data types not yet being tested', io_pairing_row[0]))
                    #     db_connection.commit()
                    #     module_name_o = io_pairing_row[3]
                    #     skipped_count += 1
                    #     continue
                    if source_signal_info[4] != destination_signal_info[4]:
                        print('{}: Skipped {} -> {} - No tests yet for not matching data types ({} -> {})..'.format(
                            io_pairing_row[3], io_pairing_row[2],
                            io_pairing_row[4], source_signal_info[4], destination_signal_info[4]), flush=True)
                        execute_sql(db_connection, '''UPDATE io_pairing SET status=?, result=?, notes=? WHERE id=?;''',
                                    ('Skipped', 'N/A',
                                     'No tests yet for not matching data types ({} -> {})'.format(
                                         source_signal_info[4], destination_signal_info[4]),
                                     io_pairing_row[0]))
                        db_connection.commit()
                        module_name_o = io_pairing_row[3]
                        skipped_count += 1
                        continue

                # Get details about the source signal
                source_address = int(source_signal_info[2])
                source_data_size = int(source_signal_info[5])
                source_cycle_ms = int(source_signal_info[7])
                source_data_type = source_signal_info[4]

                # Get details about the destination signal
                destination_address = int(destination_signal_info[2])
                destination_data_size = int(destination_signal_info[5])
                destination_cycle_ms = int(destination_signal_info[7])
                destination_data_type = destination_signal_info[4]

                # For threading
                g_update_finished = False
                g_value_updated = False
                g_expected_value = 0
                g_input_updated = False
                g_input_timestamp_s = 0.0
                g_output_updated = False
                g_output_timestamp_s = 0.0
                g_test_passed = False

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
                # IOStream(self, thread_id, name, bus, signal_name, signal_address, data_size, cycle):
                thread1 = IOStream(1, "input", xcp_bus, source_signal,
                                   source_address, source_data_size, source_cycle_ms)
                thread2 = IOStream(2, "output", xcp_bus, destination_signal,
                                   destination_address, destination_data_size, destination_cycle_ms)
                # UpdateValues(self, thread_id, name, bus, signal_name, input_address, data_size, update_values[max, min, [any]]):
                thread3 = UpdateValues(3, "update", xcp_bus, source_signal,
                                       source_address, source_data_size, update_values[source_data_type])

                # Start new threads
                print('{}: Testing {} -> {}'.format(io_pairing_row[3],
                                                    io_pairing_row[2],
                                                    io_pairing_row[4]), flush=True)
                thread1.start()
                thread2.start()
                sleep(3)
                thread3.start()

                # Add threads to thread list
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

            if not first_entry:
                log_to_output.close()

            print('-----------------------------------', flush=True)
            print('', flush=True)
            if max_retry > 0:
                retry_count += 1
                if retry_count > max_retry:
                    IF_test_finished = True
                else:
                    io_pairing = execute_sql(db_connection,
                                             '''SELECT * FROM io_pairing WHERE result='Failed' ORDER BY destination_module;''',
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

        print('', flush=True)
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
