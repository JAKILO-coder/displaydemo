import socketio
# import numpy as np
import time


def update_display_data(data):
    sio = socketio.Client()
    try:
        sio.connect('http://127.0.0.1:9000')
    except socketio.exceptions.ConnectionError:
        print('display socket not connect')
        return
    try:
        sio.emit('update_display_data', data)
    except socketio.exceptions.BadNamespaceError:
        print('connection error')
    print('display data update')


if __name__ == '__main__':
    data_list = [[[114.19907498038577, 22.329900192903423], [114.19924728766279, 22.330203159539693],
                  [114.19941479027733, 22.330001229595453]],
                 [[114.19938048828095, 22.33002068976063], [114.19999204671973, 22.33109449526779],
                  [114.19941432769986, 22.330001545365405]],
                 [[114.19931571211305, 22.33017041297731], [114.19942939888182, 22.33010716894877],
                  [114.19937814339744, 22.33013587295231]]]
    count = 0
    while 1:
        if count >= len(data_list):
            count = 0
        update_display_data(data_list[count])
        count += 1
        time.sleep(1)
    sio.disconnect()
