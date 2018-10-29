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
        conn = sqlite3.connect('main.db')
        self.c = conn.cursor()

        # configure logging settings
        logging.basicConfig(level=logging.DEBUG, format=' %(asctime)s - %(levelname)s- %(message)s')

        # self.bus1 = can.interface.Bus(bustype='vector', channel=0, bitrate=500000, app_name='InterfaceTest')
        self.bus2 = can.interface.Bus(bustype='vector', channel=1, receive_own_messages=False, bitrate=500000, app_name='InterfaceTest')
        # self.bus2 = can.interface.Bus(bustype='vector', channel=1, can_filters=[{"can_id": 0x7e1, "can_mask": 0x7ef, "extended": False}], receive_own_messages=False, bitrate=500000, app_name='InterfaceTest')
        # self.bus3 = can.interface.Bus(bustype='vector', channel=2, bitrate=500000, app_name='InterfaceTest')
        # self.bus4 = can.interface.Bus(bustype='vector', channel=3, bitrate=500000, app_name='InterfaceTest')

#        self.bus1 = Bus(config_section='CAN1')
#        self.bus2 = Bus(config_section='CAN2')
#        self.bus3 = Bus(config_section='CAN3')
#        self.bus4 = Bus(config_section='CAN4')
        
#        self.bus2.set_filters([{"can_id": 0x7e1, "can_mask": 0x7ef, "extended": False}])
            
        # CAN logger
        self.logfile = open('log.asc', 'w+')
        self.ascwriter = can.ASCWriter('log.asc')
        self.notifier = can.Notifier(self.bus2, [self.ascwriter])
        # self.notifier.add_bus(self.bus1)
        # self.notifier.add_bus(self.bus3)
        # self.notifier.add_bus(self.bus4)

        # Info logger
        self.loginfo = open('info.txt', 'w+')

    def connect(self, bus):
        msg = can.Message(arbitration_id=0x7e0,
                          data=[0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                          extended_id=False)
        self.send_once(bus, msg)
        
    def start_polling(self, bus, msg, cycle_s):
        try:
            ## Display bus output
    ##        notifier = can.Notifier([self.bus1, self.bus2, self.bus3, self.bus4], [can.Printer()])
        
            ## Send messages
            return bus.send_periodic(msg, cycle_s, False)

        except can.CanError:
            print("Message NOT sent")

    def send_once(self, bus, msg):
        # self.loginfo.write(str(time.process_time()) + " " + msg.__str__() + "\n")
        bus.send(msg)
        
        response_message = self.check_xcp_response(bus, 0x7E1)
        command = hex(msg.data[0])

        if response_message.data[0] == 0xFF:
            # response indicates command successful
            if msg.data[0] == 0xF6:
                logging.debug('Command: SET_MTA Response: Success Address: 0x{}{}{}{}'.format(format(msg.data[7], 'x'), format(msg.data[6], 'x'), format(msg.data[5], 'x'), format(msg.data[4], 'x')))
            elif msg.data[0] == 0xF0:
                logging.debug('Command: DOWNLOAD Response: Success')
            elif msg.data[0] == 0xFF:
                logging.debug('Command: {} Response: Connected to XCP slave through {}'.format(command, bus))
            elif msg.data[0] == 0xFE:
                logging.debug('Command: {} Response: Disconnected from XCP slave'.format(command))
            else:
                logging.debug('Command: {} Response: Success'.format(command))
        elif response_message.data[0] == 0xFE:
            # response indicates error, report error
            error_code = response_message.data[1]
            self.c.execute("SELECT * FROM error_array WHERE error_code=?", (error_code,))
            error_info = self.c.fetchone()
            if error_info is not None:
                logging.debug('Command: {} Response: {} {}'.format(command, error_info[1], error_info[2].strip()))
            else:
                logging.debug('Command: {} Response: {}'.format(command, hex(response_message.data[1])))
        elif response_message.data[0] == 0x20:
            logging.debug('Command: {} Response: XCP_ERR_CMD_UNKNOWN'.format(command))
        else:
            logging.debug('Command: {} Response: {}'.format(command, hex(response_message.data[0])))
            # pass

    def end_polling(self, task):
        task.stop()

    def end_logging(self):
        self.notifier.stop()
        self.ascwriter.stop()

        self.loginfo.close()
        self.logfile.close()

    def disconnect(self, bus):
        msg = can.Message(arbitration_id=0x7e0,
                          data=[0xFE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                          extended_id=False)
        self.send_once(bus, msg)

    @staticmethod
    def check_xcp_response(bus, xcp_rx_id):
        # read response
        # NOTE: add more sophisticated XCP error reporting using error array
        for recvd_msg in bus:
            if recvd_msg.arbitration_id == xcp_rx_id:
                print(recvd_msg)
                return recvd_msg

##            ## Send once
##            # CAN to APP
##            # Result: OK
##    ####        print("Start monitoring FSFC_f_ABS_Op in channel 2")
##    ####        task = bus2.send_periodic(cmdSHORT_UPLOAD_FSFC_f_ABS_Op, 0.010)
##    ##        print("Updating VDC139_4_4_ACTIVATE_ABS signal and sending it to channel 4")
##    ##        bus4.send(msgVDC139_00)
##    ##        sleep(3)
##    ##        bus4.send(msgVDC139_01)
##    ##        sleep(1)
##    ##        bus4.send(msgVDC139_00)
##    ##        sleep(3)
##
##    ##        # APP to APP
##    ##        # Result: NG
##    ##        print("Start monitoring the following signals in channel 2:")
##    ##        print("   ACC_Main_f_fACCFail")
##    ##        print("   CUS_f_ACC_FAIL")
##    ##        print("   HMI_f_ACCFail")
##    ##        print("   SAS_f_ACCFail")
##    ##        task = bus2.send_periodic(ACC_Main_f_fACCFail, 0.050)
##    ##        task = bus2.send_periodic(CUS_f_ACC_FAIL, 0.010)
##    ##        task = bus2.send_periodic(HMI_f_ACCFail, 0.010)
##    ##        task = bus2.send_periodic(SAS_f_ACCFail, 0.010)
##            bus2.send(cmdSET_MTA_FSFC_f_Eye_Fail)
##            bus2.send(cmdDOWNLOAD_OFF)
##            sleep(3)
##            bus2.send(cmdSET_MTA_FSFC_f_Eye_Fail)
##            bus2.send(cmdDOWNLOAD_ON)
##            sleep(1)
##            bus2.send(cmdSET_MTA_FSFC_f_Eye_Fail)
##            bus2.send(cmdDOWNLOAD_OFF)
##            sleep(3)
##    ##        #bus2.send(cmdSET_MTA)
##    ##        #bus2.send(cmdDOWNLOAD_00)
##    ##        #bus2.send(cmdSHORT_UPLOAD)
##    ##
##    ##        # APP to CAN
##    ##        # Result:
##    ##        print("Updating FSFC_f_ACCFailForVDC in channel 2")
##    ##        bus2.send(cmdSET_MTA_FSFC_f_ACCFailForVDC)
##    ##        bus2.send(cmdDOWNLOAD_OFF)
##    ##        sleep(3)
##    ##        bus2.send(cmdSET_MTA_FSFC_f_ACCFailForVDC)
##    ##        bus2.send(cmdDOWNLOAD_ON)
##    ##        sleep(1)
##    ##        bus2.send(cmdSET_MTA_FSFC_f_ACCFailForVDC)
##    ##        bus2.send(cmdDOWNLOAD_OFF)
##    ##        sleep(3)
##
##            ## End task
##            # End display output
##    ##        notifier.stop(5)
##    ##        task.stop()
##            
##    ##        print(res)
##    ##        if res.data[0] == 0xFF:
##    ##            print("Success! Sending DOWNLOAD request to channel 2")
##    ##            bus2.send(cmdDOWNLOAD_01)
##    ##            res = bus2BufferedReader.get_message(timeout=0.5)
##    ##            if res.data[0] == 0xFF:
##    ##                print("Success!")
##
##            ##print("Message sent on {}".format(bus.channel_info))
##    ##        print("Creating cyclic task to a send message every 20 ms")
##    ##        task = bus2.send_periodic(msg, 0.020)
##    #        bus2Listener.stop()


def main():
    # Common messages
    cmdDOWNLOAD_ON = can.Message(arbitration_id=0x7e0,
                                 data=[0xF0, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00],
                                 extended_id=False)
    cmdDOWNLOAD_OFF = can.Message(arbitration_id=0x7e0,
                                  data=[0xF0, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                                  extended_id=False)
    # CAN to APP
    # VDC139_4_4_ACTIVATE_ABS: CH 4
    # FSFC_f_ABS_Op: 0x9004245c
    msgVDC139_01 = can.Message(arbitration_id=0x139,
                               data=[0x00, 0x00, 0x00, 0x00, 0x10, 0x00, 0x00, 0x00],
                               extended_id=False)
    msgVDC139_00 = can.Message(arbitration_id=0x139,
                               data=[0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                               extended_id=False)
    cmdSHORT_UPLOAD_FSFC_f_ABS_Op = can.Message(arbitration_id=0x7e0,
                                                data=[0xF4, 0x01, 0x00, 0x00, 0x5C, 0x24, 0x04, 0x90],
                                                extended_id=False)

    # APP to APP
    # FSFC_f_Eye_Fail: 0x90042464
    # ACC_Main_f_fACCFail: 0x50016840
    # CUS_f_ACC_FAIL: 0x50016948
    # HMI_f_ACCFail: 0x90042F58
    # SAS_f_ACCFail: 0x9004BBD4
    cmdSET_MTA_FSFC_f_Eye_Fail = can.Message(arbitration_id=0x7e0,
                                             data=[0xF6, 0x00, 0x00, 0x00, 0x64, 0x24, 0x04, 0x90],
                                             extended_id=False)
    cmdSHORT_UPLOAD_ACC_Main_f_fACCFail = can.Message(arbitration_id=0x7e0,
                                                      data=[0xF4, 0x01, 0x00, 0x00, 0x40, 0x68, 0x01, 0x50],
                                                      extended_id=False)
    cmdSHORT_UPLOAD_CUS_f_ACC_FAIL = can.Message(arbitration_id=0x7e0,
                                                 data=[0xF4, 0x01, 0x00, 0x00, 0x48, 0x69, 0x01, 0x50],
                                                 extended_id=False)
    cmdSHORT_UPLOAD_HMI_f_ACCFail = can.Message(arbitration_id=0x7e0,
                                                data=[0xF4, 0x01, 0x00, 0x00, 0x58, 0x2F, 0x04, 0x90],
                                                extended_id=False)
    cmdSHORT_UPLOAD_SAS_f_ACCFail = can.Message(arbitration_id=0x7e0,
                                                data=[0xF4, 0x01, 0x00, 0x00, 0xD4, 0xBB, 0x04, 0x90],
                                                extended_id=False)

    # APP to CAN
    # FSFC_f_ACCFailForVDC: 0x90042460
    # EYE220_4_5_FAIL_ACC_FOR_VDC: CH 4
    cmdSET_MTA_FSFC_f_ACCFailForVDC = can.Message(arbitration_id=0x7e0,
                                                  data=[0xF6, 0x00, 0x00, 0x00, 0x60, 0x24, 0x04, 0x90],
                                                  extended_id=False)

    # For polling signals
    # ACC_Main_ACCSelectObj -
    cmdSHORT_UPLOAD1 = can.Message(arbitration_id=0x7e0,
                                   data=[0xF4, 0x01, 0x00, 0x00, 0x14, 0x68, 0x00, 0x50],
                                   extended_id=False)
    # VDC_ACCSelectObj - 50017f1c
    cmdSHORT_UPLOAD2 = can.Message(arbitration_id=0x7e0,
                                   data=[0xF4, 0x01, 0x00, 0x00, 0x1C, 0x7F, 0x01, 0x50],
                                   extended_id=False)

    # For update
    cmdSET_MTA1 = can.Message(arbitration_id=0x7e0,
                              data=[0xF6, 0x00, 0x00, 0x00, 0x14, 0x68, 0x00, 0x50],
                              extended_id=False)

    iTest = InterfaceTest()

    iTest.connect(iTest.bus2)

    # task1 = iTest.start_polling(iTest.bus2, cmdSHORT_UPLOAD1, 0.050)
    task2 = iTest.start_polling(iTest.bus2, cmdSHORT_UPLOAD2, 0.010)
    #
    # iTest.send_once(iTest.bus2, cmdSHORT_UPLOAD2)
    # iTest.send_once(iTest.bus2, cmdSET_MTA1)
    # iTest.send_once(iTest.bus2, cmdDOWNLOAD_OFF)
    # sleep(3)
    iTest.send_once(iTest.bus2, cmdSET_MTA1)
    iTest.send_once(iTest.bus2, cmdDOWNLOAD_ON)
    sleep(3)
    iTest.send_once(iTest.bus2, cmdSET_MTA1)
    iTest.send_once(iTest.bus2, cmdDOWNLOAD_OFF)
    sleep(3)
    #
    # iTest.end_polling(task1)
    iTest.end_polling(task2)
    #
    iTest.end_logging()

    iTest.disconnect(iTest.bus2)


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

