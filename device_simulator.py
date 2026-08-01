import sys
import socket
import json
import threading
import datetime
import struct
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QTextEdit, QLabel, QGroupBox, QFormLayout,
                               QPushButton, QComboBox, QGridLayout, QFileDialog, QMessageBox)
from PySide6.QtCore import Signal, QObject, Slot
from PySide6.QtGui import QColor, QTextCursor

class EmittingStream(QObject):
    text_written = Signal(str, str) 

class DeviceSimulator(QMainWindow):
    # 🌟 1. 新增：声明跨线程刷新 UI 的安全信号
    sig_update_ui = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DeepLUT 硬件生态模拟器 (API v1.0 双向互动版)")
        self.resize(1000, 600)

        self.device_info = {
            "brand": "XX品牌",
            "model": "XX型号",
            "fw_version": "v1.0.0",
            "sn": "123456",
            "ip": self.get_local_ip()
        }
        
        self.state = {
            "pre_1d": {"active_slot": 1, "enabled": False, "has_data": [False, False, False, False, False]},
            "lut_3d": {"active_slot": 1, "enabled": False, "has_data": [False, False, False, False, False]},
            "post_1d": {"active_slot": 1, "enabled": False, "has_data": [False, False, False, False, False]}
        }
        self.interp_mode = "tetrahedral"
        self.state_dirty = False 
        self.flash_memory = {
            "pre_1d": {}, "lut_3d": {}, "post_1d": {}
        }
        self.sim_controls = {} 
        
        # 🌟 2. 绑定：收到信号就执行安全的主线程 UI 刷新
        self.sig_update_ui.connect(self.update_ui_state) 
        
        self.setup_ui()
        self.start_servers()

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception: return "127.0.0.1"

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # 左侧：通信日志
        log_group = QGroupBox("TCP/UDP 实时通信日志")
        log_layout = QVBoxLayout(log_group)
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: Consolas;")
        log_layout.addWidget(self.log_console)
        main_layout.addWidget(log_group, stretch=5)

        # 右侧：双向互动操控面板
        status_group = QGroupBox("虚拟硬件双向操控面板 (修改将同步至软件)")
        status_layout = QVBoxLayout(status_group)
        
        top_form = QFormLayout()
        self.lbl_ip = QLabel(f"{self.device_info['ip']}:6666")
        self.lbl_ip.setStyleSheet("color: #007acc; font-weight: bold;")
        
        self.combo_sim_interp = QComboBox()
        self.combo_sim_interp.addItems(["tetrahedral", "trilinear"])
        self.combo_sim_interp.currentTextChanged.connect(self.sim_interp_changed)
        
        top_form.addRow("监听地址:", self.lbl_ip)
        top_form.addRow("3D 插值模式:", self.combo_sim_interp)
        status_layout.addLayout(top_form)

        # 构建三个管线的面板
        status_layout.addWidget(self._build_pipeline_grp("pre_1d", "Pre-1D 物理层"))
        status_layout.addWidget(self._build_pipeline_grp("lut_3d", "3D LUT 系统层"))
        status_layout.addWidget(self._build_pipeline_grp("post_1d", "Post-1D 物理层"))
        status_layout.addStretch()
        
        main_layout.addWidget(status_group, stretch=4)

        self.emitter = EmittingStream()
        self.emitter.text_written.connect(self.append_log)
        self.update_ui_state()

    def _build_pipeline_grp(self, lut_key, title):
        grp = QGroupBox(title)
        lay = QGridLayout(grp)
        
        combo = QComboBox()
        combo.addItems(["1", "2", "3", "4", "5"])
        lbl_status = QLabel("状态: ---")
        
        btn_upload = QPushButton("上传本地")
        btn_export = QPushButton("导出存盘")
        btn_active = QPushButton("激活此槽")
        btn_disable = QPushButton("关(Bypass)")
        btn_delete = QPushButton("删除此槽")

        lay.addWidget(QLabel("目标槽位:"), 0, 0)
        lay.addWidget(combo, 0, 1)
        lay.addWidget(lbl_status, 0, 2, 1, 2)
        
        lay.addWidget(btn_upload, 1, 0, 1, 2)
        lay.addWidget(btn_export, 1, 2, 1, 2)
        
        lay.addWidget(btn_active, 2, 0)
        lay.addWidget(btn_disable, 2, 1, 1, 2)
        lay.addWidget(btn_delete, 2, 3)
        
        # 绑定事件
        btn_upload.clicked.connect(lambda _, k=lut_key: self.sim_upload(k))
        btn_export.clicked.connect(lambda _, k=lut_key: self.sim_export(k))
        btn_active.clicked.connect(lambda _, k=lut_key: self.sim_active(k))
        btn_disable.clicked.connect(lambda _, k=lut_key: self.sim_disable(k))
        btn_delete.clicked.connect(lambda _, k=lut_key: self.sim_delete(k))

        self.sim_controls[lut_key] = {
            "combo": combo, "lbl_status": lbl_status
        }
        return grp

    # ==================== 模拟器 UI 按钮触发动作 ====================
    def sim_interp_changed(self, text):
        self.interp_mode = text
        self.mark_state_changed(f"本机插值模式已更改为: {text}")

    def sim_upload(self, lut_key):
        slot = int(self.sim_controls[lut_key]["combo"].currentText())
        path, _ = QFileDialog.getOpenFileName(self, "选择本机 Cube 文件模拟下发", "", "Cube Files (*.cube)")
        if not path: return
        try:
            with open(path, 'r', encoding='utf-8') as f: text = f.read()
            self.flash_memory[lut_key][slot] = {
                "payload_format": "cube", "payload_data": text.encode('utf-8'),
                "grid_size": 33 if "3d" in lut_key else 4096,
                "domain_min": [0,0,0], "domain_max": [1,1,1]
            }
            self.state[lut_key]["has_data"][slot - 1] = True
            self.mark_state_changed(f"本机已将外部文件载入 {lut_key} 槽位 {slot}")
        except Exception as e:
            QMessageBox.critical(self, "读取失败", str(e))

    def sim_export(self, lut_key):
        slot = int(self.sim_controls[lut_key]["combo"].currentText())
        data = self.flash_memory[lut_key].get(slot)
        if not data:
            QMessageBox.warning(self, "槽位空", f"该槽位没有任何数据，无法导出！")
            return
            
        path, _ = QFileDialog.getSaveFileName(self, "导出内存数据", f"HardwareDump_{lut_key}_Slot{slot}.cube", "Cube Files (*.cube)")
        if not path: return
        
        try:
            with open(path, "w", encoding="utf-8") as f:
                # 🌟 统一加上标志性 Head
                f.write("# Created by DeepLUT Calibration System\n")
                if data["payload_format"] == "binary":
                    f.write(f"LUT_{'3D' if '3d' in lut_key else '1D'}_SIZE {data['grid_size']}\n")
                    d_min, d_max = data["domain_min"], data["domain_max"]
                    f.write(f"DOMAIN_MIN {d_min[0]:.6f} {d_min[1]:.6f} {d_min[2]:.6f}\n")
                    f.write(f"DOMAIN_MAX {d_max[0]:.6f} {d_max[1]:.6f} {d_max[2]:.6f}\n\n")
                    floats = [v[0] for v in struct.iter_unpack('<f', data["payload_data"])]
                    for i in range(0, len(floats), 3):
                        f.write(f"{floats[i]:.6f} {floats[i+1]:.6f} {floats[i+2]:.6f}\n")
                else:
                    # 如果 DeepLUT 下发时没加头，为了防呆，这里不再重复加第二遍 Created by
                    text_content = data["payload_data"].decode('utf-8')
                    if "# Created by DeepLUT" not in text_content:
                        f.write(text_content)
                    else:
                        f.write(text_content.replace("# Created by DeepLUT Calibration System\n", "")) 
            self.log(f"💾 数据导出成功: {path}", is_send=True)
            QMessageBox.information(self, "成功", "已成功从硬件内存 Dump 数据为 Cube 文件！")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def sim_active(self, lut_key):
        slot = int(self.sim_controls[lut_key]["combo"].currentText())
        if not self.state[lut_key]["has_data"][slot - 1]:
            QMessageBox.warning(self, "拦截", "该槽位为空，不允许激活！")
            return
        self.state[lut_key]["active_slot"] = slot
        self.state[lut_key]["enabled"] = True
        self.mark_state_changed(f"本机强行激活了 {lut_key} 的槽位 {slot}")

    def sim_disable(self, lut_key):
        self.state[lut_key]["enabled"] = False
        self.mark_state_changed(f"本机强行旁路了管线 {lut_key}")

    def sim_delete(self, lut_key):
        slot = int(self.sim_controls[lut_key]["combo"].currentText())
        if self.state[lut_key]["active_slot"] == slot:
            self.state[lut_key]["enabled"] = False
        self.state[lut_key]["has_data"][slot - 1] = False
        if slot in self.flash_memory[lut_key]:
            del self.flash_memory[lut_key][slot]
        self.mark_state_changed(f"本机强行删除了 {lut_key} 的槽位 {slot}")

    def mark_state_changed(self, log_msg=""):
        self.state_dirty = True
        if log_msg: self.log(f"🛠️ {log_msg}", is_send=True)
        self.update_ui_state()

    def update_ui_state(self):
        self.combo_sim_interp.blockSignals(True)
        self.combo_sim_interp.setCurrentText(self.interp_mode)
        self.combo_sim_interp.blockSignals(False)

        for key, st in self.state.items():
            ctrl = self.sim_controls[key]
            active = st["active_slot"]
            status_text = f"工作槽: {active} | "
            if st["enabled"]: status_text += "<span style='color:green; font-weight:bold;'>[开启]</span>"
            else: status_text += "<span style='color:red; font-weight:bold;'>[旁路 Bypass]</span>"
            ctrl["lbl_status"].setText(status_text)

    # ==================== 网络日志与服务 ====================
    @Slot(str, str)
    def append_log(self, text, color):
        self.log_console.moveCursor(QTextCursor.End)
        self.log_console.insertHtml(f"<span style='color:{color};'>{text}</span><br>")
        self.log_console.moveCursor(QTextCursor.End)

    def log(self, text, is_error=False, is_recv=False, is_send=False):
        timestamp = datetime.datetime.now().strftime("[%H:%M:%S]")
        color = "#d4d4d4"
        if is_error: color = "#f44336"
        elif is_recv: color = "#4caf50"
        elif is_send: color = "#2196f3"
        self.emitter.text_written.emit(f"{timestamp} {text}", color)

    def start_servers(self):
        threading.Thread(target=self.udp_server_loop, daemon=True).start()
        threading.Thread(target=self.tcp_server_loop, daemon=True).start()
        self.log("模拟器核心引擎(双向互动版)已启动，正在监听 6666 端口...")

    def udp_server_loop(self):
        try:
            udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp_sock.bind(("0.0.0.0", 6666)) 
            self.log("✅ UDP 嗅探雷达已就绪", is_recv=True)
        except Exception: return

        while True:
            try:
                data, addr = udp_sock.recvfrom(1024)
                if data.decode('utf-8').strip() == "WHO_SUPPORT_DEEPLUT":
                    udp_sock.sendto(json.dumps(self.device_info).encode('utf-8'), addr)
            except Exception: pass

    def tcp_server_loop(self):
        try:
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            tcp_sock.bind(("0.0.0.0", 6666))
            tcp_sock.listen(5)
            self.log("✅ TCP 指令引擎已就绪", is_recv=True)
        except Exception: return

        while True:
            conn, addr = tcp_sock.accept()
            self.log(f"🔗 客户端接入: {addr}")
            threading.Thread(target=self.handle_tcp_client, args=(conn, addr), daemon=True).start()

    def handle_tcp_client(self, conn, addr):
        try:
            while True:
                buffer = bytearray()
                while True:
                    char = conn.recv(1)
                    if not char: return
                    if char == b'\n': break
                    buffer.extend(char)
                if not buffer: continue

                req_str = buffer.decode('utf-8')
                try:
                    req = json.loads(req_str)
                    is_hb = req.get("is_heartbeat", False)
                    if not is_hb: self.log(f"⬅ 收到 JSON: {req_str}", is_recv=True)
                    self.process_command(req.get("cmd"), req, conn, is_hb)
                except Exception as e:
                    try: conn.sendall((json.dumps({"status": "error", "msg": str(e)}) + "\n").encode('utf-8'))
                    except: pass
                    if not is_hb: self.log(f"❌ 解析报错: {str(e)}", is_error=True)
        except Exception: pass
        finally:
            conn.close()
            self.log(f"🔗 客户端断开: {addr}")

    def process_command(self, cmd, req, conn, is_hb=False):
        res = {"status": "ok"}
        raw_lut_type = req.get("lut_type", "").upper()
        lut_map = {"PRE_1D": "pre_1d", "3D": "lut_3d", "POST_1D": "post_1d", "ALL": "all"}
        lut_type = lut_map.get(raw_lut_type, raw_lut_type.lower())

        if cmd == "PING":
            # 🌟 核心引擎：在心跳响应中附加状态脏标记，如果脏了就回传 True，并复位。
            res["state_changed"] = self.state_dirty
            self.state_dirty = False

        elif cmd == "GET_INFO":
            res["data"] = {
                "brand": self.device_info["brand"], "model": self.device_info["model"],
                "sn": self.device_info["sn"], "fw_version": self.device_info["fw_version"],
                "capabilities": {
                    "pre_1d": {"supported": True, "max_size": 4096, "slots": 5, "upload_format": "binary"},
                    "lut_3d": {"supported": True, "max_size": 33, "slots": 5, "support_domain": True, "upload_format": "cube"},
                    "post_1d": {"supported": True, "max_size": 4096, "slots": 5, "upload_format": "binary"}
                },
                "interp_modes": ["trilinear", "tetrahedral"],
                "current_state": {"interp_mode": self.interp_mode, **self.state}
            }

        elif cmd == "SET_ACTIVE_SLOT":
            self.state[lut_type]["active_slot"] = int(req["slot_index"])
            self.state_dirty = True
            self.log(f"⚙️ 切换 {raw_lut_type} 槽位至 {req['slot_index']}")

        elif cmd == "SET_ENABLE":
            st = bool(req["state"])
            if lut_type == "all":
                for k in ["pre_1d", "lut_3d", "post_1d"]: self.state[k]["enabled"] = st
            else: self.state[lut_type]["enabled"] = st
            self.state_dirty = True
            self.log(f"⚙️ 设置 {raw_lut_type} 状态: {'开启' if st else '旁路'}")

        elif cmd == "DELETE_LUT":
            slot_idx = int(req['slot_index'])
            if self.state[lut_type]["active_slot"] == slot_idx: self.state[lut_type]["enabled"] = False
            self.state[lut_type]["has_data"][slot_idx - 1] = False
            if slot_idx in self.flash_memory[lut_type]: del self.flash_memory[lut_type][slot_idx]
            self.state_dirty = True
            self.log(f"🗑️ 已清空 {raw_lut_type} 槽位 {slot_idx}")

        elif cmd == "SET_INTERP":
            self.interp_mode = req["mode"]
            self.state_dirty = True
            self.log(f"⚙️ 切换插值: {self.interp_mode}")

        elif cmd == "UPLOAD_LUT":
            bytes_len, fmt = int(req["payload_bytes"]), req.get("payload_format", "cube")
            grid, d_min, d_max = int(req.get("grid_size", 33)), req.get("domain_min"), req.get("domain_max")
            slot_num = int(req['slot_index'])
            
            self.log(f"📦 接收流: {bytes_len} bytes, 格式: {fmt}", is_recv=True)
            received, payload_data = 0, bytearray()
            while received < bytes_len:
                chunk = conn.recv(min(4096, bytes_len - received))
                if not chunk: raise ConnectionError("中断")
                payload_data.extend(chunk)
                received += len(chunk)

            # 存入闪存记忆体，不再强制弹出保存文件
            self.flash_memory[lut_type][slot_num] = {
                "payload_format": fmt, "payload_data": payload_data,
                "grid_size": grid, "domain_min": d_min, "domain_max": d_max
            }
            self.state[lut_type]["has_data"][slot_num - 1] = True
            self.state_dirty = True
            self.log(f"🔥 数据已存入虚拟闪存，您可使用右侧面板导出 {raw_lut_type} 槽位 {slot_num}")

        conn.sendall((json.dumps(res) + "\n").encode('utf-8'))
        if not is_hb:
            self.log(f"➔ 响应: {json.dumps(res)}", is_send=True)
            
        # 🌟 3. 修复：不再用危险的 postEvent，而是通过信号安全通知主线程刷新 UI
        self.sig_update_ui.emit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = DeviceSimulator()
    win.show()
    sys.exit(app.exec())