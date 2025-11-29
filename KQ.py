import sys
import os
import json
import subprocess
import threading
import time
import webbrowser
from datetime import date
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                               QPushButton, QLabel, QLineEdit, QMessageBox, 
                               QGroupBox, QCheckBox, QFrame, QDialog, QComboBox, 
                               QDateEdit, QTextEdit)
from PySide6.QtGui import QTextCursor, QFont
from PySide6.QtCore import Qt, Signal, QThread, Slot, QDate

# ==========================================
# 0. 基础配置与路径
# ==========================================
def get_app_path():
    """获取程序运行时的绝对路径 (兼容 EXE 和 Python 脚本)"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

APP_ROOT = get_app_path()
USER_DATA_DIR = os.path.join(APP_ROOT, "user_data")
STRATEGY_DIR = os.path.join(USER_DATA_DIR, "strategies")
CONFIG_PATH = os.path.join(USER_DATA_DIR, "config.json")

# --- 样式表 ---
STYLE_LIGHT_ON = "background-color: #2ecc71; border-radius: 10px; border: 2px solid #27ae60;" # 亮绿
STYLE_LIGHT_OFF = "background-color: #e74c3c; border-radius: 10px; border: 2px solid #c0392b;" # 暗红
STYLE_BTN_GREEN = "background-color: #dff0d8; color: #3c763d; font-weight: bold;"
STYLE_BTN_BLUE = "background-color: #d9edf7; color: #31708f; font-weight: bold;"
STYLE_BTN_ORANGE = "background-color: #f39c12; color: white; font-weight: bold;"

# ==========================================
# 1. 后台任务线程 (执行回测/下载)
# ==========================================
class DockerWorker(QThread):
    log_signal = Signal(str)
    finish_signal = Signal()

    def __init__(self, cmd):
        super().__init__()
        self.cmd = cmd

    def run(self):
        try:
            self.log_signal.emit(f"🚀 执行命令:\n{self.cmd}\n{'='*40}\n")
            # 使用 Popen 实时捕获输出
            process = subprocess.Popen(
                self.cmd, 
                shell=True, 
                cwd=APP_ROOT, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                creationflags=subprocess.CREATE_NO_WINDOW,
                encoding='utf-8', 
                errors='replace'
            )

            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    self.log_signal.emit(line.strip())
            
            self.log_signal.emit(f"\n{'='*40}\n✅ 任务结束")
        except Exception as e:
            self.log_signal.emit(f"❌ 发生错误: {str(e)}")
        finally:
            self.finish_signal.emit()

# ==========================================
# 2. 实验室弹窗 (回测与数据下载)
# ==========================================
class BacktestWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 实验室: 回测与数据下载")
        self.resize(750, 600)
        self.init_ui()
        self.scan_files()

    def init_ui(self):
        layout = QVBoxLayout()

        # --- 1. 文件选择 ---
        grp_files = QGroupBox("1. 文件选择")
        layout_files = QHBoxLayout()
        layout_files.addWidget(QLabel("策略:"))
        self.combo_strat = QComboBox()
        layout_files.addWidget(self.combo_strat)
        layout_files.addWidget(QLabel(" 配置:"))
        self.combo_conf = QComboBox()
        layout_files.addWidget(self.combo_conf)
        grp_files.setLayout(layout_files)
        layout.addWidget(grp_files)

        # --- 2. 参数设置 ---
        grp_params = QGroupBox("2. 参数设置")
        layout_params = QVBoxLayout()
        
        # 日期选择
        hbox_date = QHBoxLayout()
        hbox_date.addWidget(QLabel("开始日期:"))
        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_start.setDisplayFormat("yyyy-MM-dd")
        self.date_start.setDate(QDate.currentDate().addDays(-30)) # 默认前30天
        hbox_date.addWidget(self.date_start)
        
        hbox_date.addWidget(QLabel("  结束日期:"))
        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDisplayFormat("yyyy-MM-dd")
        self.date_end.setDate(QDate.currentDate())
        hbox_date.addWidget(self.date_end)
        layout_params.addLayout(hbox_date)

        # 币种与合约模式
        hbox_pairs = QHBoxLayout()
        
        self.chk_futures = QCheckBox("🔥 合约模式 (Futures)")
        self.chk_futures.setStyleSheet("color: #e67e22; font-weight: bold;")
        self.chk_futures.setToolTip("勾选后，自动为币种添加 :USDT 后缀")
        hbox_pairs.addWidget(self.chk_futures)

        hbox_pairs.addWidget(QLabel("指定币种:"))
        self.line_pairs = QLineEdit()
        self.line_pairs.setPlaceholderText("例: BTC/USDT (留空则使用 Config 列表)")
        hbox_pairs.addWidget(self.line_pairs)
        layout_params.addLayout(hbox_pairs)
        
        # 下载周期
        hbox_tf = QHBoxLayout()
        hbox_tf.addWidget(QLabel("下载周期:"))
        self.line_tf = QLineEdit("1m 5m 15m 1h 4h 1d")
        self.line_tf.setToolTip("可手动删除不需要的周期，加快下载速度")
        hbox_tf.addWidget(self.line_tf)
        layout_params.addLayout(hbox_tf)

        grp_params.setLayout(layout_params)
        layout.addWidget(grp_params)

        # --- 3. 操作按钮 ---
        hbox_actions = QHBoxLayout()
        self.btn_download = QPushButton("📥 下载数据 (Download)")
        self.btn_download.setStyleSheet(STYLE_BTN_BLUE)
        self.btn_download.clicked.connect(self.run_download)
        
        self.btn_backtest = QPushButton("▶ 开始回测 (Backtest)")
        self.btn_backtest.setStyleSheet(STYLE_BTN_GREEN)
        self.btn_backtest.clicked.connect(self.run_backtest)

        self.btn_copy = QPushButton("📋 复制日志")
        self.btn_copy.setStyleSheet(STYLE_BTN_ORANGE)
        self.btn_copy.clicked.connect(self.copy_log)
        
        hbox_actions.addWidget(self.btn_download)
        hbox_actions.addWidget(self.btn_backtest)
        hbox_actions.addWidget(self.btn_copy)
        
        layout.addLayout(hbox_actions) # 修正了之前的 addWidget 错误

        # --- 4. 日志输出 ---
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: Consolas; font-size: 10pt;")
        layout.addWidget(self.txt_log)

        self.setLayout(layout)

    def scan_files(self):
        """扫描策略和配置文件"""
        self.combo_strat.clear()
        if os.path.exists(STRATEGY_DIR):
            strategies = [f[:-3] for f in os.listdir(STRATEGY_DIR) if f.endswith(".py") and f != "__init__.py"]
            if strategies: self.combo_strat.addItems(strategies)
            else: self.combo_strat.addItem("未找到策略")
        
        self.combo_conf.clear()
        if os.path.exists(USER_DATA_DIR):
            configs = [f for f in os.listdir(USER_DATA_DIR) if f.endswith(".json")]
            self.combo_conf.addItems(configs)
            # 优先选中 back.json
            index = self.combo_conf.findText("back.json")
            if index >= 0: self.combo_conf.setCurrentIndex(index)

    def process_pairs(self, raw_pairs):
        """智能处理币种格式 (合约/现货)"""
        if not raw_pairs: return ""
        pairs_list = raw_pairs.split()
        final_list = []
        is_futures = self.chk_futures.isChecked()
        
        for p in pairs_list:
            # 1. 补全计价货币 (如 BTC -> BTC/USDT)
            if "/" not in p: p = f"{p}/USDT"
            # 2. 补全合约后缀
            if is_futures and ":" not in p: p = f"{p}:USDT"
            final_list.append(p)
            
        return " ".join(final_list)

    def get_common_flags(self):
        d_start = self.date_start.date().toString("yyyyMMdd")
        d_end = self.date_end.date().toString("yyyyMMdd")
        timerange = f"{d_start}-{d_end}"
        config_file = self.combo_conf.currentText()
        
        raw_pairs = self.line_pairs.text().strip()
        pairs = self.process_pairs(raw_pairs)
        
        flags = f"--config user_data/{config_file} --timerange {timerange}"
        if pairs:
            flags += f" --pairs {pairs}"
            self.txt_log.append(f"🔍 智能识别币种: {pairs}")
            
        return flags

    def run_download(self):
        self.txt_log.clear()
        flags = self.get_common_flags()
        tfs = self.line_tf.text().strip()
        cmd = f"docker compose run --rm freqtrade download-data {flags} -t {tfs}"
        self.start_worker(cmd)

    def run_backtest(self):
        self.txt_log.clear()
        flags = self.get_common_flags()
        strategy = self.combo_strat.currentText()
        cmd = f"docker compose run --rm freqtrade backtesting {flags} --strategy {strategy}"
        self.start_worker(cmd)

    def start_worker(self, cmd):
        self.btn_download.setEnabled(False)
        self.btn_backtest.setEnabled(False)
        self.worker = DockerWorker(cmd)
        self.worker.log_signal.connect(self.append_log)
        self.worker.finish_signal.connect(self.on_finished)
        self.worker.start()

    def append_log(self, text):
        self.txt_log.append(text)
        self.txt_log.moveCursor(QTextCursor.End)

    def on_finished(self):
        self.btn_download.setEnabled(True)
        self.btn_backtest.setEnabled(True)

    def copy_log(self):
        self.txt_log.selectAll()
        self.txt_log.copy()
        self.txt_log.moveCursor(QTextCursor.End) # 取消全选高亮，体验更好

# ==========================================
# 3. 主程序 (FreqtradeManager)
# ==========================================
class DockerMonitor(QThread):
    status_signal = Signal(bool)
    def run(self):
        while True:
            try:
                # 检查是否有 freqtrade 容器在运行
                result = subprocess.run(
                    "docker compose ps --services --filter \"status=running\"", 
                    shell=True, cwd=APP_ROOT, capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                self.status_signal.emit(bool(result.stdout.strip()))
            except: self.status_signal.emit(False)
            time.sleep(3) # 每3秒刷新一次

class FreqtradeManager(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Freqtrade 懒人管家 (V4.0 终极版)")
        self.setGeometry(300, 300, 400, 520) # 高度减小，更紧凑
        
        self.check_env()
        self.init_ui()
        self.load_config()
        
        # 启动状态监控
        self.monitor = DockerMonitor()
        self.monitor.status_signal.connect(self.update_power_light)
        self.monitor.start()

    def check_env(self):
        if not os.path.exists(CONFIG_PATH):
            QMessageBox.critical(self, "错误", f"找不到配置文件：\n{CONFIG_PATH}")
            sys.exit(1)

    def init_ui(self):
        layout = QVBoxLayout()
        btn_font = QFont("Microsoft YaHei", 9, QFont.Bold)
        
        # --- 1. 状态指示 ---
        grp_status = QGroupBox("📊 运行状态")
        lay_status = QHBoxLayout()
        lay_status.addStretch()
        
        self.light_p = QLabel()
        self.light_p.setFixedSize(20, 20)
        self.light_p.setStyleSheet(STYLE_LIGHT_OFF)
        lay_status.addWidget(self.light_p)
        lay_status.addWidget(QLabel("Docker 电源状态"))
        
        lay_status.addStretch()
        grp_status.setLayout(lay_status)
        layout.addWidget(grp_status)

        # --- 2. 电源与日志控制 (核心区) ---
        grp_ctrl = QGroupBox("🔌 电源与日志")
        lay_ctrl = QVBoxLayout()
        
        # 启动/停止
        hbox_btn = QHBoxLayout()
        self.btn_start = QPushButton("▶ 启动电源")
        self.btn_start.setFont(btn_font)
        self.btn_start.clicked.connect(lambda: self.run_bg("docker compose up -d", "启动指令已发送"))
        
        self.btn_stop = QPushButton("⏹ 切断电源")
        self.btn_stop.clicked.connect(self.confirm_stop)
        
        hbox_btn.addWidget(self.btn_start)
        hbox_btn.addWidget(self.btn_stop)
        lay_ctrl.addLayout(hbox_btn)

        # 实时日志 (新加回来的功能)
        self.btn_logs = QPushButton("📜 查看实时运行日志 (Live Logs)")
        self.btn_logs.setStyleSheet("background-color: #ecf0f1; border: 1px solid #bdc3c7;")
        self.btn_logs.setToolTip("弹出一个独立窗口查看 Docker 实时输出")
        self.btn_logs.clicked.connect(self.view_logs)
        lay_ctrl.addWidget(self.btn_logs)
        
        # 重启
        self.btn_restart = QPushButton("🔄 重启生效 (Restart)")
        self.btn_restart.clicked.connect(self.confirm_restart)
        lay_ctrl.addWidget(self.btn_restart)
        
        grp_ctrl.setLayout(lay_ctrl)
        layout.addWidget(grp_ctrl)

        # --- 3. 配置与实验室 ---
        grp_cfg = QGroupBox("⚙️ 配置与功能")
        lay_cfg = QVBoxLayout()
        
        # 模拟盘开关
        self.chk_dry = QCheckBox("🛡️ 模拟盘 (Dry Run)")
        self.chk_dry.toggled.connect(self.toggle_dry)
        lay_cfg.addWidget(self.chk_dry)
        
        # 端口设置
        hbox_port = QHBoxLayout()
        hbox_port.addWidget(QLabel("代理端口:"))
        self.line_port = QLineEdit()
        self.btn_save_port = QPushButton("保存")
        self.btn_save_port.clicked.connect(self.save_port)
        hbox_port.addWidget(self.line_port)
        hbox_port.addWidget(self.btn_save_port)
        lay_cfg.addLayout(hbox_port)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        lay_cfg.addWidget(line)

        # 实验室入口
        self.btn_lab = QPushButton("🧪 打开实验室 (回测/下载)")
        self.btn_lab.setStyleSheet("font-weight: bold; padding: 6px;")
        self.btn_lab.clicked.connect(self.open_backtest_window)
        lay_cfg.addWidget(self.btn_lab)

        grp_cfg.setLayout(lay_cfg)
        layout.addWidget(grp_cfg)

        # --- 4. 快捷方式 ---
        grp_link = QGroupBox("🚀 快捷入口")
        lay_link = QHBoxLayout()
        b1 = QPushButton("🌐 FreqUI (网页)")
        b1.clicked.connect(lambda: webbrowser.open("http://127.0.0.1:8080"))
        b2 = QPushButton("📂 打开文件夹")
        b2.clicked.connect(lambda: subprocess.Popen(f'explorer "{APP_ROOT}"'))
        lay_link.addWidget(b1)
        lay_link.addWidget(b2)
        grp_link.setLayout(lay_link)
        layout.addWidget(grp_link)

        self.setLayout(layout)

    # --- 功能函数 ---

    def open_backtest_window(self):
        self.bt_window = BacktestWindow(self)
        self.bt_window.show()

    @Slot(bool)
    def update_power_light(self, on):
        self.light_p.setStyleSheet(STYLE_LIGHT_ON if on else STYLE_LIGHT_OFF)
        self.light_p.setToolTip("运行中" if on else "已停止")

    def view_logs(self):
        """弹出独立的 PowerShell 窗口查看实时日志"""
        # 使用 start powershell 确保弹出新窗口
        cmd = f'start powershell -NoExit -Command "cd \'{APP_ROOT}\'; echo 正在连接日志...; docker compose logs -f"'
        subprocess.Popen(cmd, shell=True, cwd=APP_ROOT)

    def load_config(self):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # 只加载 Dry Run，不再碰 initial_state
            is_dry = data.get("dry_run", True)
            self.chk_dry.blockSignals(True)
            self.chk_dry.setChecked(is_dry)
            self.chk_dry.blockSignals(False)
            
            # 读取端口
            try:
                proxy = data.get("exchange", {}).get("ccxt_config", {}).get("proxies", {}).get("http", "")
                if ":" in proxy: self.line_port.setText(proxy.split(":")[-1].replace("/", ""))
            except: pass
        except: pass

    def toggle_dry(self, chk):
        if not chk:
            reply = QMessageBox.warning(self, "高能预警", 
                                        "🛑 切换到【实盘 (Live)】模式资金将面临风险！\n确定要继续吗？", 
                                        QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                self.chk_dry.setChecked(True)
                return
        self.update_json("dry_run", chk)
        QMessageBox.information(self, "保存", f"已切换为 {'模拟盘' if chk else '实盘'}，请点击【重启生效】。")

    def save_port(self):
        port = self.line_port.text().strip()
        if not port.isdigit(): return
        proxy_str = f"http://host.docker.internal:{port}"
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f: data = json.load(f)
            if "exchange" not in data: data["exchange"] = {}
            if "ccxt_config" not in data["exchange"]: data["exchange"]["ccxt_config"] = {"enableRateLimit": True}
            data["exchange"]["ccxt_config"]["proxies"] = {"http": proxy_str, "https": proxy_str}
            
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
            QMessageBox.information(self, "成功", "端口已保存，请点击【重启生效】。")
        except Exception as e: QMessageBox.critical(self, "错误", str(e))

    def update_json(self, k, v):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f: d=json.load(f)
            d[k]=v
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f: json.dump(d,f,indent=4,ensure_ascii=False)
            return True
        except Exception as e: return False

    def run_bg(self, cmd, msg):
        threading.Thread(target=lambda: subprocess.run(cmd,shell=True,cwd=APP_ROOT,creationflags=subprocess.CREATE_NO_WINDOW)).start()
        if msg: QMessageBox.information(self,"提示",msg)

    def confirm_stop(self):
        if QMessageBox.question(self,"关机","确定彻底关闭机器人电源吗？")==QMessageBox.Yes: 
            self.run_bg("docker compose down","已发送关机指令")

    def confirm_restart(self):
        if QMessageBox.question(self,"重启","确定重启容器吗？")==QMessageBox.Yes:
            # 同样使用弹窗方式重启，方便看有没有报错
            subprocess.Popen(f'start powershell -NoExit -Command "cd \'{APP_ROOT}\'; docker compose restart; echo 重启完成"', shell=True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = FreqtradeManager()
    w.show()
    sys.exit(app.exec())