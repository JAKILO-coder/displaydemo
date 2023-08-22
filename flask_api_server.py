import flask
from flask import make_response, request, jsonify
# import utils.db_connector as db_connector
from collections import defaultdict
import logging
import json
import time
from threading import Thread, Lock
import requests
# from utils.security import decrypt
import sqlite3
from typing import Dict, Any, List, Tuple, Union
import traceback
import math
from functools import reduce
from multiprocessing.connection import Client
# from config import *
from random import randint

INTERNAL_REQUEST_USERNAME = 'INTERNAL_REQUEST_USERNAME'
INTERNAL_REQUEST_PSW = 'INTERNAL_REQUEST_PSW'
app = flask.Flask(__name__)

LON_LAT_TO_METER_FACTOR = 111194.926644

RESPONSE_TARGET_SIGNUP_SUCCESS_CODE = 200
RESPONSE_TARGET_NOT_YET_VALID_CODE = 201
RESPONSE_TARGET_VALID_WITH_NO_UPDATE_TASK_CODE = 202
RESPONSE_TARGET_VALID_WITH_UPDATE_TASK_CODE = 300
RESPONSE_INVALID_TARGET_CODE = 400

RECEIVE_DOWNLOAD_FAIL_CODE = 301
RECEIVE_MD5_INCORRECT_CODE = 302
RECEIVE_RUN_INTO_OTHER_ERROR_CODE = 303
RECEIVE_CODE_UPDATE_SUCCESS_CODE = 500

RESPONSE_NO_CONTENT_CODE = 204

# logging.basicConfig(level=logging.ERROR)   # note: I don't know why it's necessary
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s')

# note: Werkzeug logs basic request/response information to the 'werkzeug' logger.
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.ERROR)

logger = logging.getLogger('flask_api_server')

import datetime


def ts2date(timestamp):
    return (datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S'))


# logger.setLevel(logging.DEBUG)

# todo: to-be-defined read in database or hard code
# MAPS = {
#     11:[[12705533.454438854,2483584.18816789,1],[12705533.234537795,2483575.9300001203,1],[12705530.331842283,2483576.011361375,1],[12705530.287862247,2483584.025445371,1]],
#     12:[[12705532.3109529,2483586.2628792073,1],[12705532.442893602,2483584.1474872245,1],[12705517.709515275,2483584.4729321357,1],[12705518.149317687,2483585.9781148466,1]],
#     13:[[12705532.398913553,2483593.9921937142,1],[12705532.486874063,2483586.4256016226,1],[12705529.936020462,2483586.1408370608,1],[12705530.067961156,2483593.936823757,1]],
#     14:[[12705531.079506567,2483595.2792832297,1],[12705531.343387958,2483592.960489454,1],[12705530.111941345,2483593.326614868,1],[12705529.89204028,2483595.2386026843,1]],
#     15:[[12705525.537996914,2483595.035199934,1],[12705525.588564396,2483575.2149595823,1],[12705524.533038812,2483575.2149595823,1],[12705524.137216568,2483595.0671002134,1]],
#     16:[[12705519.387351278,2483595.43322551,1],[12705519.827153705,2483575.2149595823,1],[12705518.155904813,2483575.2963208454,1],[12705517.628141878,2483595.3111837856,1]],
# }


def _particle_within_range(pos: Tuple[float, float],
                           polygon: List[Tuple[float, float, float]]) -> bool:
    # todo: not 3d checking
    # todo: should at least consider polygon in different floors
    res = False

    p1, p2, p3, p4 = polygon
    p1_p2_cross_product_p1_p = (p1[0] - p2[0]) * (p1[1] - pos[1]) - (p1[1] - p2[1]) * (p1[0] - pos[0])
    p3_p4_cross_product_p3_p = (p3[0] - p4[0]) * (p3[1] - pos[1]) - (p3[1] - p4[1]) * (p3[0] - pos[0])

    p1_p4_cross_product_p1_p = (p1[0] - p4[0]) * (p1[1] - pos[1]) - (p1[1] - p4[1]) * (p1[0] - pos[0])
    p3_p2_cross_product_p3_p = (p3[0] - p2[0]) * (p3[1] - pos[1]) - (p3[1] - p2[1]) * (p3[0] - pos[0])
    res |= (p1_p2_cross_product_p1_p * p3_p4_cross_product_p3_p >= 0) and (
                p1_p4_cross_product_p1_p * p3_p2_cross_product_p3_p >= 0)
    return res


# todo: write error log to database and sys.stdout
# todo: write info log to sys.stdout and
# todo: enable debug log when have no idea what's going on in app

class Cache:
    __to_be_registered_targets = {}  # {target_identifier: label}
    __invalid_targets = {}
    __registered_targets = {}

    __registered_sources = set()

    __ota_targets = {}  # {target_identifier: {label, md5, ts_create, ts_update}}

    __data_result = defaultdict(
        dict)  # note: {sensor_ble_mac:{vm,hci_status(arr),loc_x,loc_y,loc_z,vel_x,vel_y,vel_z,alarm_flag,location_ts,heartbeat_ts}}
    __data_beacon = defaultdict(dict)  # note: {major_minor: {vm, mac, ts, rssi, sensor_ble_mac}}
    __db_conn = None

    __loc_lock = Lock()
    __raw_lock = Lock()
    __target_registration_table_lock = Lock()
    __beacon_registration_table_lock = Lock()
    __ota_table_lock = Lock()
    __history_vel_norm = {}

    beacon_n = 0
    imu_n = 0

    @classmethod
    def init(cls):
        pass
        # try:
        #     cls.__db_conn = db_connector.DataBaseConnector(**DB_CONNECT_INFO)
        # except:
        #     logging.error(traceback.format_exc())
        #     logging.error("Unable to connect to database, terminate the whole API Server")
        #     exit(0)
        # else:
        #     Thread(target=cls.keep_update_target_registration_table).start()
        #     Thread(target=cls.keep_update_source_registration_table).start()
        #     Thread(target=cls.keep_update_ota_table).start()

    @classmethod
    def keep_update_target_registration_table(cls):
        while True:
            sensors = cls.__db_conn.query_full_table('sensor', 'sensor', 'label', 'valid')

            with cls.__target_registration_table_lock:
                to_be_registered_targets = {}
                invalid_targets = {}
                registered_targets = {}
                for sensor_ble_mac, label, valid_flag in sensors:
                    sensor_ble_mac = sensor_ble_mac.lower()
                    if valid_flag == 1:
                        registered_targets[sensor_ble_mac] = label
                    elif valid_flag == -1:
                        to_be_registered_targets[sensor_ble_mac] = label
                    elif valid_flag == 0:
                        invalid_targets[sensor_ble_mac] = label
                    else:
                        logger.warning("error valid flag in registration_table")

                cls.__to_be_registered_targets = to_be_registered_targets
                cls.__invalid_targets = invalid_targets
                cls.__registered_targets = registered_targets
            logger.debug('registered_targets', cls.__registered_targets)
            with cls.__loc_lock:
                for target_identifier, label in cls.__registered_targets.items():
                    target_identifier = target_identifier.lower()
                    if target_identifier not in cls.__data_result:
                        cls.__data_result[target_identifier] = {'site': None,
                                                                'loc_x': None,
                                                                'loc_y': None,
                                                                'loc_z': None,
                                                                'vel_x': None,
                                                                'vel_y': None,
                                                                'vel_z': None,
                                                                'alarm_flag': None,
                                                                'vel_norm': None,
                                                                'location_ts': None,
                                                                'hci_status': None,
                                                                'hci_ts': None,
                                                                'vm': None,
                                                                'history_vel': [0.] * 10,
                                                                'faster_flag': None,
                                                                'label': label,
                                                                'beacon_n': None,
                                                                'imu_n': None,
                                                                'beacon_n_ts': None,
                                                                'imu_n_ts': None,
                                                                'cpu_t': None,
                                                                'cpu_u': None,
                                                                'sd': None,
                                                                }
                removed_list = []
                for target_identifier, info in cls.__data_result.items():
                    # target_identifier = target_identifier.lower()
                    if target_identifier not in cls.__registered_targets:
                        removed_list.append(target_identifier)
                for to_be_removed_target_ident in removed_list:
                    del cls.__data_result[to_be_removed_target_ident]
            logger.debug('updated_sensor_table', cls.__data_result)
            time.sleep(60)

    @classmethod
    def keep_update_source_registration_table(cls):
        while True:
            sources = cls.__db_conn.query_full_table('source_release', 'name', 'site', 'label', 'lng', 'lat', 'floor')

            with cls.__beacon_registration_table_lock:
                registered_sources = set()
                for source_identifier, site, label, lng, lat, floor in sources:
                    source_identifier = source_identifier.lower()
                    registered_sources.add(source_identifier)
                cls.__registered_sources = registered_sources

            with cls.__raw_lock:
                source_identifiers = set()
                for source_identifier, site, label, lng, lat, floor in sources:
                    source_identifiers.add(source_identifier)
                    source_identifier = source_identifier.lower()
                    if source_identifier not in cls.__data_beacon:
                        cls.__data_beacon[source_identifier] = {'site': site,
                                                                'sensor_ble_mac': None,
                                                                'mac': None,
                                                                'vm': None,
                                                                'rssi': None,
                                                                'ts': None,
                                                                'lng': lng,
                                                                'lat': lat,
                                                                'floor': floor,
                                                                'label': label,
                                                                }
            removed_list = []
            for source_identifier, info in cls.__data_beacon.items():
                source_identifier = source_identifier.lower()
                if source_identifier not in source_identifiers:
                    removed_list.append(source_identifier)
            for to_be_removed_target_ident in removed_list:
                del cls.__data_result[to_be_removed_target_ident]
            logger.debug('updated beacon_table', cls.__data_beacon)
            time.sleep(60)

    @classmethod
    def keep_update_ota_table(cls):
        while True:
            records = cls.__db_conn.query_latest_updating_table_info()
            new_ota_target = {}
            for target_ident, ts_create, code_label, code_md5, ts_update in records:
                new_ota_target[target_ident] = {'label': code_label,
                                                'md5': code_md5,
                                                'ts_create': ts_create,
                                                'ts_update': ts_update,
                                                }
            with cls.__ota_table_lock:
                cls.__ota_targets = new_ota_target

            time.sleep(60)

    @classmethod
    def update_beacon_status(cls, data, *args, **kwargs):
        # store and refresh
        try:
            sensor_label = data['identifier'].lower()
            signal_receive_ts = float(data['timestamp'])
            vm = float(data['vm'])
            beacon_mac = data['beacon_mac'].lower()
            rssi = int(data['rssi'])

            major = str(data['major'])
            minor = str(data['minor'])
        # uuid = data['_value']['_value']['_uuid']
        except Exception as e:
            logger.error(traceback.format_exc())
        else:
            with cls.__raw_lock:
                with cls.__target_registration_table_lock:
                    source_identifier = major + minor
                    if source_identifier in cls.__data_beacon and sensor_label in cls.__registered_targets:
                        beacon_info = cls.__data_beacon[major + minor]
                        beacon_info['sensor_ble_mac'] = sensor_label
                        beacon_info['vm'] = vm
                        beacon_info['mac'] = beacon_mac
                        beacon_info['ts'] = signal_receive_ts
                        beacon_info['rssi'] = rssi

                        cls.__db_conn.insert_beacon_scan_data(vm=vm,
                                                              mac=beacon_mac,
                                                              major=int(major),
                                                              minor=int(minor),
                                                              rssi=rssi,
                                                              ts=(signal_receive_ts),
                                                              sensor=sensor_label,
                                                              )
                        if sensor_label in cls.__data_result:
                            cls.beacon_n += 1
                            if cls.__data_result[sensor_label]['beacon_n_ts']:
                                if (time.time() - cls.__data_result[sensor_label]['beacon_n_ts']) > 5:
                                    cls.beacon_n = 0
                            cls.__data_result[sensor_label]['beacon_n'] = cls.beacon_n
                            cls.__data_result[sensor_label]['beacon_n_ts'] = time.time()

    @classmethod
    def update_sensor_location(cls, data, *args, **kwargs):
        # store and refresh
        try:
            target_identifier = data['_identifier'].lower()
            location_ts = float(data['_timestamp'])
            vm = float(data['vm'])
            site = data['site']
            loc_x, loc_y, loc_z, vel_x, vel_y, vel_z, alarm_flag = float(
                data['_value']['_x']) / LON_LAT_TO_METER_FACTOR, \
                                                                   float(
                                                                       data['_value']['_y']) / LON_LAT_TO_METER_FACTOR, \
                                                                   int(data['_value']['_z']), \
                                                                   abs(round(float(data['_value']['_vx']), 2)), \
                                                                   abs(round(float(data['_value']['_vy']), 2)), \
                                                                   abs(round(float(data['_value']['_vz']), 2)), \
                                                                   int(data['_value']['_overspeed_alarm'])
        except Exception as e:
            logger.error(traceback.format_exc())
        else:
            with cls.__loc_lock:
                if target_identifier in cls.__data_result:
                    # note: if not registered, then ignore result
                    sensor_location = cls.__data_result[target_identifier]
                    sensor_location['location_ts'] = location_ts
                    sensor_location['vm'] = vm
                    sensor_location['loc_x'] = loc_x
                    sensor_location['loc_y'] = loc_y
                    sensor_location['loc_z'] = loc_z
                    sensor_location['vel_x'] = vel_x
                    sensor_location['vel_y'] = vel_y
                    sensor_location['vel_z'] = vel_z
                    sensor_location['alarm_flag'] = alarm_flag
                    sensor_location['site'] = site

                    cur_vel_norm = round(math.sqrt(vel_x ** 2 + vel_y ** 2), 2)
                    if cur_vel_norm > 2.3:
                        r_seed = randint(1, 4)
                        cur_vel_norm = 2.3
                        cur_vel_norm = cur_vel_norm - r_seed / 10

                    history_vel = sensor_location['history_vel']
                    history_vel.append(cur_vel_norm)
                    history_vel.pop(0)
                    prev_vel, cur_vel = history_vel[-2], history_vel[-1]
                    if cur_vel > prev_vel:
                        faster_flag = 1
                    else:
                        faster_flag = -1
                    sensor_location['faster_flag'] = faster_flag
                    sensor_location['vel_norm'] = cur_vel_norm

                cls.__db_conn.insert_sensor_loc(ts=int(location_ts),
                                                vm=vm,
                                                pos_x=loc_x,
                                                pos_y=loc_y,
                                                pos_z=loc_z,
                                                vel_x=vel_x,
                                                vel_y=vel_y,
                                                vel_z=vel_z,
                                                alarm=alarm_flag,
                                                sensor=target_identifier,
                                                site_name=site,
                                                )

    @classmethod
    def update_system_status_monitoring(cls, data, *args, **kwargs):
        target_identifier = data['_identifier'].lower()
        sys_status = data['_status_dict']
        ts = int(data['_timestamp'])
        # print(target_identifier, sys_status)
        if target_identifier in cls.__data_result:
            # note: if not registered, then ignore result
            sensor_location = cls.__data_result[target_identifier]
            sensor_location['cpu_t'] = sys_status['CPU_T']
            sensor_location['cpu_u'] = sys_status['CPU_usg']
            sensor_location['sd'] = round(sys_status['sd_used']/sys_status['sd_total'], 2)
        cls.__db_conn.insert_system_status(sensor=target_identifier,
                                           cpu_clock_feq=sys_status['CPU_clock_feq'],
                                           cpu_usg=sys_status['CPU_usg'],
                                           cpu_t=sys_status['CPU_T'],
                                           pi_v=sys_status['pi_V'],
                                           arm_core_V=sys_status['arm_core_V'],
                                           ram_total=sys_status['RAM_total'],
                                           ram_used=sys_status['RAM_used'],
                                           ram_free=sys_status['RAM_free'],
                                           sd_total=sys_status['sd_total'],
                                           sd_used=sys_status['sd_used'],
                                           ts=ts,
                                           )

    @classmethod
    def update_sensor_running_status(cls, data, *args, **kwargs):
        target_identifier = data['_identifier'].lower()
        hci_status = data['_value']
        ts = float(data['_timestamp'])
        vm = float(data['vm'])
        logger.info(f"update HCI: {target_identifier}, {ts2date(ts)}")
        with cls.__loc_lock:
            if target_identifier in cls.__data_result:
                cls.__data_result[target_identifier]['hci_status'] = hci_status
                cls.__data_result[target_identifier]['hci_ts'] = ts
                cls.__data_result[target_identifier]['vm'] = vm
        # cls.__db_conn.insert_heartbeat(sensor=ble_mac,
        #                                hci_status=str(hci_status),
        #                                ts=heartbeat_ts,
        #                                vm=vm,
        #                                )

    @classmethod
    def update_imu_status(cls, data):
        # testing
        # pass
        # imu_table = cls.__mock_db['imu']
        # imu_table.insert_one(imu_data)
        sensor_label = data['identifier'].lower()
        # cls.__db_conn.insert_imu_data(vm=1,
        #                               ts=float(data['timestamp']),
        #                               sensor=data['identifier'].lower(),
        #                               acc_x=data['acc_x'],
        #                               acc_y=data['acc_y'],
        #                               acc_z=data['acc_z'],
        #                               gyro_x=data['gyro_x'],
        #                               gyro_y=data['gyro_y'],
        #                               gyro_z=data['gyro_z'],
        #                               mag_x=data['mag_x'],
        #                               mag_y=data['mag_y'],
        #                               mag_z=data['mag_z'],
        #                               roll=data['roll'],
        #                               pitch=data['pitch'],
        #                               yaw=data['yaw'],
        #                               q1=data['q1'],
        #                               q2=data['q2'],
        #                               q3=data['q3'],
        #                               q4=data['q4'],
        #                               )
        if sensor_label in cls.__data_result:
            cls.imu_n += 1
            if cls.__data_result[sensor_label]['imu_n_ts']:
                if (time.time() - cls.__data_result[sensor_label]['imu_n_ts']) > 5:
                    cls.imu_n = 0
            cls.__data_result[sensor_label]['imu_n'] = cls.imu_n
            cls.__data_result[sensor_label]['imu_n_ts'] = time.time()

    @classmethod
    def store_logs(cls, log_msg):
        ts = log_msg['timestamp']
        level = log_msg['level']
        msg = log_msg['msg']
        src_type = log_msg['src_type']

        cls.__db_conn.insert_log(ts=ts,
                                 src_type=src_type,
                                 content=str(msg),
                                 level=level,
                                 )

    @classmethod
    def get_latest_beacon_status(cls, *args, **kwargs):
        with cls.__raw_lock:
            return cls.__data_beacon

    @classmethod
    def get_latest_target_status(cls, *args, **kwargs):
        return cls.__data_result

    @classmethod
    def update_code_download_record(cls, target_identifier, receive_md5, receive_ts_create, receive_code):
        # logger.info(f'{target_identifier} response update state:'
        #             f' receive md5={receive_md5}, '
        #             f' receive_ts_create={receive_ts_create},'
        #             f' receive code={receive_code}')
        if receive_code == RECEIVE_CODE_UPDATE_SUCCESS_CODE:
            target_identifier = target_identifier.lower()
            if cls.__db_conn.insert_code_update_timestamp(target_identifier=target_identifier,
                                                          md5=receive_md5,
                                                          ts_update=int(time.time()),
                                                          ts_create=receive_ts_create):
                if target_identifier in cls.__ota_targets:
                    code_md5 = cls.__ota_targets[target_identifier]['md5']
                    ts_create = cls.__ota_targets[target_identifier]['ts_create']
                    if ts_create == receive_ts_create and code_md5 == receive_md5:
                        with cls.__ota_table_lock:
                            del cls.__ota_targets[target_identifier]
                logger.info(f'{target_identifier} update success')
            else:
                logger.info('unable to update code download record')
        elif receive_code == RECEIVE_DOWNLOAD_FAIL_CODE:
            logger.info('RECEIVE_DOWNLOAD_FAIL_CODE')
        elif receive_code == RECEIVE_MD5_INCORRECT_CODE:
            logger.info('RECEIVE_MD5_INCORRECT_CODE')
        elif receive_code == RECEIVE_RUN_INTO_OTHER_ERROR_CODE:
            logger.info('RECEIVE_RUN_INTO_OTHER_ERROR_CODE')

    @classmethod
    def get_target_latest_code_vm(cls, target_identifier) -> Tuple[Union[Dict, None], int]:
        logger.info(f'{target_identifier.lower()} request for latest code')
        target_identifier = target_identifier.lower()

        if target_identifier not in cls.__registered_targets:
            if target_identifier in cls.__invalid_targets:
                return None, RESPONSE_INVALID_TARGET_CODE
            elif target_identifier in cls.__to_be_registered_targets:
                return None, RESPONSE_TARGET_NOT_YET_VALID_CODE
            else:
                cls.__db_conn.insert_sensor(ts_create=int(time.time()),
                                            sensor=target_identifier)
                cls.__to_be_registered_targets[target_identifier] = None
                return None, RESPONSE_TARGET_SIGNUP_SUCCESS_CODE

        if target_identifier in cls.__ota_targets:
            with cls.__ota_table_lock:
                code_label = cls.__ota_targets[target_identifier]['label']
                code_md5 = cls.__ota_targets[target_identifier]['md5']
                ts_create = cls.__ota_targets[target_identifier]['ts_create']
                ts_update = cls.__ota_targets[target_identifier]['ts_update']
                return {'target_identifier': target_identifier,
                        'label': code_label,
                        'md5': code_md5,
                        'ts_create': ts_create,
                        'ts_update': ts_update,
                        }, RESPONSE_TARGET_VALID_WITH_UPDATE_TASK_CODE
        else:
            return None, RESPONSE_TARGET_VALID_WITH_NO_UPDATE_TASK_CODE

    @classmethod
    def get_history_sensors_status(cls, s_ts, e_ts) -> Union[List, None]:
        # todo: bug, don't know why request will crash the application, even if the request is correct
        # example: curl http://10.2.1.4:8080/history_sensor_status/1616515200/1616652823
        try:
            records = cls.__db_conn.query_history_sensors_trajectory(s_ts, e_ts)
            logger.debug(records)
            res = []
            for sensor, pos_x, pos_y, pos_z, vel_x, vel_y, vel_z, alarm, vm, ts, site_name in records:
                # {device_id, vel_x, vel_y, loc_x, loc_y, loc_z, alarm, ts, vm}
                res.append({'sensor': sensor.lower(),
                            'loc_x': pos_x,
                            'loc_y': pos_y,
                            'loc_z': pos_z,
                            'vel_x': vel_x,
                            'vel_y': vel_y,
                            'alarm': alarm,
                            'ts': ts,
                            'vm': vm,
                            'site_name': site_name,
                            })
        except Exception:
            logger.error(traceback.format_exc())
            return None
        else:
            if res:
                return res
            return None

    @classmethod
    def get_report(cls, s_ts, e_ts):
        # todo
        pass

    # @classmethod
    # def get_sensor_site(cls, sensor_ble_mac):
    #     if hasattr(cls, '__db_conn'):
    #         cls.__registration_table_lock.acquire()
    #         if sensor_ble_mac in cls.ble_mac_registration_table:
    #             res = cls.ble_mac_registration_table[sensor_ble_mac]
    #         else:
    #             res = {'sensor': sensor_ble_mac, 'site': 'None', 'label': 'None', 'id': 'None', 'ts_create': None}
    #         cls.__registration_table_lock.release()
    #         return res
    #     else:
    #         return {'fake': True, 'sensor': sensor_ble_mac, 'site': 'KOB', 'label': None, 'id': 1, 'ts_create': 1234567890}
    #


@app.route('/latest_sensor_status', methods=['get', 'post'])
def latest_sensor_status():
    res = make_response(Cache.get_latest_target_status())
    res.headers['Access-Control-Allow-Origin'] = '*'
    res.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    res.headers['Access-Control-Allow-Headers'] = 'x-requested-with, content-type'
    return res


@app.route('/latest_beacon_status', methods=['get', 'post'])
def latest_beacon_status():
    site = request.args.get('site', default='', type=str)
    res = make_response(Cache.get_latest_beacon_status(site))
    res.headers['Access-Control-Allow-Origin'] = '*'
    res.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    res.headers['Access-Control-Allow-Headers'] = 'x-requested-with, content-type'
    return res


@app.route('/latest_code_info', methods=['get', 'post'])
def latest_code_info():
    code_request_info = request.get_json()
    if 'target_ble_mac' in code_request_info:
        target_ble_mac = code_request_info['target_ble_mac']
        res, code = Cache.get_target_latest_code_vm(target_ble_mac)
        if isinstance(res, dict):
            res = make_response(jsonify(res), RESPONSE_TARGET_VALID_WITH_UPDATE_TASK_CODE)
        elif isinstance(res, int):
            res = make_response(jsonify({'message': 'fail'}), code)
        else:
            res = make_response(jsonify({'message': 'fail'}), code)
    else:
        res = make_response(jsonify({'message': 'fail'}), RESPONSE_NO_CONTENT_CODE)
    res.headers['Access-Control-Allow-Origin'] = '*'
    res.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    res.headers['Access-Control-Allow-Headers'] = 'x-requested-with, content-type'
    return res


# todo: have to access database
@app.route('/history_sensor_status/<int:s_ts>/<int:e_ts>', methods=['get', 'post'])
def history_sensor_status(s_ts, e_ts):
    res = Cache.get_history_sensors_status(s_ts, e_ts)
    if res:
        res = make_response(jsonify(res), 200)
    else:
        res = make_response(jsonify({'message': f'no data within this time range: {s_ts} to {e_ts}'}), 200)
    res.headers['Access-Control-Allow-Origin'] = '*'
    res.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    res.headers['Access-Control-Allow-Headers'] = 'x-requested-with, content-type'
    return res


# todo: have to access database
@app.route('/report/<int:s_ts>/<int:e_ts>', methods=['get', 'post'])
def report(s_ts, e_ts):
    # todo: implementation
    # res = Cache.get_report(s_ts, e_ts)
    # if res:
    #     res = make_response(jsonify(res), 200)
    # else:
    #     res = make_response(jsonify({'message': 'no report'}), 200)
    res = make_response(jsonify({'message': 'no report functionality for now'}), 200)
    res.headers['Access-Control-Allow-Origin'] = '*'
    res.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    res.headers['Access-Control-Allow-Headers'] = 'x-requested-with, content-type'
    return res


@app.route('/update_code_update_record', methods=['get', 'post'])
def update_code_update_record():
    try:
        data = request.get_json()
        code = int(data['status_code']) if 'target_ble_mac' in data else None
        target_ble_mac = data['target_ble_mac'] if 'target_ble_mac' in data else None
        code_md5 = data['md5'] if 'md5' in data else None
        ts_create = data['ts_create'] if 'ts_create' in data else None
        Cache.update_code_download_record(target_identifier=target_ble_mac,
                                          receive_md5=code_md5,
                                          receive_ts_create=ts_create,
                                          receive_code=code)
    except Exception:
        logger.error(traceback.format_exc())
    finally:
        return make_response('', RESPONSE_NO_CONTENT_CODE)


# todo: move these functionality to cache
@app.route('/update_target_loc', methods=['get', 'post'])
def update_target_loc():
    if request.authorization is not None and request.authorization['username'] == INTERNAL_REQUEST_USERNAME and \
            request.authorization['password'] == INTERNAL_REQUEST_PSW:
        data = request.get_json()
        # logger.info(f"receive sensor result: {data}")
        Cache.update_sensor_location(data)
        response = make_response(jsonify({"message": "success"}), 200)
        return response
    else:
        response = make_response(jsonify({"message": "fail"}), 200)
    return response


@app.route('/update_sensor_running_status', methods=['get', 'post'])
def update_sensor_running_status():
    if request.authorization is not None and request.authorization['username'] == INTERNAL_REQUEST_USERNAME and \
            request.authorization['password'] == INTERNAL_REQUEST_PSW:
        data = request.get_json()
        # logger.info(f"receive sensor status: {data}")
        Cache.update_sensor_running_status(data)
        response = make_response(jsonify({"message": "success"}), 200)
        return response
    else:
        response = make_response(jsonify({"message": "fail"}), 200)
    return response


@app.route('/update_beacon_status', methods=['get', 'post'])
def update_beacon_status():
    if request.authorization is not None and request.authorization['username'] == INTERNAL_REQUEST_USERNAME and \
            request.authorization['password'] == INTERNAL_REQUEST_PSW:
        beacon_data = request.get_json()
        # logger.info(f"receive beacon_data: {beacon_data}")
        Cache.update_beacon_status(beacon_data)
        response = make_response(jsonify({"message": "success"}), 200)
    else:
        response = make_response(jsonify({"message": "fail"}), 200)
    return response


@app.route('/update_imu_status', methods=['get', 'post'])
def update_imu_status():
    if request.authorization is not None and request.authorization['username'] == INTERNAL_REQUEST_USERNAME and \
            request.authorization['password'] == INTERNAL_REQUEST_PSW:
        imu_data = request.get_json()
        # logger.info(f"receive request: {imu_data}")
        Cache.update_imu_status(imu_data)
        response = make_response(jsonify({"message": "success"}), 200)
    else:
        response = make_response(jsonify({"message": "fail"}), 200)
    return response


@app.route('/update_system_status_monitoring', methods=['get', 'post'])
def update_system_status_monitoring():
    if request.authorization is not None and request.authorization['username'] == INTERNAL_REQUEST_USERNAME and \
            request.authorization['password'] == INTERNAL_REQUEST_PSW:
        data = request.get_json()
        # logger.info(f"receive update_system_status_monitoring status: {data}")
        Cache.update_system_status_monitoring(data)
        response = make_response(jsonify({"message": "success"}), 200)
        return response
    else:
        response = make_response(jsonify({"message": "fail"}), 200)
    return response


@app.route('/update_daily_log', methods=['get', 'post'])
def update_daily_log():
    try:
        if request.authorization is not None and request.authorization['username'] == INTERNAL_REQUEST_USERNAME and \
                request.authorization['password'] == INTERNAL_REQUEST_PSW:
            l = request.get_json()
            logger.info(l)
            # Cache.store_logs(l)  # todo: write logs to database
            response = make_response(jsonify({"message": "success"}), 200)
        else:
            response = make_response(jsonify({"message": "fail, error psw or username"}), 200)
    except Exception:
        logger.error(traceback.format_exc())
        response = make_response(jsonify({"message": "fail, error occurs in api server"}), 200)
    return response

# ----------------------------- new -----------------------------

@app.route('/update_label_status', methods=['get', 'post'])
def update_label_status():
    try:
        if request.authorization is not None and request.authorization['username'] == INTERNAL_REQUEST_USERNAME and \
                request.authorization['password'] == INTERNAL_REQUEST_PSW:
            res = request.get_json()
            print(res)
            # logger.info(l)
            # Cache.store_logs(l)  # todo: write logs to database
            response = make_response(jsonify({"message": "success"}), 200)
        else:
            response = make_response(jsonify({"message": "fail, error psw or username"}), 200)
    except Exception:
        logger.error(traceback.format_exc())
        response = make_response(jsonify({"message": "fail, error occurs in api server"}), 200)
    return response

@app.route('/update_label_signal_source', methods=['get', 'post'])
def update_label_signal_source():
    try:
        if request.authorization is not None and request.authorization['username'] == INTERNAL_REQUEST_USERNAME and \
                request.authorization['password'] == INTERNAL_REQUEST_PSW:
            res = request.get_json()
            print(res)
            # logger.info(l)
            # Cache.store_logs(l)  # todo: write logs to database
            response = make_response(jsonify({"message": "success"}), 200)
        else:
            response = make_response(jsonify({"message": "fail, error psw or username"}), 200)
    except Exception:
        logger.error(traceback.format_exc())
        response = make_response(jsonify({"message": "fail, error occurs in api server"}), 200)
    return response


# @app.route('/id_request', methods=['get', 'post'])
# def id_request():
#     if request.authorization is not None and request.authorization['username'] == INTERNAL_REQUEST_USERNAME and request.authorization['password'] == INTERNAL_REQUEST_PSW:
#         id_req = request.get_json()
#         data = Cache.get_sensor_site(id_req['ble_mac'])
#         response = make_response(jsonify({'event_type': 'remote_request', 'data': {'site': data['site']}}), 200)
#     else:
#         response = make_response(jsonify({"message": "fail"}), 200)
#     return response


if __name__ == '__main__':
    Cache.init()
    app.run(port=8009, debug=True, host='127.0.0.1')
