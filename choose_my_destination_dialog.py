import os
from qgis.PyQt import uic, QtWidgets, QtCore
from qgis.PyQt.QtWidgets import QFileDialog
from qgis.core import QgsProject, QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsPointXY
from qgis.gui import QgsMapToolEmitPoint
from qgis.utils import iface
from qgis.PyQt.QtCore import QVariant

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'choose_my_destination_dialog_base.ui'))

class ChooseMyDestinationDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.btn_pick_point.clicked.connect(self.pick_point)
        self.btn_browse_export_path.clicked.connect(self.browse_export_path)
        self.comboBox_layer.currentIndexChanged.connect(self.on_layer_changed)
        self.listWidget_field_select.itemSelectionChanged.connect(self.populate_fields)
        self.btn_start_analysis.clicked.connect(self.run_main_logic)
        self.btn_stop_analysis.clicked.connect(self.stop_analysis)
        self.populate_layers()
        self.populate_modes()
        self.on_layer_changed()
        self.selected_point = None
        self.canvas = iface.mapCanvas()
        self.project_crs = self.canvas.mapSettings().destinationCrs()
        self.wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        self.transformer = QgsCoordinateTransform(self.project_crs, self.wgs84, QgsProject.instance())
        self.lineEdit_start.setPlaceholderText('支持工程坐标或WGS84经纬度，格式：x,y')
        self._old_map_tool = None
        self._pick_tool = None
        # 进度条初始化
        if hasattr(self, 'progressBar'):
            self.progressBar.hide()
        self.progressBar.setVisible(True)  # 强制显示进度条

    def populate_layers(self):
        self.comboBox_layer.clear()
        layers = [lyr for lyr in QgsProject.instance().mapLayers().values() if lyr.type() == 0 and lyr.geometryType() in (0, 4)]
        for lyr in layers:
            self.comboBox_layer.addItem(lyr.name())

    def on_layer_changed(self):
        self.populate_field_select()
        self.populate_dest_id_fields()
        self.populate_fields()

    def populate_field_select(self):
        self.listWidget_field_select.clear()
        layer_name = self.comboBox_layer.currentText()
        lyr = None
        for l in QgsProject.instance().mapLayers().values():
            if l.name() == layer_name:
                lyr = l
                break
        if not lyr:
            return
        for f in lyr.fields():
            # 只显示数值型字段
            if f.type() in (QVariant.Int, QVariant.Double, QVariant.LongLong, QVariant.UInt, QVariant.ULongLong):
                item = QtWidgets.QListWidgetItem(f.name())
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                self.listWidget_field_select.addItem(item)

    def get_selected_fields(self):
        return [item.text() for item in self.listWidget_field_select.selectedItems()]

    def populate_fields(self):
        self.tableWidget_fields.clear()
        selected_fields = self.get_selected_fields()
        self.tableWidget_fields.setColumnCount(3)
        self.tableWidget_fields.setHorizontalHeaderLabels(['字段名', '权重', '归一化方式'])
        self.tableWidget_fields.setRowCount(len(selected_fields))
        for i, fname in enumerate(selected_fields):
            item = QtWidgets.QTableWidgetItem(fname)
            item.setFlags(item.flags() ^ QtCore.Qt.ItemIsEditable)
            self.tableWidget_fields.setItem(i, 0, item)
            w_edit = QtWidgets.QLineEdit("1.0")
            self.tableWidget_fields.setCellWidget(i, 1, w_edit)
            norm_combo = QtWidgets.QComboBox()
            norm_combo.addItems(["无需归一化", "1-(value-min)/(max-min)", "(value-min)/(max-min)"])
            self.tableWidget_fields.setCellWidget(i, 2, norm_combo)
        # 三列均匀分配
        header = self.tableWidget_fields.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.tableWidget_fields.setMinimumWidth(400)
        self.tableWidget_fields.setMinimumHeight(80)

    def populate_modes(self):
        self.comboBox_mode.clear()
        self.comboBox_mode.addItems(['驾车', '步行', '骑行', '公交'])

    def populate_dest_id_fields(self):
        self.comboBox_dest_id_field.clear()
        layer_name = self.comboBox_layer.currentText()
        lyr = None
        for l in QgsProject.instance().mapLayers().values():
            if l.name() == layer_name:
                lyr = l
                break
        if not lyr:
            return
        fields = [f.name() for f in lyr.fields()]
        for fname in fields:
            self.comboBox_dest_id_field.addItem(fname)

    def get_dest_id_field(self):
        return self.comboBox_dest_id_field.currentText()

    def get_field_settings(self):
        """返回每个字段的权重和归一化方式"""
        settings = {}
        for i in range(self.tableWidget_fields.rowCount()):
            field = self.tableWidget_fields.item(i, 0).text()
            w_edit = self.tableWidget_fields.cellWidget(i, 1)
            norm_combo = self.tableWidget_fields.cellWidget(i, 2)
            try:
                weight = float(w_edit.text())
            except:
                weight = 1.0
            norm_type = norm_combo.currentText()
            settings[field] = {'weight': weight, 'normalize': norm_type}
        return settings

    def get_accessibility_weight(self):
        try:
            return float(self.lineEdit_accessibility_weight.text())
        except:
            return 1.0

    def get_mode(self):
        text = self.comboBox_mode.currentText()
        if text == '驾车':
            return 'driving'
        elif text == '步行':
            return 'walking'
        elif text == '骑行':
            return 'bicycling'
        elif text == '公交':
            return 'transit'
        else:
            return 'driving'

    def get_export_path(self):
        return self.lineEdit_export_path.text().strip()

    def get_key(self):
        return self.lineEdit_key.text().strip()

    def append_log(self, msg):
        self.textEdit_log.append(msg)

    def run_main_logic(self):
        try:
            self._stop_requested = False
            from .choose_my_destination import run_choose_my_destination
            run_choose_my_destination(self)
        except Exception as e:
            self.append_log(f"运行出错: {e}")

    def stop_analysis(self):
        self._stop_requested = True
        self.append_log("已请求停止分析，当前任务完成后将中断。")

    def browse_export_path(self):
        filename, _ = QFileDialog.getSaveFileName(self, "选择导出CSV文件", "", "CSV Files (*.csv)")
        if filename:
            self.lineEdit_export_path.setText(filename)

    def pick_point(self):
        self.textEdit_log.append("请在地图上点击选择起点...")
        self._old_map_tool = self.canvas.mapTool()
        from qgis.gui import QgsMapToolEmitPoint
        self._pick_tool = QgsMapToolEmitPoint(self.canvas)
        self._pick_tool.canvasClicked.connect(self.on_map_click)
        self.canvas.setMapTool(self._pick_tool)

    def on_map_click(self, point, button):
        # 工程坐标转WGS84
        wgs_pt = self.transformer.transform(point)
        self.selected_point = (wgs_pt.x(), wgs_pt.y())
        self.lineEdit_start.setText(f"{wgs_pt.x():.6f},{wgs_pt.y():.6f}")
        self.textEdit_log.append(f"已选起点: {wgs_pt.x():.6f},{wgs_pt.y():.6f}")
        # 恢复原有工具
        if self._old_map_tool:
            self.canvas.setMapTool(self._old_map_tool)
        if self._pick_tool:
            self._pick_tool.canvasClicked.disconnect(self.on_map_click)
        self._pick_tool = None
        self._old_map_tool = None
        # 选点后自动弹出插件窗口
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def get_layer(self):
        name = self.comboBox_layer.currentText()
        for l in QgsProject.instance().mapLayers().values():
            if l.name() == name:
                return l
        return None 

    def get_start_point(self):
        text = self.lineEdit_start.text().strip()
        if ',' in text:
            x, y = map(float, text.split(','))
            # 判断是否为工程坐标（大数值），自动转WGS84
            if abs(x) > 180 or abs(y) > 90:
                pt = QgsPointXY(x, y)
                wgs_pt = self.transformer.transform(pt)
                return wgs_pt.x(), wgs_pt.y()
            else:
                return x, y
        return None 