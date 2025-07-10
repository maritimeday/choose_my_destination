import requests
import time
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsField, QgsCoordinateReferenceSystem, QgsCoordinateTransform
)
from .choose_my_destination_dialog import ChooseMyDestinationDialog
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import QObject
import os
from .transform import wgs2gcj, gcj2wgs

# 顶部统一导入QGIS核心类
# from qgis.core import (
#     QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsField, QgsCoordinateReferenceSystem, QgsCoordinateTransform
# )

def get_travel_time_amap(origin, dest, mode, key, city=None, dlg=None):
    o_gcj = wgs2gcj(*origin)
    d_gcj = wgs2gcj(*dest)
    try:
        if mode == 'transit':
            url = f'https://restapi.amap.com/v3/direction/transit/integrated?origin={o_gcj[0]},{o_gcj[1]}&destination={d_gcj[0]},{d_gcj[1]}&city={city}&key={key}'
            resp = requests.get(url).json()
            if resp['status'] == '1' and resp['route']['transits']:
                transit = resp['route']['transits'][0]
                duration = float(transit['duration'])
                distance = float(transit['distance'])
                return duration, distance
            else:
                if dlg:
                    info = resp.get('info', resp.get('errmsg', '未知错误'))
                    dlg.append_log(f"终点可达性获取失败: {info}")
                return float('inf'), float('inf')
        elif mode == 'bicycling':
            url = f'https://restapi.amap.com/v4/direction/bicycling?origin={o_gcj[0]},{o_gcj[1]}&destination={d_gcj[0]},{d_gcj[1]}&key={key}'
            resp = requests.get(url).json()
            if resp.get('errcode', 1) == 0 and resp['data']['paths']:
                path = resp['data']['paths'][0]
                duration = float(path['duration'])
                distance = float(path['distance'])
                return duration, distance
            else:
                if dlg:
                    info = resp.get('errmsg', resp.get('info', '未知错误'))
                    dlg.append_log(f"终点可达性获取失败: {info}")
                return float('inf'), float('inf')
        else:
            url = f'https://restapi.amap.com/v3/direction/{mode}?origin={o_gcj[0]},{o_gcj[1]}&destination={d_gcj[0]},{d_gcj[1]}&key={key}'
            resp = requests.get(url).json()
            if resp['status'] == '1' and resp['route']['paths']:
                path = resp['route']['paths'][0]
                duration = float(path['duration'])
                distance = float(path['distance'])
                return duration, distance
            else:
                if dlg:
                    info = resp.get('info', '未知错误')
                    dlg.append_log(f"终点可达性获取失败: {info}")
                return float('inf'), float('inf')
    except Exception as e:
        if dlg:
            dlg.append_log(f"终点可达性获取异常: {e}")
        return float('inf'), float('inf')

def get_route_amap(origin, destination, mode, key, city=None, dlg=None):
    # origin, destination: WGS84经纬度
    o_gcj = wgs2gcj(*origin)
    d_gcj = wgs2gcj(*destination)
    try:
        if mode == 'bicycling':
            url = f'https://restapi.amap.com/v4/direction/bicycling?origin={o_gcj[0]},{o_gcj[1]}&destination={d_gcj[0]},{d_gcj[1]}&key={key}'
            resp = requests.get(url).json()
            if resp.get('errcode', 1) == 0 and resp['data']['paths']:
                route = resp['data']['paths'][0]
                polyline = []
                for step in route['steps']:
                    for pt in step['polyline'].split(';'):
                        lon, lat = map(float, pt.split(','))
                        polyline.append((lon, lat))
                return polyline
            else:
                if dlg:
                    dlg.append_log(f"路径API失败: url={url}")
                    dlg.append_log(f"路径API失败: resp={resp}")
                raise Exception('路径规划失败: ' + str(resp.get('errmsg', resp.get('info', '未知错误'))))
        elif mode == 'transit':
            if not city:
                raise Exception('公交模式下城市不能为空')
            url = f'https://restapi.amap.com/v3/direction/transit/integrated?origin={o_gcj[0]},{o_gcj[1]}&destination={d_gcj[0]},{d_gcj[1]}&city={city}&key={key}'
            resp = requests.get(url).json()
            if resp['status'] == '1' and resp['route']['transits']:
                transit = resp['route']['transits'][0]
                polyline = []
                for seg in transit['segments']:
                    pl = ''
                    if 'bus' in seg and seg['bus']['buslines']:
                        pl = seg['bus']['buslines'][0]['polyline']
                    elif 'walking' in seg and seg['walking']['steps']:
                        pl = ';'.join([step['polyline'] for step in seg['walking']['steps']])
                    for pt in pl.split(';'):
                        if pt:
                            lon, lat = map(float, pt.split(','))
                            polyline.append((lon, lat))
                return polyline
            else:
                if dlg:
                    dlg.append_log(f"路径API失败: url={url}")
                    dlg.append_log(f"路径API失败: resp={resp}")
                raise Exception('公交路径规划失败: ' + resp.get('info', ''))
        else:
            url = f'https://restapi.amap.com/v3/direction/{mode}?origin={o_gcj[0]},{o_gcj[1]}&destination={d_gcj[0]},{d_gcj[1]}&key={key}'
            resp = requests.get(url).json()
            if resp['status'] == '1' and resp['route']['paths']:
                route = resp['route']['paths'][0]
                polyline = []
                for step in route['steps']:
                    for pt in step['polyline'].split(';'):
                        lon, lat = map(float, pt.split(','))
                        polyline.append((lon, lat))
                return polyline
            else:
                if dlg:
                    dlg.append_log(f"路径API失败: url={url}")
                    dlg.append_log(f"路径API失败: resp={resp}")
                raise Exception('路径规划失败: ' + resp.get('info', ''))
    except Exception as e:
        if dlg:
            dlg.append_log(f"路径API异常: {e}")
        raise

def run_choose_my_destination(dlg):
    # 新增：支持起点图层-终点图层批量OD分析
    start_layer = getattr(dlg, 'get_start_layer', None)
    if start_layer and callable(start_layer):
        start_layer = dlg.get_start_layer()
    else:
        start_layer = None
    dest_layer = dlg.get_layer()
    field_weights = dlg.get_field_weights()
    dest_id_field = dlg.get_dest_id_field()
    normalize_settings = dlg.get_normalize_settings()
    mode = dlg.get_mode()
    export_path = dlg.get_export_path()
    key = dlg.get_key()
    city = None  # 可扩展为UI输入
    # 获取起点
    if start_layer:
        start_features = list(start_layer.getFeatures())
    else:
        # 单点模式
        start_pt = dlg.get_start_point()
        if not start_pt:
            dlg.append_log('请先输入或选择起点')
            return
        # 构造虚拟feature
        from qgis.core import QgsFeature, QgsGeometry, QgsPointXY
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*start_pt)))
        start_features = [f]
    dest_features = list(dest_layer.getFeatures())
    # 坐标转换器
    project_crs = dest_layer.crs()
    wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
    to_wgs84 = QgsCoordinateTransform(project_crs, wgs84, QgsProject.instance())
    # 结果列表 - 保存所有路径结果
    all_results = []
    best_results = []
    dlg.append_log(f"共{len(start_features)}个起点，{len(dest_features)}个目的地，开始批量OD分析...")
    for sidx, s in enumerate(start_features):
        # 起点坐标
        if start_layer:
            s_pt = s.geometry().asPoint()
            s_proj = s_pt
            s_wgs = to_wgs84.transform(s_pt)
            s_wgs_tuple = (float(s_wgs.x()), float(s_wgs.y()))
        else:
            s_proj = QgsPointXY(*start_pt)
            s_wgs_tuple = start_pt
        od_rows = []
        for didx, d in enumerate(dest_features):
            d_pt = d.geometry().asPoint()
            d_wgs = to_wgs84.transform(d_pt)
            d_wgs_tuple = (float(d_wgs.x()), float(d_wgs.y()))
            duration, distance = get_travel_time_amap(s_wgs_tuple, d_wgs_tuple, mode, key, city, dlg)
            # 添加延时避免API请求过于频繁
            time.sleep(0.5)  # 每次请求间隔0.5秒
            attrs = {field: d[field] for field in field_weights if field in d.fields().names()}
            attrs['可达性'] = duration
            attrs['距离'] = distance
            # 获取目的地ID字段值
            dest_id = d[dest_id_field] if dest_id_field in d.fields().names() else d.id()
            row = {
                'start': s, 'dest': d, 'duration': duration, 'distance': distance, 'attrs': attrs,
                's_proj': s_proj, 'd_proj': d_pt, 's_wgs': s_wgs_tuple, 'd_wgs': d_wgs_tuple,
                'dest_id': dest_id
            }
            od_rows.append(row)
            if duration == float('inf'):
                dlg.append_log(f"起点{sidx}→终点{didx} 可达性: infs")
            else:
                dlg.append_log(f"起点{sidx}→终点{didx} 可达性: {duration:.1f}s, 距离: {distance:.1f}m")
        # 标准化与加权得分
        all_fields = list(field_weights.keys()) + ['可达性']
        if normalize_settings['enabled']:
            for field in all_fields:
                values = [r['attrs'][field] for r in od_rows]
                if all(isinstance(v, (int, float)) for v in values):
                    min_v, max_v = min(values), max(values)
                    for r in od_rows:
                        if max_v > min_v:
                            if field == '可达性' and normalize_settings['type'] == '1-(value-min)/(max-min)':
                                # 可达性特殊处理：1-(cost-min)/(max-min)，这样耗时越短值越大
                                r['attrs'][field] = 1 - (r['attrs'][field] - min_v) / (max_v - min_v)
                            else:
                                # 其他字段或可达性的另一种归一化方式
                                r['attrs'][field] = (r['attrs'][field] - min_v) / (max_v - min_v)
                        else:
                            r['attrs'][field] = 0.0
        for r in od_rows:
            score = sum(r['attrs'][field] * field_weights[field] for field in field_weights if isinstance(r['attrs'][field], (int, float)))
            # 可达性得分处理
            if normalize_settings['enabled']:
                # 如果启用了归一化，可达性已经标准化为正值
                score += r['attrs']['可达性'] * field_weights.get('可达性', 1.0)
            else:
                # 如果没有启用归一化，可达性越小越好，所以用负值
                accessibility_score = -r['attrs']['可达性'] * field_weights.get('可达性', 1.0)
                score += accessibility_score
            r['score'] = score
        # 选出最优终点（得分最高）
        best = max(od_rows, key=lambda r: r['score'])
        best_dest = best['dest']
        # 高亮最佳目的地
        dest_layer.selectByIds([best_dest.id()])
        dlg.append_log(f"起点{sidx}最优终点ID: {best_dest.id()}，属性: {best_dest.attributes()}")
        dlg.append_log(f"最优终点得分: {best['score']:.2f}，耗时: {best['duration']:.1f}s")
        # 保存所有结果和最佳结果
        all_results.extend(od_rows)
        best_results.append(best)
    # 导出OD汇总csv - 导出所有路径结果
    if export_path:
        try:
            import csv
            csv_path = export_path if export_path.endswith('.csv') else export_path + '.csv'
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                # 字段头
                start_fields = ['start_id']
                dest_fields = ['dest_id'] + list(field_weights.keys())
                writer.writerow(start_fields + dest_fields + ['duration', 'distance', 'score'])
                for r in all_results:
                    s_id = r['start'].id() if start_layer else 0
                    d_id = r['dest_id']  # 使用选择的目的地ID字段值
                    dest_vals = [r['dest'][field] if field in r['dest'].fields().names() else '' for field in field_weights]
                    writer.writerow([s_id] + [d_id] + dest_vals + [r['duration'], r['distance'], r.get('score', '')])
            dlg.append_log(f'已导出所有OD路径csv：{csv_path}')
        except Exception as e:
            dlg.append_log(f'OD汇总csv导出出错: {e}')
    # 导出路径图层 - 只导出最佳路径
    if export_path:
        try:
            crs_proj = QgsProject.instance().crs()
            crs_wgs = QgsCoordinateReferenceSystem('EPSG:4326')
            xform_to_proj = QgsCoordinateTransform(crs_wgs, crs_proj, QgsProject.instance())
            vl = QgsVectorLayer(f'LineString?crs={crs_proj.authid()}', '最佳OD路径', 'memory')
            pr = vl.dataProvider()
            # 字段
            pr.addAttributes([
                QgsField('start_id', 4),
                QgsField('dest_id', 10),  # 改为字符串类型以支持自定义ID
                QgsField('duration', 6, 'double'),
                QgsField('distance', 6, 'double'),
                QgsField('score', 6, 'double'),
            ] + [QgsField(f, 10) for f in field_weights])
            vl.updateFields()
            for r in best_results:
                if r['duration'] == float('inf'):
                    continue
                try:
                    polyline = get_route_amap(r['s_wgs'], r['d_wgs'], mode, key, city, dlg)
                    # 添加延时避免API请求过于频繁
                    time.sleep(0.5)  # 每次路径请求间隔0.5秒
                    points = []
                    for lon_gcj, lat_gcj in polyline:
                        lon_wgs, lat_wgs = gcj2wgs(lon_gcj, lat_gcj)
                        pt_wgs = QgsPointXY(lon_wgs, lat_wgs)
                        pt_proj = xform_to_proj.transform(pt_wgs)
                        points.append(pt_proj)
                    if not points:
                        continue
                    feat = QgsFeature()
                    feat.setGeometry(QgsGeometry.fromPolylineXY(points))
                    attrs = [r['start'].id() if start_layer else 0, r['dest_id'], r['duration'], r['distance'], r.get('score', '')]
                    attrs += [r['dest'][f] if f in r['dest'].fields().names() else '' for f in field_weights]
                    feat.setAttributes(attrs)
                    pr.addFeatures([feat])
                except Exception as e:
                    dlg.append_log(f'最佳路径导出出错: {e}')
            vl.updateExtents()
            QgsProject.instance().addMapLayer(vl)
            dlg.append_log('最佳OD路径图层已添加')
        except Exception as e:
            dlg.append_log(f'路径图层导出出错: {e}')

class ChooseMyDestination(QObject):
    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        self.action = None
        self.dlg = None
        self.plugin_dir = os.path.dirname(__file__)

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.action = QAction(QIcon(icon_path), "目的地优选", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("&目的地优选", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action:
            self.iface.removePluginMenu("&目的地优选", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    def run(self):
        if not self.dlg:
            self.dlg = ChooseMyDestinationDialog()
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow() 