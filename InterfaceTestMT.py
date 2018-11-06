#!/usr/bin/env python3

# coding: utf-8

from __future__ import print_function
from time import sleep
# from can.interface import Bus

import can
import time
import sqlite3
import logging
import threading


class InterfaceTestMT(object):
    def __init__(self):
        # Connect to database for error-checking
        self.conn = sqlite3.connect('main.db')
        self.c = self.conn.cursor()

        # configure logging settings
        logging.basicConfig(level=logging.DEBUG, format=' %(asctime)s - %(levelname)s- %(message)s')

        try:
            # self.bus1 = can.interface.Bus(bustype='vector', channel=0, bitrate=500000, app_name='InterfaceTest')
            # self.bus2 = can.interface.Bus(bustype='vector', channel=1, receive_own_messages=True, bitrate=500000,
            #                               app_name='InterfaceTest')
            # self.bus2 = can.interface.Bus(bustype='vector', channel=1,
            #                               can_filters=[{"can_id": 0x7e1, "can_mask": 0x7ef, "extended": False}],
            #                               receive_own_messages=True, bitrate=500000, app_name='InterfaceTest')
            self.bus2 = can.ThreadSafeBus(bustype='vector', channel=1,
                                          can_filters=[{"can_id": 0x7e1, "can_mask": 0x7e1, "extended": False}],
                                          receive_own_messages=True, bitrate=500000, app_name='InterfaceTest')
            # self.bus3 = can.interface.Bus(bustype='vector', channel=2, bitrate=500000, app_name='InterfaceTest')
            # self.bus4 = can.interface.Bus(bustype='vector', channel=3, bitrate=500000, app_name='InterfaceTest')

            # Connect using the can.ini file
            # self.bus1 = Bus(config_section='CAN1')
            # self.bus2 = Bus(config_section='CAN2')
            # self.bus3 = Bus(config_section='CAN3')
            # self.bus4 = Bus(config_section='CAN4')
        except can.CanError as message:
            logging.error(message)
            exit(-1)

        # CAN logger
        self.can_log = open('log.asc', 'w+')
        self.asc_writer = can.ASCWriter('log.asc')
        self.notifier = can.Notifier(self.bus2, [self.asc_writer])
        # self.notifier.add_bus(self.bus1)
        # self.notifier.add_bus(self.bus3)
        # self.notifier.add_bus(self.bus4)

    def connect(self, bus):
        global start_s

        print("Connecting to XCP slave..")
        msg = can.Message(arbitration_id=0x7e0,
                          data=[0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                          extended_id=False)
        start_s = time.time()
        self.send_once(bus, msg)
        sleep(1)

    def send_once(self, bus, msg):
        tries = 0
        bus.send(msg)
        response_message = self.check_xcp_response(bus, slave_id)
        # Keep sending connect request until a response is received
        while response_message is None and tries < 9:
            tries += 1
            if msg.data[0] == 0xFF:
                print("InterfaceTestMT: Retrying to connect to XCP slave.. {}".format(tries))
            elif msg.data[0] == 0xFE:
                print("InterfaceTestMT: Retrying to disconnect from XCP slave.. {}".format(tries))
            bus.send(msg)
            response_message = self.check_xcp_response(bus, slave_id)
        if tries > 9:
            if msg.data[0] == 0xFF:
                print("InterfaceTestMT: Failed to connect to the XCP slave!")
            elif msg.data[0] == 0xFE:
                print("InterfaceTestMT: Failed to disconnect from the XCP slave!")
            exit(-1)
        command = hex(msg.data[0])

        if response_message is not None:
            # Response packet
            if response_message.data[0] == 0xFF:
                if msg.data[0] == 0xFF:
                    logging.debug('Command: CONNECT       Response: Connected to XCP slave through {}'.format(bus))
                elif msg.data[0] == 0xFE:
                    logging.debug('Command: DISCONNECT    Response: Disconnected from XCP slave')
                else:
                    logging.debug('Command: {}            Response: Success'.format(hex(command)))
            # Error packet
            elif response_message.data[0] == 0xFE:
                # response indicates error, report error
                error_code = response_message.data[1]
                self.c.execute("SELECT * FROM error_array WHERE error_code=?", (error_code,))
                error_info = self.c.fetchone()
                if error_info is not None:
                    logging.debug('Command: {}            Response: {} {}'.format(command, error_info[1],
                                                                                  error_info[2].strip()))
                else:
                    logging.debug('Command: {}            Response: {}'.format(command, hex(response_message.data[1])))
                if msg.data[0] == 0xFF:
                    print("Unable to connect to the XCP slave.")
                    exit(-1)
            elif response_message.data[0] == 0x20:
                logging.debug('Command: {}            Response: XCP_ERR_CMD_UNKNOWN'.format(command))
            else:
                logging.debug('Command: {}            Response: {}'.format(command, hex(response_message.data[0])))
        else:
            logging.debug('Command: {}          Response: XCP slave response timeout!'.format(command))

    def end_logging(self):
        # self.log_to_output.close()
        self.can_log.close()

    def disconnect(self, bus):
        self.conn.close()
        self.notifier.stop()
        self.asc_writer.stop()

        msg = can.Message(arbitration_id=0x7e0,
                          data=[0xFE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                          extended_id=False)
        self.send_once(bus, msg)
        bus.shutdown()

    @staticmethod
    def check_xcp_response(bus, xcp_rx_id):
        try:
            # Set timeout for response message
            received_msg = bus.recv(0.05)
            if received_msg is None:
                print("InterfaceTestMT: No message received from {}!".format(bus))
            elif received_msg.arbitration_id == xcp_rx_id:
                return received_msg

        except can.CanError as message:
            logging.error(message)


class IOStream(threading.Thread):
    def __init__(self, thread_id, name, bus, signal_name, signal_address, num_of_bytes, cycle):
        # Thread
        threading.Thread.__init__(self)
        self.thread_id = thread_id
        self.name = name
        self.bus = bus
        self.signal_name = signal_name
        self.message = can.Message(arbitration_id=0x7E0, data=[0xF4, num_of_bytes, 0x0, 0x0,
                                                               signal_address & 0xFF,
                                                               (signal_address >> 8) & 0xFF,
                                                               (signal_address >> 16) & 0xFF,
                                                               (signal_address >> 24) & 0xFF],
                                   extended_id=False)
        self.cycle = cycle
        # Connect to database for error-checking
        conn = sqlite3.connect('main.db')
        self.c = conn.cursor()

        # configure logging settings
        logging.basicConfig(level=logging.DEBUG, format=' %(asctime)s - %(levelname)s- %(message)s')

        self.start_timestamp = 0.0

        # Data check
        if self.name == "input":
            self.input_timestamp = 0.0
            self.input_value = 0.0
        else:
            self.output_timestamp = 0.0
            self.output_value = 0.0

    def run(self):
        global test_passed
        global g_timestamp
        global g_value_updated
        global g_value
        global g_input_updated

        print("Starting polling thread for {} signal {}...".format(self.name, self.signal_name))

        while g_update_finished is False:
            thread_lock.acquire()
            # response_message = None
            # while response_message is None:
            #     # SET_MTA
            #     self.bus.send(self.message)
            #     response_message = self.check_xcp_response(self.bus, slave_id)
            self.bus.send(self.message)
            response_message = self.check_xcp_response(self.bus, slave_id)

            command = hex(self.message.data[0])
            if response_message is not None:
                # Response packet
                if response_message.data[0] == 0xFF:
                    thread_lock.release()
                    # response indicates command successful
                    # if self.message.data[0] == 0xF6:
                    #     logging.debug('Command: SET_MTA       Response: Success Address: 0x{}{}{}{}'.format(
                    #         format(self.message.data[7], 'x'),
                    #         format(self.message.data[6], 'x'),
                    #         format(self.message.data[5], 'x'),
                    #         format(self.message.data[4], 'x')))
                    if self.message.data[0] == 0xF4:
                        # logging.debug('Command: SHORT_UPLOAD  Response: Success  Signal Name: {}'.format(
                        #     self.signal_name))
                        if g_value_updated is True:
                            if response_message.data[1] == g_value:
                                if self.name == "input" and g_input_updated is False:
                                    g_timestamp = response_message.timestamp
                                    g_input_updated = True
                                    # Log to output file
                                    log_to_output.write("{}  {}: {}\n".format(
                                        round(response_message.timestamp - start_s, 4),
                                        self.signal_name,
                                        hex(response_message.data[1]))
                                    )
                                elif self.name == "output" and g_input_updated is True:
                                    # Log to output file
                                    log_to_output.write("{}  {}: {}\n".format(
                                        round(response_message.timestamp - start_s, 4),
                                        self.signal_name,
                                        hex(response_message.data[1]))
                                    )
                                    g_timestamp = abs(response_message.timestamp - g_timestamp)
                                    if g_timestamp <= (self.cycle / 1000):
                                        log_to_output.write("Update successful! ")
                                        test_passed = True
                                    else:
                                        log_to_output.write("Update failed! ")
                                        test_passed = False
                                        # thread_lock.release()
                                        # return
                                    log_to_output.write("Time: {} ms\n".format(
                                            int(g_timestamp * 1000)))
                                    # Reset globals
                                    g_value_updated = False
                                    g_value = 0
                                    g_timestamp = 0.0
                                    g_input_updated = False
                        # Log to output file
                        # log_to_output.write("{}  {}: {}\n".format(response_message.timestamp,
                        #                                      self.signal_name,
                        #                                      hex(response_message.data[1])))
                    else:
                        logging.debug('Command: {}            Response: Success'.format(hex(command)))
                # Error packet
                elif response_message.data[0] == 0xFE:
                    # response indicates error, report error
                    error_code = response_message.data[1]
                    self.c.execute("SELECT * FROM error_array WHERE error_code=?", (error_code,))
                    error_info = self.c.fetchone()
                    if error_info is not None:
                        logging.debug('Command: {}            Response: {} {}'.format(command, error_info[1],
                                                                                      error_info[2].strip()))
                    else:
                        logging.debug('Command: {}            Response: {}'.format(command,
                                                                                   hex(response_message.data[1])))
                elif response_message.data[0] == 0x20:
                    logging.debug('Command: {}            Response: XCP_ERR_CMD_UNKNOWN'.format(command))
                else:
                    logging.debug('Command: {}            Response: {}'.format(command, hex(response_message.data[0])))
            else:
                logging.debug('Command: {}          Response: XCP slave response timeout! Signal: {}'.format(
                    command,
                    self.signal_name))

            if thread_lock.locked():
                thread_lock.release()
            # if self.name == "input":
            #     sleep(self.cycle/1000)
            # elif self.name == "output":
            #     sleep(0.01)
            # else:
            #     logging.debug("IOStream: Invalid stream name!")
            sleep(0.01)
        print("Exiting {} polling thread for {}".format(self.name, self.signal_name))

    @staticmethod
    def check_xcp_response(bus, xcp_rx_id):
        # read response
        # NOTE: add more sophisticated XCP error reporting using error array
        #
        # try:
        #     # Loop until expected response is received
        #     for recvd_msg in bus:
        #         if recvd_msg.arbitration_id == xcp_rx_id:
        #             print(recvd_msg)
        #             return recvd_msg
        #
        # except None:
        #     print('No response from XCP slave!')
        try:
            # Set timeout for response message
            received_msg = bus.recv(0.05)
            if received_msg is None:
                # print("IOStream: No message received from {}!".format(bus))
                pass
            elif received_msg.arbitration_id == xcp_rx_id:
                return received_msg

            # print(received_msg)

        except can.CanError as message:
            logging.error(message)


class UpdateValues(threading.Thread):
    def __init__(self, thread_id, name, bus, signal_name, input_address, data_size, update_values):
        # Thread
        threading.Thread.__init__(self)
        self.thread_id = thread_id
        self.name = name
        self.bus = bus
        self.signal_name = signal_name
        self.mta_data = [0xF6, 0x00, 0x00, 0x00,
                         input_address & 0xFF,
                         (input_address >> 8) & 0xFF,
                         (input_address >> 16) & 0xFF,
                         (input_address >> 24) & 0xFF]
        self.data_size = data_size
        self.update_values = update_values
        self.download_data = [0xF0, self.data_size]
        # if data_size == 1:
        #     self.download_data.append(update_values[0])
        #     self.download_data.append([0x00, 0x00, 0x00, 0x00, 0x00])
        # elif data_size == 2:
        #     self.download_data.append((update_values[0] >> 8) & 0xFF)
        #     self.download_data.append(update_values[0] & 0xFF)
        #     self.download_data.append([0x00, 0x00, 0x00, 0x00])
        # elif data_size == 4:
        #     self.download_data.append((update_values[0] >> 24) & 0xFF)
        #     self.download_data.append((update_values[0] >> 16) & 0xFF)
        #     self.download_data.append((update_values[0] >> 8) & 0xFF)
        #     self.download_data.append(update_values[0] & 0xFF)
        #     self.download_data.append([0x00, 0x00])
        # else:
        #     print("UpdateValues: Invalid data_size!")
        # XCP
        # self.set_mta = can.Message(arbitration_id=0x7e0,
        #                            data=self.mta_data,
        #                            extended_id=False)
        # self.cmd_download = can.Message(arbitration_id=0x7e0,
        #                                 data=self.update_value1,
        #                                 extended_id=False)
        # self.cmd_download2 = can.Message(arbitration_id=0x7e0,
        #                                  data=self.update_value2,
        #                                  extended_id=False)

    def run(self):
        global g_update_finished
        global g_value_updated
        global g_value
        # global g_min_check
        # global g_max_check
        # global g_any_check

        set_mta = can.Message(arbitration_id=0x7e0,
                              data=self.mta_data,
                              extended_id=False)
        for data in self.update_values:
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
                print("UpdateValues: Invalid data_size!")

            cmd_download = can.Message(arbitration_id=0x7e0,
                                       data=self.download_data,
                                       extended_id=False)
            sleep(0.5)
            # response_message = None
            thread_lock.acquire()
            # while response_message is None:
            #     # SET_MTA
            #     self.bus.send(self.set_mta)
            #     response_message = self.check_xcp_response(self.bus, slave_id)
            self.bus.send(set_mta)
            response_message = self.check_xcp_response(self.bus, slave_id)

            if response_message is not None:
                if response_message.data[0] == 0xFF:
                    # response indicates command successful
                    logging.debug(
                        'Command: SET_MTA       Response: Success Address: 0x{}{}{}{}'.format(
                            format(set_mta.data[7], 'x'), format(set_mta.data[6], 'x'),
                            format(set_mta.data[5], 'x'), format(set_mta.data[4], 'x'))
                    )

                    # DOWNLOAD
                    response_message = None
                    while response_message is None:
                        # DOWNLOAD
                        self.bus.send(cmd_download)
                        response_message = self.check_xcp_response(self.bus, slave_id)

                    if response_message is not None:
                        if response_message.data[0] == 0xFF:
                            thread_lock.release()
                            # 0xFF means success
                            g_value_updated = True
                            g_value = cmd_download.data[2]
                            logging.debug('Command: DOWNLOAD      Response: Success')
                            log_to_output.write("{}  Update {}: {}\n".format(
                                round(response_message.timestamp - start_s, 4),
                                self.signal_name,
                                hex(cmd_download.data[2]))
                            )
                    else:
                        logging.debug('Command: DOWNLOAD      Response: XCP slave response timeout!')
                elif response_message.data[0] == 0x20:
                    logging.debug('Command: SET_MTA       Response: XCP_ERR_CMD_UNKNOWN')
                else:
                    logging.debug('Command: SET_MTA       Response: {}'.format(hex(response_message.data[0])))
            else:
                logging.debug('Command: SET_MTA       Response: XCP slave response timeout!')
            # thread_lock.release()
            sleep(0.5)
            g_value_updated = False
            self.download_data = [0xF0, self.data_size]

        # This thread has finished updating the input signal, end the IOStream thread
        g_update_finished = True

    @staticmethod
    def check_xcp_response(bus, xcp_rx_id):
        try:
            # Set timeout for response message
            received_msg = bus.recv(0.05)
            if received_msg is None:
                print("UpdateValues: No message received!".format(bus))
            elif received_msg.arbitration_id == xcp_rx_id:
                return received_msg

        except can.CanError as message:
            logging.error(message)


def main():
    global test_passed

    interface_test = InterfaceTestMT()
    xcp_bus = interface_test.bus2
    # Connect to the XCP slave
    interface_test.connect(xcp_bus)

    test_passed = False
    source_signal = "ACC_Main_ACCSelectObj"
    destination_signal = "VDC_ACCSelectObj"

    # Create new threads
    # def __init__(self, thread_id, name, bus, signal_name, signal_address, num_of_bytes, cycle):
    thread1 = IOStream(1, "input", xcp_bus, source_signal, 0x50006814, 0x1, 50)
    thread2 = IOStream(2, "output", xcp_bus, destination_signal, 0x50017f1c, 0x1, 50)
    # def __init__(self, thread_id, name, bus, signal_name, input_address, data_size, update_values[max, min, [any]]):
    thread3 = UpdateValues(3, "update", xcp_bus, source_signal, 0x50006814, 0x01, [0xFF, 0x00, 0x7F])

    # Start new threads
    thread1.start()
    thread2.start()
    thread3.start()

    # Add threads to thread list
    threads.append(thread1)
    threads.append(thread2)
    threads.append(thread3)

    # Wait for all threads to complete
    for t in threads:
        t.join()

    if test_passed:
        # Output to report
        print("Interface test for {} -> {} PASSED".format(source_signal, destination_signal))
    else:
        # Output to report
        print("Interface test for {} -> {} FAILED".format(source_signal, destination_signal))

    # Disconnect from XCP slave
    interface_test.disconnect(interface_test.bus2)
    # End logging (ASC and info)
    interface_test.end_logging()


if __name__ == '__main__':
    start_s = 0.0

    test_passed = False

    master_id = 0x7E0
    slave_id = 0x7E1

    g_update_finished = False
    g_value_updated = False
    g_value = 0
    g_input_updated = False

    # g_min_check = False
    # g_min_value = 0
    # g_max_check = False
    # g_max_value = 1
    # g_any_check = False
    # g_any_value = 100
    g_timestamp = 0.0

    log_to_output = open('ACC_Main.txt', 'w+')

    thread_lock = threading.Lock()
    threads = []

    main()

    log_to_output.close()

