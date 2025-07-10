import requests
import time
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsField, QgsCoordinateReferenceSystem, QgsCoordinateTransform
)
from .choose_my_destination_dialog import ChooseMyDestinationDialog
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtCore import QObject
import os
from .transform import wgs2gcj, gcj2wgs
import csv
from qgis.PyQt import QtWidgets
from qgis.core import QgsCategorizedSymbolRenderer, QgsSymbol, QgsRendererCategory

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
    field_settings = dlg.get_field_settings()
    accessibility_weight = dlg.get_accessibility_weight()  # 确保此处定义
    dest_id_field = dlg.get_dest_id_field()
    # 移除normalize_settings相关
    # normalize_settings = dlg.get_normalize_settings()  # 删除此行
    # 主逻辑其它地方不再用normalize_settings，全部用field_settings和accessibility_weight
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
    # 1. 设置进度条最大值和初始值
    total_count = len(dest_features)
    if hasattr(dlg, 'progressBar'):
        dlg.progressBar.setMaximum(total_count)
        dlg.progressBar.setValue(0)
        dlg.progressBar.setFormat(f"0/{total_count} (0.0%)")

    # 2. 数据收集、归一化、评分合并
    all_results = []
    best_result = None
    minmax = {}
    norm_fields = list(field_settings.keys()) + ['可达性']
    # 先收集所有原始值
    raw_values = {field: [] for field in norm_fields}
    for d in dest_features:
        for field in norm_fields:
            if field in d.fields().names() and isinstance(d[field], (int, float)):
                raw_values[field].append(d[field])
    # 主循环
    for idx, d in enumerate(dest_features):
        d_id = d[dest_id_field] if dest_id_field in d.fields().names() else d.id()
        d_pt = d.geometry().asPoint()
        d_wgs = to_wgs84.transform(d_pt)
        d_wgs_tuple = (float(d_wgs.x()), float(d_wgs.y()))
        if start_layer:
            s = start_features[0]
            s_pt = s.geometry().asPoint()
            s_proj = s_pt
            s_wgs = to_wgs84.transform(s_pt)
            s_wgs_tuple = (float(s_wgs.x()), float(s_wgs.y()))
        else:
            s_proj = QgsPointXY(*start_pt)
            s_wgs_tuple = start_pt
        duration, distance = get_travel_time_amap(s_wgs_tuple, d_wgs_tuple, mode, key, city, dlg)
        attrs = {field: d[field] for field in field_settings if field in d.fields().names() and isinstance(d[field], (int, float))}
        attrs['可达性'] = duration
        attrs['距离'] = distance
        for field in norm_fields:
            raw_values[field].append(attrs.get(field, 0))
        row = {
            'start': s if start_layer else None, 'dest': d, 'duration': duration, 'distance': distance, 'attrs': attrs,
            's_proj': s_proj, 'd_proj': d_pt, 's_wgs': s_wgs_tuple, 'd_wgs': d_wgs_tuple,
            'dest_id': d_id
        }
        all_results.append(row)
        # 日志输出和进度条刷新，确保实时
        dest_id_val = d_id
        dlg.append_log(f"起点→终点[{dest_id_val}] 路径用时: {duration:.1f}s, 距离: {distance:.1f}m")
        if hasattr(dlg, 'progressBar'):
            dlg.progressBar.setValue(idx + 1)
            percent = (idx + 1) / total_count * 100
            dlg.progressBar.setFormat(f"{idx + 1}/{total_count} ({percent:.1f}%) 终点ID: {dest_id_val}")
        QtWidgets.QApplication.processEvents()
        time.sleep(0.5)
    # 计算minmax
    for field in norm_fields:
        values = raw_values[field]
        minmax[field] = (min(values), max(values)) if values else (0, 0)
    # 归一化、评分、日志输出
    for idx, r in enumerate(all_results):
        normalized_attrs = {}
        for field in norm_fields:
            v = r['attrs'].get(field, 0)
            min_v, max_v = minmax[field]
            norm_type = field_settings[field]['normalize'] if field in field_settings else '无需归一化'
            if max_v > min_v:
                if norm_type == '1-(value-min)/(max-min)' and field != '可达性':
                    normalized_attrs[field] = 1 - (v - min_v) / (max_v - min_v)
                elif norm_type == '(value-min)/(max-min)' and field != '可达性':
                    normalized_attrs[field] = (v - min_v) / (max_v - min_v)
                elif field == '可达性':
                    normalized_attrs[field] = 1 - (v - min_v) / (max_v - min_v)
                else:
                    normalized_attrs[field] = v
            else:
                normalized_attrs[field] = 0.0
        # 评分
        score = 0.0
        for field in field_settings:
            weight = field_settings[field]['weight']
            score += normalized_attrs.get(field, 0) * weight
        score += normalized_attrs.get('可达性', 0) * accessibility_weight
        r['normalized_attrs'] = normalized_attrs
        r['score'] = score
        # 日志输出（路径用时）
        dest_id_val = r['dest_id']
        dlg.append_log(f"起点→终点[{dest_id_val}] 路径用时: {r['duration']:.1f}s, 距离: {r['distance']:.1f}m, 评分: {score:.3f}")
        QtWidgets.QApplication.processEvents()
        # 选最佳
        if best_result is None or score > best_result['score']:
            best_result = r
    best_results = [best_result] if best_result else []
    # 分析结束后不隐藏进度条

    # 4. 导出OD结果csv（全部为归一化值，增加normalized_accessibility，覆盖写入）
    if export_path:
        try:
            csv_path = export_path if export_path.endswith('.csv') else export_path + '.csv'
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                # 字段头
                start_fields = ['start_id']
                dest_fields = ['dest_id']
                norm_fields2 = list(field_settings.keys())
                writer.writerow(start_fields + dest_fields + norm_fields2 + ['normalized_accessibility', 'duration', 'distance', 'score'])
                for r in all_results:
                    s_id = r['start'].id() if start_layer else 0
                    d_id = r['dest_id']
                    norm_vals = [r['normalized_attrs'].get(f, '') for f in norm_fields2]
                    norm_access = r['normalized_attrs'].get('可达性', '')
                    writer.writerow([s_id, d_id] + norm_vals + [norm_access, r['duration'], r['distance'], r.get('score', '')])
            dlg.append_log(f'已导出所有OD路径csv：{csv_path}')
        except Exception as e:
            dlg.append_log(f'OD结果csv导出出错: {e}')
    # 显示最终最佳路径信息
    if best_results:
        best = best_results[0]
        best_dest_id = best['dest_id']
        best_score = best['score']
        best_duration = best['duration']
        dlg.append_log(f"最终最佳目的地: {best_dest_id}, 综合评分: {best_score:.2f}, 可达性: {best_duration:.1f}s")
    else:
        dlg.append_log("没有找到可达的目的地")
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
            ] + [QgsField(f, 10) for f in field_settings])
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
                    attrs += [r['dest'][f] if f in r['dest'].fields().names() else '' for f in field_settings]
                    feat.setAttributes(attrs)
                    pr.addFeatures([feat])
                except Exception as e:
                    dlg.append_log(f'最佳路径导出出错: {e}')
            vl.updateExtents()
            QgsProject.instance().addMapLayer(vl)
            dlg.append_log('最佳OD路径图层已添加')
            
            # 高亮最佳目的地（重写：先添加终点和起点feature，最后addMapLayer）
            if best_results:
                try:
                    best_dest = best_results[0]['dest']
                    crs_proj = QgsProject.instance().crs()
                    highlight_vl = QgsVectorLayer(f'Point?crs={crs_proj.authid()}', '最佳目的地', 'memory')
                    highlight_pr = highlight_vl.dataProvider()
                    highlight_pr.addAttributes([
                        QgsField('type', 10),
                        QgsField('id', 10),
                        QgsField('score', 6, 'double'),
                        QgsField('duration', 6, 'double')
                    ])
                    highlight_vl.updateFields()
                    # 添加终点feature
                    feat_dest = QgsFeature(highlight_vl.fields())
                    feat_dest.setGeometry(QgsGeometry.fromPointXY(best_dest.geometry().asPoint()))
                    feat_dest.setAttributes(['dest', best_results[0]['dest_id'], best_results[0]['score'], best_results[0]['duration']])
                    highlight_pr.addFeatures([feat_dest])
                    # 添加起点feature
                    start_text = dlg.lineEdit_start.text().strip()
                    start_xy = dlg.get_start_point()  # (lon, lat) WGS84
                    if start_xy and start_text:
                        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
                        to_proj = QgsCoordinateTransform(wgs84, crs_proj, QgsProject.instance())
                        pt_wgs = QgsPointXY(*start_xy)
                        pt_proj = to_proj.transform(pt_wgs)
                        feat_start = QgsFeature(highlight_vl.fields())
                        feat_start.setGeometry(QgsGeometry.fromPointXY(pt_proj))
                        feat_start.setAttributes(['start', start_text, '', ''])
                        highlight_pr.addFeatures([feat_start])
                        dlg.append_log(f"已添加起点高亮: 输入框={start_text}, WGS84={start_xy}, 工程坐标=({pt_proj.x():.4f},{pt_proj.y():.4f})")
                    else:
                        dlg.append_log(f"未能添加起点高亮，start_xy={start_xy}, start_text={start_text}")
                    highlight_vl.updateExtents()
                    # 输出feature数量到日志
                    dlg.append_log(f"高亮图层要素数: {highlight_vl.featureCount()}")
                    # 分类渲染：起点蓝色2pt，终点红色2.5pt
                    categories = []
                    symbol_start = QgsSymbol.defaultSymbol(highlight_vl.geometryType())
                    symbol_start.setColor(QColor(0, 0, 255))
                    symbol_start.setSize(2)
                    categories.append(QgsRendererCategory('start', symbol_start, 'Start'))
                    symbol_dest = QgsSymbol.defaultSymbol(highlight_vl.geometryType())
                    symbol_dest.setColor(QColor(255, 0, 0))
                    symbol_dest.setSize(2.5)
                    categories.append(QgsRendererCategory('dest', symbol_dest, 'Destination'))
                    renderer = QgsCategorizedSymbolRenderer('type', categories)
                    highlight_vl.setRenderer(renderer)
                    highlight_vl.triggerRepaint()
                    QgsProject.instance().addMapLayer(highlight_vl, addToLegend=True)
                    dlg.append_log(f'已高亮最佳目的地: {best_results[0]["dest_id"]}，并包含起点')
                except Exception as e:
                    dlg.append_log(f'最佳目的地高亮出错: {e}')
        except Exception as e:
            dlg.append_log(f'路径图层导出出错: {e}')

def stop_analysis(dlg):
    dlg._stop_requested = True

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