from PyQt5 import QtGui, QtWidgets
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QMenuBar, QGraphicsOpacityEffect, QMessageBox)
from PyQt5.QtCore import Qt, QTimer, QSize, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QCursor
import socket, json, time, subprocess, os


cameras = []
selectedCamera = None

def resource_path(relative_path):
    try:
        appdata_path = os.environ.get('APPDATA')
    except Exception:
        appdata_path = os.path.abspath(".")  # fallback pentru rulare normala

    return os.path.join(os.path.join(appdata_path, "M5TallyClient"), relative_path)

class DeviceWidget(QLabel):
    device_selected = pyqtSignal(str, str)

    def __init__(self, device_id, ip_address, parent=None):
        super().__init__(parent)
        self.device_id = device_id
        self.ip_address = ip_address
        self.status = 0
        self.active = True
        self.flashing = False
        self.flash_count = 0
        self.max_flashes = 8
        self.setFixedSize(100, 100)
        self.setStyleSheet("border: 3px solid transparent; border-radius: 12px;")
        self.setAlignment(Qt.AlignCenter)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.opacity_effect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)
        self.flash_timer = QTimer(self)
        self.flash_timer.timeout.connect(self.toggle_flash)
        self.regular_pixmap = None
        self.bright_pixmap = None
        self.update_status(0, active=True)
        self.setCursor(QCursor(Qt.ArrowCursor))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.device_selected.emit(self.device_id, self.ip_address)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        if self.pixmap():
            painter.drawPixmap(self.rect(), self.pixmap())
        painter.setPen(Qt.white)
        painter.setFont(QtGui.QFont('Arial', 22, QtGui.QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, str(self.device_id))

    def update_status(self, status, active=True):
        self.status = status
        self.active = active
        status_str = ["idle", "preview", "live"][status] if status in [0, 1, 2] else "idle"
        regular_sprite_path = resource_path(f"Assets/sprites/default/{status_str}.png")
        bright_sprite_path = resource_path(f"Assets/sprites/highlight/{status_str}_pressed.png")
        self.regular_pixmap = QPixmap(regular_sprite_path)
        if self.regular_pixmap.isNull():
            self.regular_pixmap = QPixmap(100, 100)
            self.regular_pixmap.fill(Qt.blue)
        self.bright_pixmap = QPixmap(bright_sprite_path)
        if self.bright_pixmap.isNull():
            self.bright_pixmap = self.regular_pixmap
        self.setPixmap(self.regular_pixmap.scaled(QSize(100, 100), Qt.KeepAspectRatio))
        self.opacity_effect.setOpacity(1.0 if active else 0.3)
        self.stop_flashing()

    def start_flashing(self):
        if not self.flashing and self.active:
            self.flashing = True
            self.flash_count = 0
            self.flash_timer.start(250)
            self.toggle_flash()

    def toggle_flash(self):
        if not self.flashing: return
        self.setPixmap(
            (self.bright_pixmap if self.flash_count % 2 == 0 else self.regular_pixmap).scaled(QSize(100, 100),
                                                                                              Qt.KeepAspectRatio))
        self.flash_count += 1
        if self.flash_count >= self.max_flashes:
            self.stop_flashing()

    def stop_flashing(self):
        if self.flashing:
            self.flashing = False
            self.flash_timer.stop()
            self.setPixmap(self.regular_pixmap.scaled(QSize(100, 100), Qt.KeepAspectRatio))

    def show_context_menu(self, position):
        context_menu = QtWidgets.QMenu(self)
        ip_action = context_menu.addAction(self.ip_address)
        ip_action.setEnabled(False)
        context_menu.addSeparator()
        delete_action = context_menu.addAction("Delete Device")
        action = context_menu.exec_(self.mapToGlobal(position))
        if action == delete_action:
            self.parent().remove_device(self.device_id)


class DeviceContainer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.devices = {}
        self.layout_ = QHBoxLayout(self)
        self.layout_.setAlignment(Qt.AlignCenter)
        self.layout_.setSpacing(30)

    def add_or_update_device(self, device_id, ip_address, status):
        if device_id in self.devices:
            device = self.devices[device_id]
            device.active = True
            device.opacity_effect.setOpacity(1.0)
            if device.status != status:
                device.update_status(status, active=True)
        else:
            device_widget = DeviceWidget(device_id, ip_address, self)
            device_widget.device_selected.connect(self.parent().update_selected_device)
            device_widget.update_status(status, active=True)
            self.devices[device_id] = device_widget
            self.devices[device_id] = device_widget
            self.reorder_devices()

    def mark_device_inactive(self, device_id):
        if device_id in self.devices:
            self.devices[device_id].update_status(self.devices[device_id].status, active=False)

    def trigger_device_flash(self, device_id):
        if device_id in self.devices:
            self.devices[device_id].start_flashing()

    def reorder_devices(self):
        for i in reversed(range(self.layout_.count())):
            self.layout_.itemAt(i).widget().setParent(None)
        for key in sorted(self.devices.keys(), key=lambda x: int(x)):
            self.layout_.addWidget(self.devices[key])

    def remove_device(self, device_id):
        if device_id in self.devices:
            widget = self.devices[device_id]
            self.layout_.removeWidget(widget)
            widget.deleteLater()
            del self.devices[device_id]


class UdpListener(QThread):
    device_signal = pyqtSignal(str, str, int)
    device_discovered = pyqtSignal(str, str)
    device_refreshed = pyqtSignal(str, str, int)
    button_pressed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.device_statuses = {}

    def send_connected_ping(self, ip):
        message = {"connected": True}
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(json.dumps(message).encode('utf-8'), (ip, 12002))
        sock.close()

    def run(self):
        s_discovery = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s_status = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s_button = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s_discovery.bind(('0.0.0.0', 12001))
        s_status.bind(('0.0.0.0', 12002))
        s_button.bind(('0.0.0.0', 12003))
        s_discovery.settimeout(0.1)
        s_status.settimeout(0.1)
        s_button.settimeout(0.1)

        while self.running:
            try:
                data, addr = s_discovery.recvfrom(1024)
                if len(data) == 1:
                    dev_id = str(data[0])
                    self.send_connected_ping(addr[0])
                    if dev_id not in cameras:
                        cameras.append(dev_id)
                        self.device_discovered.emit(dev_id, addr[0])
                    else:
                        self.device_refreshed.emit(dev_id, addr[0], self.device_statuses.get(dev_id, 0))
            except socket.timeout:
                pass
            try:
                data, addr = s_status.recvfrom(1024)
                message = json.loads(data.decode('utf-8'))
                dev_id = str(message['device_id'])
                status = message['status']
                self.device_signal.emit(dev_id, addr[0], status)
                self.device_statuses[dev_id] = status
            except:
                pass
            try:
                data, addr = s_button.recvfrom(1024)
                if len(data) == 1:
                    self.button_pressed.emit(str(data[0]))
            except socket.timeout:
                pass
        s_discovery.close()
        s_status.close()
        s_button.close()

    def stop(self):
        self.running = False
        self.wait()


class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(QtGui.QIcon(resource_path("Assets/icon.ico")))
        self.setWindowTitle("M5 Device Monitor")
        self.setGeometry(100, 100, 800, 600)
        self.setStyleSheet("background-color: #2E3440; color: #D8DEE9; font-family: 'Fira Code'; font-size: 14px;")
        self.devices = {}
        self.initUI()
        self.start_networking()

    def initUI(self):
        global selectedCamera
        layout = QVBoxLayout(self)
        menu_bar = QMenuBar(self)

        menu_bar.setStyleSheet("""
            QMenuBar::item:selected {
                background-color: #4C566A; /* Background color when hovering over a menu item */
                color: #D8DEE9; /* Text color when hovering over a menu item */
            }
        """)

        new_m5_action = QtWidgets.QAction("New M5", self)
        new_m5_action.triggered.connect(self.open_flasher)
        menu_bar.addAction(new_m5_action)

        refresh_action = QtWidgets.QAction("Refresh Devices", self)
        refresh_action.triggered.connect(self.refresh_devices)
        menu_bar.addAction(refresh_action)

        about_action = QtWidgets.QAction("About", self)
        about_action.triggered.connect(self.show_about)
        menu_bar.addAction(about_action)

        layout.setMenuBar(menu_bar)

        self.device_container = DeviceContainer()
        layout.addWidget(self.device_container)

        bottom = QHBoxLayout()
        left = QVBoxLayout()
        self.prompt_label = QLabel("Send Prompt to Device ID: none")
        left.addWidget(self.prompt_label)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Enter message to send")
        self.input.setStyleSheet(
            "background-color: transparent; color: #D8DEE9; padding: 5px; border: 1px solid #D8DEE9; border-radius: 3px;")
        self.input.returnPressed.connect(self.send_prompt)  # Trigger send_prompt on Enter key
        left.addWidget(self.input)
        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet(
            "background-color: transparent; color: #D8DEE9; padding: 5px; border: 1px solid #D8DEE9; border-radius: 3px;")
        self.send_btn.clicked.connect(self.send_prompt)
        left.addWidget(self.send_btn)

        right = QVBoxLayout()
        self.about_label = QLabel("About Device ID: none")
        right.addWidget(self.about_label)
        self.ip_label = QLabel("M5 Device IP: unknown")
        right.addWidget(self.ip_label)
        self.rm_btn = QPushButton("Remove Device")
        self.rm_btn.setStyleSheet(
            "background-color: transparent; color: #D8DEE9; padding: 5px; border: 1px solid #D8DEE9; border-radius: 3px;")
        right.addWidget(self.rm_btn)
        self.rm_btn.clicked.connect(self.remove_selected_device)

        left_w = QWidget()
        left_w.setFixedHeight(140)
        left_w.setLayout(left)
        left_w.setStyleSheet("background-color: #4C566A; border-right: 1px solid black;")
        right_w = QWidget()
        right_w.setFixedHeight(140)
        right_w.setLayout(right)
        right_w.setStyleSheet("background-color: #4C566A;")

        bottom.addWidget(left_w, 2)
        bottom.addWidget(right_w, 1)
        layout.addLayout(bottom)

    def start_networking(self):
        self.udp_listener = UdpListener()
        self.udp_listener.device_signal.connect(self.update_device)
        self.udp_listener.device_discovered.connect(self.add_device)
        self.udp_listener.device_refreshed.connect(self.refresh_device)
        self.udp_listener.button_pressed.connect(self.device_flash)
        self.udp_listener.start()
        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.timeout.connect(self.cleanup_devices)
        self.cleanup_timer.start(10000)

    def add_device(self, dev_id, ip):
        self.devices[dev_id] = time.time()
        self.device_container.add_or_update_device(dev_id, ip, 0)

    def refresh_device(self, dev_id, ip, status):
        self.devices[dev_id] = time.time()
        self.device_container.add_or_update_device(dev_id, ip, status)

    def update_device(self, dev_id, ip, status):
        self.devices[dev_id] = time.time()
        self.device_container.add_or_update_device(dev_id, ip, status)

    def device_flash(self, dev_id):
        self.device_container.trigger_device_flash(dev_id)

    def cleanup_devices(self):
        now = time.time()
        for dev_id, last_seen in list(self.devices.items()):
            if now - last_seen > 10:
                self.device_container.mark_device_inactive(dev_id)

    def refresh_devices(self):
        for device_id in list(self.devices.keys()):
            self.device_container.mark_device_inactive(device_id)

    def show_about(self):
        QMessageBox.about(self, "About M5 Device Monitor",
                          "This app monitors M5 devices using UDP.\n\nEduard Balasea & Rares-Bogdan Cazan, © 2025")

    def send_prompt(self):
        global selectedCamera
        if not selectedCamera:
            QMessageBox.warning(self, "No Device Selected", "Please click on a device first.")
            return
        ip = None
        for device_id, widget in self.device_container.devices.items():
            if device_id == selectedCamera:
                ip = widget.ip_address
                break
        if not ip:
            QMessageBox.warning(self, "IP Not Found", "Could not find IP for selected device.")
            return
        msg = self.input.text()
        if not msg:
            return
        json_message = {"message": f"{msg}"}
        json_data = json.dumps(json_message)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(json_data.encode('utf-8'), (ip, 12002))
        finally:
            sock.close()
        self.about_label.setText(f"About Device ID: {selectedCamera}")
        self.input.clear()
        self.ip_label.setText(f"M5 Device IP: {ip}")

    def update_selected_device(self, dev_id, ip):
        global selectedCamera
        selectedCamera = dev_id
        self.about_label.setText(f"About Device ID: {dev_id}")
        self.ip_label.setText(f"M5 Device IP: {ip}")
        self.prompt_label.setText(f"Send Prompt to Device ID: {dev_id}")

    def open_flasher(self):
        try:
            flasher_path = resource_path("flasher.exe")            
            if os.path.exists(flasher_path):
                flags = subprocess.DETACHED_PROCESS if os.name == 'nt' else 0
                subprocess.Popen(flasher_path, creationflags=flags)
                return

            QMessageBox.warning(self, "Error", "Flasher executable not found.")

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not launch flasher: {e}")


    def remove_selected_device(self):
        global selectedCamera
        if selectedCamera and selectedCamera in self.device_container.devices:
            self.device_container.remove_device(selectedCamera)
            self.about_label.setText("About Device ID: none")
            self.ip_label.setText("M5 Device IP: unknown")
            self.input.clear()

    def closeEvent(self, event):
        self.udp_listener.stop()
        self.cleanup_timer.stop()
        super().closeEvent(event)


if __name__ == '__main__':
    import sys

    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
