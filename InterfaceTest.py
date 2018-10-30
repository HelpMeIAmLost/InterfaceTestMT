#!/usr/bin/env python3

# coding: utf-8

from __future__ import print_function
from time import sleep
from can.interface import Bus

import can
import time
import sqlite3
import logging


class InterfaceTest(object):
    def __init__(self):
        # XCP message IDs
        self.master_id = 0x7E0
        self.slave_id = 0x7E1
        # Connect to database for error-checking
        conn = sqlite3.connect('main.db')
        self.c = conn.cursor()

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
                                          can_filters=[{"can_id": 0x7e1, "can_mask": 0x7ef, "extended": False}],
                                          receive_own_messages=True, bitrate=500000, app_name='InterfaceTest')
            # self.bus3 = can.interface.Bus(bustype='vector', channel=2, bitrate=500000, app_name='InterfaceTest')
            # self.bus4 = can.interface.Bus(bustype='vector', channel=3, bitrate=500000, app_name='InterfaceTest')

            # Connect using the can.ini file
            # self.bus1 = Bus(config_section='CAN1')
            # self.bus2 = Bus(config_section='CAN2')
            # self.bus3 = Bus(config_section='CAN3')
            # self.bus4 = Bus(config_section='CAN4')
        except can.interfaces.vector.exceptions.VectorError as message:
            logging.error(message)
            exit(-1)

        # CAN logger
        self.logfile = open('log.asc', 'w+')
        self.ascwriter = can.ASCWriter('log.asc')
        self.notifier = can.Notifier(self.bus2, [self.ascwriter])
        # self.notifier.add_bus(self.bus1)
        # self.notifier.add_bus(self.bus3)
        # self.notifier.add_bus(self.bus4)

        # Info logger
        self.loginfo = open('info.txt', 'w+')

        # Data check
        self.input_timestamp = 0.0
        self.input_value = 0.0
        self.output_timestamp = 0.0
        self.output_value = 0.0
        self.cmd_sent = False

    def connect(self, bus):
        msg = can.Message(arbitration_id=0x7e0,
                          data=[0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                          extended_id=False)
        self.send_once(bus, msg)
        
    @staticmethod
    def start_polling(bus, msg, cycle_s):
        try:
            # Send a periodic message
            return bus.send_periodic(msg, cycle_s, False)

        except can.CanError:
            print("Message NOT sent")

    # Non-short upload commands
    def send_once(self, bus, msg):
        bus.send(msg)
        response_message = self.check_xcp_response(bus, self.slave_id)
        command = hex(msg.data[0])

        if response_message is not None:
            # Response packet
            if response_message.data[0] == 0xFF:
                # response indicates command successful
                if msg.data[0] == 0xF6:
                    logging.debug('Command: SET_MTA       Response: Success Address: 0x{}{}{}{}'.format(
                        format(msg.data[7], 'x'),
                        format(msg.data[6], 'x'),
                        format(msg.data[5], 'x'),
                        format(msg.data[4], 'x')))
                elif msg.data[0] == 0xF4:
                    logging.debug('Command: SHORT_UPLOAD  Response: Success')
                    # Check the output
                    # self.loginfo.write('Timestamp: {} Value: {}\n'.format(response_message.timestamp, msg.data[2]))
                    # if self.cmdsent is True:
                    #     self.cmdsent = False
                    #     self.edgetimestamp = response_message.timestamp - self.cmdtimestamp
                    #     if self.inputvalue == response_message.data[1] and self.edgetimestamp <= 0.05:
                    #         print('Passed!')
                elif msg.data[0] == 0xFF:
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
            elif response_message.data[0] == 0x20:
                logging.debug('Command: {}            Response: XCP_ERR_CMD_UNKNOWN'.format(command))
            else:
                logging.debug('Command: {}            Response: {}'.format(command, hex(response_message.data[0])))
        else:
            logging.debug('Command: {}          Response: XCP slave response timeout!'.format(command))

    def xcp_download(self, bus, msg1, msg2):
        # SET_MTA

        response_message = None
        while response_message is None:
            bus.send(msg1)
            response_message = self.check_xcp_response(bus, self.slave_id)

        if response_message is not None:
            if response_message.data[0] == 0xFF:
                # response indicates command successful
                logging.debug(
                    'Command: SET_MTA       Response: Success Address: 0x{}{}{}{}'.format(
                        format(msg1.data[7], 'x'), format(msg1.data[6], 'x'),
                        format(msg1.data[5], 'x'), format(msg1.data[4], 'x'))
                )

                # DOWNLOAD
                bus.send(msg2)
                response_message = self.check_xcp_response(bus, self.slave_id)

                if response_message is not None:
                    if response_message.data[0] == 0xFF:
                        # response indicates command successful
                        logging.debug('Command: DOWNLOAD      Response: Success')
                        self.loginfo.write('Timestamp: {} Value: {}\n'.format(response_message.timestamp, msg2.data[2]))
                        # Get timestamp and value
                        # self.cmdtimestamp = response_message.timestamp
                        # self.inputvalue = msg2.data[2]
                        # self.cmdsent = True
                else:
                    logging.debug('Command: DOWNLOAD      Response: XCP slave response timeout!')
            elif response_message.data[0] == 0x20:
                logging.debug('Command: SET_MTA       Response: XCP_ERR_CMD_UNKNOWN')
            else:
                logging.debug('Command: SET_MTA       Response: {}'.format(hex(response_message.data[0])))
        else:
            logging.debug('Command: SET_MTA       Response: XCP slave response timeout!')
# End

    def end_polling(self, task):
        task.stop()

    def end_logging(self):
        self.loginfo.close()
        self.logfile.close()

    def disconnect(self, bus):
        self.notifier.stop()
        self.ascwriter.stop()

        msg = can.Message(arbitration_id=0x7e0,
                          data=[0xFE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                          extended_id=False)
        self.send_once(bus, msg)

        bus.shutdown()

    @staticmethod
    def check_xcp_response(bus, xcp_rx_id):
        # read response
        # NOTE: add more sophisticated XCP error reporting using error array
        #
        # try:
        #     for recvd_msg in bus:
        #         if recvd_msg.arbitration_id == xcp_rx_id:
        #             print(recvd_msg)
        #             return recvd_msg
        #
        # except None:
        #     print('No response from XCP slave!')
        try:
            recvd_msg = bus.recv(0.05)
            if recvd_msg.arbitration_id == xcp_rx_id:
                print(recvd_msg)
                return recvd_msg
            else:
                print(recvd_msg)
                # logging.debug('XCP slave response timeout!')

        except can.VectorError as message:
            logging.error(message)


def main():
    # Common messages
    cmd_download_on = can.Message(arbitration_id=0x7e0,
                                  data=[0xF0, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00],
                                  extended_id=False)
    cmd_download_off = can.Message(arbitration_id=0x7e0,
                                   data=[0xF0, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                                   extended_id=False)
    # APP to APP
    # For polling signals
    # VDC_ACCSelectObj - 50017f1c
    cmd_short_upload_output = can.Message(arbitration_id=0x7e0,
                                          data=[0xF4, 0x01, 0x00, 0x00, 0x1C, 0x7F, 0x01, 0x50],
                                          extended_id=False)
    # For update
    cmd_set_mta = can.Message(arbitration_id=0x7e0,
                              data=[0xF6, 0x00, 0x00, 0x00, 0x14, 0x68, 0x00, 0x50],
                              extended_id=False)

    interface_test = InterfaceTest()
    # Connect to the XCP slave
    interface_test.connect(interface_test.bus2)
    sleep(1)
    # Poll the output signal every 10ms
    task2 = interface_test.start_polling(interface_test.bus2, cmd_short_upload_output, 0.010)
    sleep(1)
    # Write the first value to the input signal (SET_MTA -> DOWNLOAD)
    interface_test.xcp_download(interface_test.bus2, cmd_set_mta, cmd_download_on)
    sleep(3)
    # Write the second value to the input signal (SET_MTA -> DOWNLOAD)
    interface_test.xcp_download(interface_test.bus2, cmd_set_mta, cmd_download_off)
    sleep(1)
    # End polling of output signal
    interface_test.end_polling(task2)
    # Disconnect from XCP slave
    interface_test.disconnect(interface_test.bus2)
    # End logging (ASC and info)
    interface_test.end_logging()


if __name__ == '__main__':
    main()

#"""
#This example exercises the periodic sending capabilities.
#Expects a vcan0 interface:
#        python3 -m examples.cyclic
#"""
#
#import logging
#import time
#import can
#
#logging.basicConfig(level=logging.INFO)
##can.rc['interface'] = 'socketcan_ctypes'
#
#from can.interfaces.interface import Message, MultiRateCyclicSendTask
#
#
#def test_simple_periodic_send():
#    print("Trying to send a message...")
#    msg = Message(arbitration_id=0x0cf02200, data=[0, 1, 3, 1, 4, 1])
#    task = can.send_periodic('vcan0', msg, 0.020)
#    time.sleep(2)
#
#    print("Trying to change data")
#    msg.data[0] = 99
#    task.modify_data(msg)
#    time.sleep(2)
#
#    task.stop()
#    print("stopped cyclic send")
#
#    time.sleep(1)
#    task.start()
#    print("starting again")
#    time.sleep(1)
#    print("done")
#
#
#def test_dual_rate_periodic_send():
#    """Send a message 10 times at 1ms intervals, then continue to send every 500ms"""
#    msg = Message(arbitration_id=0x0c112200, data=[0, 1, 2, 3, 4, 5])
#    print("Creating cyclic task to send message 10 times at 1ms, then every 500ms")
#    task = MultiRateCyclicSendTask('vcan0', msg, 10, 0.001, 0.50)
#    time.sleep(2)
#
#    print("Changing data[0] = 0x42")
#    msg.data[0] = 0x42
#    task.modify_data(msg)
#    time.sleep(2)
#
#    task.stop()
#    print("stopped cyclic send")
#
#    time.sleep(2)
#
#    task.start()
#    print("starting again")
#    time.sleep(2)
#    print("done")
#
#
#if __name__ == "__main__":
#
#    test_simple_periodic_send()
##    #test_dual_rate_periodic_send()

