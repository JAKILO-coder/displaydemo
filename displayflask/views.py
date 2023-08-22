import io
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
import re
from flask import (
    Flask,
    Blueprint,
    render_template,
    abort,
    current_app,
    make_response
)
import numpy as np
import matplotlib.colors as mcolors
import datetime
from datetime import datetime
from flask_socketio import SocketIO
import os


client = Blueprint('client', __name__, template_folder='templates', static_url_path='/static')
u_loc = np.array([[114.19907498038577,22.329900192903423], [114.19924728766279,22.330203159539693],
                 [114.19941479027733,22.330001229595453]])
u_id = np.array(['a', 'b', 'c'])
u_battery = np.array([1, 30, 99])

# pos_data = [0]
# w_data = [0]
# b_name = [0]
# b_strength = [0]
# time_stamp = 0
# user_speed1 = 0
# user_speed2 = 0
# user_speed3 = 0
# loc_std = 5
########################################################################################################
# codes to update these data from other service with socket
# import socketio
# def update_display_data(data):
#     sio = socketio.Client()
#     try:
#         sio.connect('http://127.0.0.1:9000')
#     except socketio.exceptions.ConnectionError:
#         print('display socket not connect')
#         return
#     try:
#         sio.emit('update_display_data', data)
#     except socketio.exceptions.BadNamespaceError:
#         print('connection error')
#     print('data update')

##################################################################################################################
# get map
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!1#
# use the map geo location here
file_path = 'KAT-polygon_source-geojson-1692267656.txt'  # 替换成你的文件路径
# file_path = '/home/mtrec/Desktop/mtr-py/mtr_py/flaskplotlib/KAT-polygon_source-geojson-1692267656.txt'

with open(file_path, 'r') as file:
    data = file.read()

# 提取数据
maps_start = data.find('MAPS = {')
maps_end = data.find('}', maps_start)
maps_data = data[maps_start + len('MAPS = {'):maps_end].strip()

# 解析多边形数据
polygon_name = []
polygon_location = []

for line in maps_data.split('\n'):
    parts = line.strip().split(':')
    if len(parts) == 2:
        key = parts[0].strip()
        value = parts[1].strip()
        if value.endswith(','):
            value = value[:-1]
        points = value.split('],')
        points_list = []
        for point in points:
            coords = point.strip('[]').split(',')
            x = float(coords[0])
            y = float(coords[1])
            z = int(coords[2])
            points_list.append([x, y, z])
        polygon_name.append(int(key))
        polygon_location.append(points_list)

# print("MAPS:", polygon_name, polygon_location)

# Extract data using regular expressions
source_name = []
source_location = []
source_info_match = re.findall(r"'(\d+)': SOURCE_INFO\(source_identifier='(\d+)', x=([\d.]+), y=([\d.]+), z=([\d.]+)",
                               data)

if source_info_match:
    source_info_dict = {}
    for identifier, _, x, y, z in source_info_match:
        source_name.append(int(identifier))
        source_location.append([float(x), float(y), float(z)])


def timestamp_to_string(timestamp):
    # 将时间戳转换成 datetime 对象
    dt_object = datetime.fromtimestamp(timestamp)

    # 格式化输出字符串
    formatted_string = dt_object.strftime("%Y-%m-%d %H:%M:%S")
    return formatted_string

# flask display client
@client.route('/')
def home():
    title = current_app.config['TITLE']
    b_strength_sort = []
    plot = plot_map(polygon_location=polygon_location, user_location=u_loc, user_id=u_id,
                    user_battery=u_battery)

    return render_template('index.html', title=title, plot=plot)


def plot_map(polygon_location, user_location, user_id, user_battery):
    # 创建一个绘图对象和一个子图
    fig, ax = plt.subplots(figsize=(13, 13))
    #     fig, ax = plt.subplots(figsize=(10, 5))

    #     绘制每一个多边形
    for polygon in polygon_location:
        polygon = np.array(polygon)
        x = polygon[:, 0]
        y = polygon[:, 1]
        z = polygon[:, 2]
        # 绘制多边形顶点
        ax.plot(x, y, '-', color='blue', linewidth=0.01)

        # 连接多边形的边
        ax.plot(np.append(x, x[0]), np.append(y, y[0]), color='blue')

        # 在多边形中间用浅蓝色填充
        ax.fill(x, y, color='lightblue')


    # plot user location
    ax.scatter(user_location[:, 0], user_location[:, 1], c="red", zorder=100, s=100, edgecolors='black',
               linewidths=1, marker='*')
    # plot user id
    for i in range(0, len(user_id)):
        ax.text(user_location[i, 0], user_location[i, 1], user_id[i],
                fontsize=20, ha='center', va='bottom', zorder=13, rotation=60)  # 在点旁边显示值

    # 设置绘图范围和标签
    ax.set_aspect('equal', adjustable='datalim')  # 保持纵横比相等
    # ax.set_xlabel('X')
    # ax.set_ylabel('Y')
    # ax.set_title('Polygon Vertices and Edges')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.set_xticklabels([])
    ax.set_yticklabels([])
    polygon_np = np.array(polygon_location)
    ax.set_xlim(polygon_np[:, :, 0].min() - 0.00005, polygon_np[:, :, 0].max() + 0.00005)  # 设置 x 坐标范围
    ax.set_ylim(polygon_np[:, :, 1].min() - 0.00005, polygon_np[:, :, 1].max() + 0.00005)  # 设置 y 坐标范围
    ax.tick_params(axis='both', which='both', bottom=False, top=False, left=False, right=False)

    #     print(np.array(polygon_location)[0, 0, :])
    # 显示绘图
    img = io.StringIO()
    fig.savefig(img, format='svg')
    # clip off the xml headers from the image
    svg_img = '<svg' + img.getvalue().split('<svg')[1]
    plt.clf()
    plt.close()

    return svg_img


# start website service
app = Flask(__name__)
app.register_blueprint(client)
app.config.from_object('config')
socket_display = SocketIO(app)


@socket_display.on('update_display_data')
def update_display_data(label_online_status):
    global u_loc, u_battery, u_id
    # all_location_x = label_online_status['userLoc']['lng']
    # all_location_y = label_online_status['userLoc']['lat']
    # all_id = label_online_status['userId']
    # all_battery = label_online_status['batteryLevel']

    # data reformat
    # u_loc_x = np.array(all_location_x.replace('[', '').replace(']', '').split(', '), dtype=float)
    # u_loc_y = np.array(all_location_y.replace('[', '').replace(']', '').split(', '), dtype=float)
    # u_loc_x = np.array(all_location_x)
    # u_loc_y = np.array(all_location_y)
    # u_loc = np.vstack(u_loc_x, u_loc_y)
    # u_id = np.array(all_id)
    # u_battery = np.array(all_battery)
    u_loc = np.array(label_online_status)
    print('display update data')

    # refresh website
    socket_display.emit('refresh_page')


port = int(os.environ.get('PORT', 9000))
socket_display.run(app, host='127.0.0.1', port=port, debug=True)
