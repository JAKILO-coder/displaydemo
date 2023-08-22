import ast
import base64
import csv
import datetime
import json
import time
import zlib
import requests

from paho.mqtt import client as mqtt_client

# broker = 'mtr-uat-internal.smartsensing.biz'
# port = 4000
broker = '143.89.49.63'
port = 1883
topic = ["tester01"]

# lc engine mqtt subscriber

# utils
# timestamp convertor
def date2ts(date):
    return datetime.datetime.timestamp(datetime.datetime.strptime(date, "%Y/%m/%d %H%M:%S"))


def ts2date(timestamp):
    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y%m%d_%H%M%S")

# daily logger
log_date = ts2date(time.time()) + '.csv'
# headers = ['acc_x', 'acc_y', 'acc_z', 'gyro_x', 'gyro_y', 'gyro_z', 'mag_x', 'mag_y', 'mag_z', 'roll', 'pitch','yaw', 'ts']
f_rawdata = open('rawdata-'+log_date, 'a', newline='')
f_rawdata_csv = csv.writer(f_rawdata)

# database connection


def connect_mqtt():
    global f_rawdata_csv
    # global f_csv2
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print("Connected to MQTT Broker!")
            client.on_message = on_message
            client.subscribe('tester01')
        else:
            print("Failed to connect, return code %d\n", rc)

    def on_message(client, userdata, msg):

        # decompress msg.payload and save as rawdata log through logger
        msg_topic = msg.topic
        msg_payload = msg.payload
        rec_ts = time.time()
        rawdata = {
            'topic': msg_topic,
            'rec_ts': rec_ts,
            'rec_date': ts2date(rec_ts),
            'payload': msg_payload.decode("utf-8"),
        }
        f_rawdata_csv.writerow([json.dumps(rawdata)])

        # for API and display
        msg_payload_json = json.loads(msg_payload)
        print(msg_payload_json.keys())

        # save select rawdata into database
        # ble->signal_source
        # userID, userLoc, speed*, ts->online_status
        # userID, status?, batteryLevel, ts->heartbeat
        # userID, trace_log, ts->exception_collector
        # others->?

        label_online_status = {
            'userId': msg_payload_json['userId'],
            'x': msg_payload_json['userLoc']['lng'],
            'y': msg_payload_json['userLoc']['lat'],
            'speed_dist': msg_payload_json['userSpeedDist'],
            'speed_cum': msg_payload_json['userSpeedCumtrapz'],
            'speed_ped': msg_payload_json['userSpeedPedometer'],
            'battery': msg_payload_json['batteryLevel'],
        }

        label_signal_source = {
            'userId': msg_payload_json['userId'],
            'signal_source': msg_payload_json['ble'],
        }

        # print(label_signal_source)

        # poster
        response = requests.post(f'http://127.0.0.1:8009/update_label_status',
                                 json=label_online_status,
                                 auth=('INTERNAL_REQUEST_USERNAME', 'INTERNAL_REQUEST_PSW'),
                                 timeout=5)

        response = requests.post(f'http://127.0.0.1:8009/update_label_signal_source',
                                 json=label_signal_source,
                                 auth=('INTERNAL_REQUEST_USERNAME', 'INTERNAL_REQUEST_PSW'),
                                 timeout=5)

        drawer_??(label_online_status)


    # Set Connecting Client ID
    client = mqtt_client.Client()
    client.on_connect = on_connect
    client.connect(broker, port)
    return client


def publish(client):
    global msg_count
    while True:
        time.sleep(1)
        msg = f"messages: {msg_count}"
        result = client.publish(topic=topic, payload=msg, qos=2)
        # result: [0, 1]
        status = result[0]
        msg_count += 1
        print(client.is_connected())
        if status == 0:
            print(f"Send `{msg}` to topic `{topic}` {int(time.time())} {status}")
        else:
            print(f"Failed to send message to topic {topic} {status}")
            client.disconnect()
            client.reinitialise()
            break


# connect to mqtt forever
# keep trying to reconnect while loss connection
while 1:
    client1 = connect_mqtt()
    client1.loop_forever()
    client1.is_connected()
    # output the trace of loss connection and reconnect
