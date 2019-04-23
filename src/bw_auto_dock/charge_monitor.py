#!/usr/bin/env python
# encoding=utf-8
"""
电量监控服务，当电量太低的时候，启动自动充电
"""

import rospy
import time
import struct
from galileo_serial_server.msg import GalileoStatus, GalileoNativeCmds
from threading import _start_new_thread
from std_msgs.msg import String

GALILEO_PUB = None
AUDIO_PUB = None
CHARGE_GOAL = None
LAST_CHARGE_CMD_TIME = 0
POWER_LOW = 36.0
CURRENT_STATUS = None


def update_status(status):
    global GALILEO_PUB, CHARGE_GOAL, LAST_CHARGE_CMD_TIME, POWER_LOW, CURRENT_STATUS
    now = int(time.time() * 1000)
    CURRENT_STATUS = status
    # 5min内只能发送一次充电指令
    if now - LAST_CHARGE_CMD_TIME < 5 * 60 * 1000:
        return
    if GALILEO_PUB is None:
        return
    if CHARGE_GOAL is None:
        return
    # 只在导航模式下启动
    if status.navStatus != 1:
        return
    if status.visualStatus != 1:
        return
    if status.chargeStatus == 1 or status.chargeStatus == 2:
        # 正在充电或已经充满
        return
    if status.busyStatus == 1:
        return
    if status.power < POWER_LOW:
        LAST_CHARGE_CMD_TIME = now
        _start_new_thread(charge_task, ())


def charge_task():
    time.sleep(10)
    AUDIO_PUB.publish("电量低，开始自动返回充电")
    global GALILEO_PUB, CHARGE_GOAL, CURRENT_STATUS
    # 停止巡检任务
    galileo_cmds = GalileoNativeCmds()
    galileo_cmds.data = 'm' + chr(0x06)
    galileo_cmds.length = len(galileo_cmds.data)
    galileo_cmds.header.stamp = rospy.Time.now()
    GALILEO_PUB.publish(galileo_cmds)
    # reset goal
    galileo_cmds = GalileoNativeCmds()
    galileo_cmds.data = 'g' + 'r' + chr(0x00)
    galileo_cmds.length = len(galileo_cmds.data)
    galileo_cmds.header.stamp = rospy.Time.now()
    GALILEO_PUB.publish(galileo_cmds)
    # insert charge goal
    previous_goal_num = int(rospy.get_param("/galileo/goal_num", 0))
    pos_x = struct.pack("f", CHARGE_GOAL["x"])
    pos_y = struct.pack("f", CHARGE_GOAL["y"])
    galileo_cmds.data = 'g' + 'i'
    galileo_cmds.data += pos_x
    galileo_cmds.data += pos_y
    galileo_cmds.length = len(galileo_cmds.data)
    GALILEO_PUB.publish(galileo_cmds)
    charge_goal_index = int(rospy.get_param("/galileo/goal_num", 0)) - 1
    while previous_goal_num > charge_goal_index:
        # 等待插入点完成
        print("等待插入点完成")
        charge_goal_index = int(rospy.get_param("/galileo/goal_num", 0)) - 1
    # start the goal
    galileo_cmds.data = 'g' + chr(charge_goal_index)
    galileo_cmds.length = len(galileo_cmds.data)
    GALILEO_PUB.publish(galileo_cmds)
    # wait goal start
    while CURRENT_STATUS.targetNumID != charge_goal_index:
        print("等待导航任务启动")
        time.sleep(1)
    # wait for goal complete
    while CURRENT_STATUS.targetNumID == charge_goal_index and not (CURRENT_STATUS.targetStatus == 0 or CURRENT_STATUS.targetStatus == -1):
        time.sleep(1)
    if CURRENT_STATUS.targetStatus == 0:
        # reset goal
        galileo_cmds = GalileoNativeCmds()
        galileo_cmds.data = 'g' + 'r' + chr(0x00)
        galileo_cmds.length = len(galileo_cmds.data)
        galileo_cmds.header.stamp = rospy.Time.now()
        GALILEO_PUB.publish(galileo_cmds)
        # start local charge
        galileo_cmds.data = 'j' + chr(0x00)
        galileo_cmds.length = len(galileo_cmds.data)
        galileo_cmds.header.stamp = rospy.Time.now()
        GALILEO_PUB.publish(galileo_cmds)


if __name__ == "__main__":
    rospy.init_node("charge_monitor")
    status_monitor_sub = rospy.Subscriber(
        "/galileo/status", GalileoStatus, update_status)
    GALILEO_PUB = rospy.Publisher(
        "/galileo/cmds", GalileoNativeCmds, queue_size=5)
    AUDIO_PUB = rospy.Publisher(
        "/xiaoqiang_tts/text", String, queue_size=1
    )
    POWER_LOW = float(rospy.get_param("~power_low", "36.0"))
    # 计算充电桩位置
    station_filename = rospy.get_param(
        "~station_filename", default="/home/xiaoqiang/slamdb/dock_station.txt")
    with open(station_filename) as station_file:
        station_info = station_file.read()
        lines = station_info.split('\n')
        line_data = lines[0].split(' ')
        ref_point1 = {
            "x": float(line_data[0]),
            "y": float(line_data[1]),
        }
        line_data = lines[1].split(' ')
        ref_point2 = {
            "x": float(line_data[0]),
            "y": float(line_data[1]),
        }
        line_data = lines[2].split(' ')
        docker_point = {
            "x": float(line_data[0]),
            "y": float(line_data[1]),
            "theta": float(line_data[2])
        }
        CHARGE_GOAL = {
            "x": (ref_point1["x"] + ref_point2["x"]) / 2,
            "y": (ref_point1["y"] + ref_point2["y"]) / 2
        }

    while not rospy.is_shutdown():
        time.sleep(1)