import sys

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capture import arm_and_receive, create_mock_capture, find_default_port, list_serial_ports
from capture_model import Capture
from decoder_dialog import DecoderDialog
from decoders import decode_i2c, decode_onewire, decode_spi, decode_uart
from measure import measure_capture
from storage import export_decode_csv, export_raw_csv, open_capture, save_capture


CHANNEL_SPACING = 1.6
MAX_STEP_CHANGES = 12000
RATES = [
    ("100 MSa/s", 100_000_000),
    ("50 MSa/s", 50_000_000),
    ("20 MSa/s", 20_000_000),
    ("10 MSa/s", 10_000_000),
    ("5 MSa/s", 5_000_000),
    ("2 MSa/s", 2_000_000),
    ("1 MSa/s", 1_000_000),
    ("500 kSa/s", 500_000),
    ("100 kSa/s", 100_000),
]
TRIGGERS = ["Off", "Rising", "Falling", "High", "Low", "Pattern"]
COLORS = ["#4fc3f7", "#81c784", "#ffb74d", "#e57373", "#ba68c8", "#4db6ac", "#fff176", "#b0bec5"]


class CaptureWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, port, rate_hz, trigger_type, trigger_channel, pattern_mask, pattern_value):
        super().__init__()
        self.port = port
        self.rate_hz = rate_hz
        self.trigger_type = trigger_type
        self.trigger_channel = trigger_channel
        self.pattern_mask = pattern_mask
        self.pattern_value = pattern_value

    def run(self):
        try:
            if self.port == "MOCK (Simulator)":
                capture = create_mock_capture(
                    self.rate_hz,
                    self.trigger_type,
                    self.trigger_channel,
                    self.pattern_mask,
                    self.pattern_value,
                )
            else:
                capture = arm_and_receive(
                    self.port,
                    self.rate_hz,
                    self.trigger_type,
                    self.trigger_channel,
                    self.pattern_mask,
                    self.pattern_value,
                )
            completed = self.completed
        except Exception as error:
            self.failed.emit(str(error))
            return
        completed.emit(capture)


def channel_offset(ch, channels):
    return (channels - 1 - ch) * CHANNEL_SPACING


def build_step_wave(bits, dt):
    bits = np.asarray(bits, dtype=np.int8)
    if len(bits) == 0:
        return np.array([]), np.array([])
    changes = np.nonzero(np.diff(bits))[0] + 1
    if len(changes) > MAX_STEP_CHANGES:
        stride = int(np.ceil(len(bits) / (MAX_STEP_CHANGES * 2)))
        bits = bits[::stride]
        dt *= stride
        changes = np.nonzero(np.diff(bits))[0] + 1

    xs = np.empty(2 * len(changes) + 2)
    ys = np.empty(2 * len(changes) + 2)
    xs[0] = 0.0
    ys[0] = bits[0]
    if len(changes):
        change_times = changes * dt
        xs[1:-1:2] = change_times
        xs[2:-1:2] = change_times
        ys[1:-1:2] = bits[changes - 1]
        ys[2:-1:2] = bits[changes]
    xs[-1] = len(bits) * dt
    ys[-1] = bits[-1]
    return xs, ys


def fmt_time(seconds):
    if seconds >= 1:
        return f"{seconds:.6f} s"
    if seconds >= 1e-3:
        return f"{seconds * 1e3:.6f} ms"
    if seconds >= 1e-6:
        return f"{seconds * 1e6:.3f} us"
    return f"{seconds * 1e9:.2f} ns"


def fmt_freq(freq):
    if freq >= 1e6:
        return f"{freq / 1e6:.6f} MHz"
    if freq >= 1e3:
        return f"{freq / 1e3:.3f} kHz"
    return f"{freq:.3f} Hz"


class LogicAnalyzerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Logic Analyzer")
        self.resize(1280, 780)

        self.capture: Capture | None = None
        self.capture_worker = None
        self.progress = None
        self.curves = []
        self.annotations = []
        self.decode_rows = []

        self._build_ui()
        self.refresh_ports()
        self._set_capture_actions_enabled(False)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        toolbar = QHBoxLayout()
        layout.addLayout(toolbar)

        self.port_combo = QComboBox()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_ports)
        self.rate_combo = QComboBox()
        for label, _rate in RATES:
            self.rate_combo.addItem(label)

        self.trigger_combo = QComboBox()
        self.trigger_combo.addItems(TRIGGERS)
        self.trigger_combo.currentIndexChanged.connect(self._update_pattern_controls)
        self.trigger_channel = QSpinBox()
        self.trigger_channel.setRange(0, 7)
        self.trigger_channel.setPrefix("CH")

        toolbar.addWidget(QLabel("Port:"))
        toolbar.addWidget(self.port_combo)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(QLabel("Rate:"))
        toolbar.addWidget(self.rate_combo)
        toolbar.addWidget(QLabel("Trigger:"))
        toolbar.addWidget(self.trigger_combo)
        toolbar.addWidget(self.trigger_channel)

        self.pattern_controls = []
        for ch in range(8):
            selector = QComboBox()
            selector.addItems(["-", "0", "1"])
            selector.setFixedWidth(46)
            label = QLabel(f"CH{ch}")
            toolbar.addWidget(label)
            toolbar.addWidget(selector)
            self.pattern_controls.append((label, selector))

        self.capture_button = QPushButton("Capture")
        self.capture_button.clicked.connect(self.start_capture)
        self.decode_button = QPushButton("Run Decoder")
        self.decode_button.clicked.connect(self.run_decoder)
        self.save_button = QPushButton("Save Capture")
        self.save_button.clicked.connect(self.save_current_capture)
        self.open_button = QPushButton("Open Capture")
        self.open_button.clicked.connect(self.open_saved_capture)
        self.export_button = QPushButton("Export CSV")
        self.export_button.clicked.connect(self.export_csv)

        toolbar.addStretch(1)
        toolbar.addWidget(self.capture_button)
        toolbar.addWidget(self.decode_button)
        toolbar.addWidget(self.save_button)
        toolbar.addWidget(self.open_button)
        toolbar.addWidget(self.export_button)

        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setMouseEnabled(x=True, y=False)
        self.plot.setClipToView(True)
        self.plot.setDownsampling(auto=True, mode="peak")
        layout.addWidget(self.plot, 1)

        self.cursor_a = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("#00e676", width=2), label="A")
        self.cursor_b = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("#ff5252", width=2), label="B")
        self.cursor_a.sigPositionChanged.connect(self.update_cursor_label)
        self.cursor_b.sigPositionChanged.connect(self.update_cursor_label)
        self.plot.addItem(self.cursor_a)
        self.plot.addItem(self.cursor_b)

        self.status_label = QLabel("Ready")
        self.cursor_label = QLabel("Delta T: --")
        status_row = QHBoxLayout()
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        status_row.addWidget(self.cursor_label)
        layout.addLayout(status_row)

        self._build_measurements_dock()
        self._build_decode_dock()
        self._update_pattern_controls()

    def _build_measurements_dock(self):
        dock = QDockWidget("Measurements", self)
        dock.setAllowedAreas(dock.allowedAreas())
        widget = QWidget()
        layout = QVBoxLayout(widget)
        row = QHBoxLayout()
        row.addWidget(QLabel("Selected channel:"))
        self.measure_channel_combo = QComboBox()
        self.measure_channel_combo.currentIndexChanged.connect(self.update_measurements_panel)
        row.addWidget(self.measure_channel_combo)
        layout.addLayout(row)

        self.measure_table = QTableWidget(0, 2)
        self.measure_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self.measure_table.verticalHeader().setVisible(False)
        self.measure_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.measure_table)
        dock.setWidget(widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _build_decode_dock(self):
        dock = QDockWidget("Decode Results", self)
        self.decode_table = QTableWidget(0, 4)
        self.decode_table.setHorizontalHeaderLabels(["Time (us)", "Protocol", "Event", "Value"])
        self.decode_table.verticalHeader().setVisible(False)
        self.decode_table.horizontalHeader().setStretchLastSection(True)
        self.decode_table.cellClicked.connect(self.center_on_decode_row)
        dock.setWidget(self.decode_table)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

    def refresh_ports(self):
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = list_serial_ports()
        self.port_combo.addItem("MOCK (Simulator)")
        self.port_combo.addItems(ports)
        default = current if current == "MOCK (Simulator)" or current in ports else find_default_port()
        if default:
            index = self.port_combo.findText(default)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

    def _set_capture_actions_enabled(self, enabled):
        self.decode_button.setEnabled(enabled)
        self.save_button.setEnabled(enabled)
        self.export_button.setEnabled(enabled)

    def _update_pattern_controls(self):
        is_pattern = self.trigger_combo.currentIndex() == 5
        self.trigger_channel.setVisible(not is_pattern)
        for label, selector in self.pattern_controls:
            label.setVisible(is_pattern)
            selector.setVisible(is_pattern)

    def _pattern_bytes(self):
        mask = 0
        value = 0
        for ch, (_label, selector) in enumerate(self.pattern_controls):
            text = selector.currentText()
            if text != "-":
                mask |= 1 << ch
                if text == "1":
                    value |= 1 << ch
        return mask, value

    def start_capture(self):
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "No Port", "Select a serial port before capturing.")
            return

        rate = RATES[self.rate_combo.currentIndex()][1]
        trigger_type = self.trigger_combo.currentIndex()
        pattern_mask, pattern_value = self._pattern_bytes()

        self.capture_button.setEnabled(False)
        self._set_capture_actions_enabled(False)
        self.status_label.setText("Waiting for trigger...")
        self.progress = QProgressDialog("Waiting for trigger...", None, 0, 0, self)
        self.progress.setWindowTitle("Capture")
        self.progress.setCancelButton(None)
        self.progress.setMinimumDuration(0)
        self.progress.show()

        self.capture_worker = CaptureWorker(
            port,
            rate,
            trigger_type,
            self.trigger_channel.value(),
            pattern_mask,
            pattern_value,
        )
        self.capture_worker.completed.connect(self.capture_completed)
        self.capture_worker.failed.connect(self.capture_failed)
        self.capture_worker.finished.connect(self.capture_worker.deleteLater)
        self.capture_worker.start()

    def capture_completed(self, capture):
        if self.progress:
            self.progress.close()
            self.progress = None
        self.capture_worker = None
        measure_capture(capture)
        self.capture = capture
        self.render_capture()
        self.populate_measurement_channels()
        self._set_capture_actions_enabled(True)
        self.capture_button.setEnabled(True)
        trigger_status = "triggered" if capture.triggered or capture.trigger_type == 0 else "timeout fallback"
        self.status_label.setText(
            f"{capture.sample_rate / 1e6:.3f} MSa/s | {capture.num_samples} samples | {fmt_time(capture.duration)} | {trigger_status}"
        )

    def capture_failed(self, message):
        if self.progress:
            self.progress.close()
            self.progress = None
        self.capture_worker = None
        self.capture_button.setEnabled(True)
        self._set_capture_actions_enabled(self.capture is not None)
        self.status_label.setText("Capture failed")
        QMessageBox.critical(self, "Capture Failed", message)

    def render_capture(self):
        if not self.capture:
            return

        self.plot.clear()
        self.curves = []
        self.annotations = []
        dt = 1.0 / self.capture.sample_rate
        for ch in range(self.capture.channels):
            xs, ys = build_step_wave(self.capture.channel_bits(ch), dt)
            y = ys * 0.8 + channel_offset(ch, self.capture.channels)
            curve = self.plot.plot(xs, y, pen=pg.mkPen(COLORS[ch % len(COLORS)], width=1.4))
            self.curves.append(curve)

        ticks = [[(channel_offset(ch, self.capture.channels) + 0.4, f"CH{ch}") for ch in range(self.capture.channels)]]
        self.plot.getAxis("left").setTicks(ticks)
        self.plot.setYRange(-0.4, channel_offset(0, self.capture.channels) + 1.4, padding=0)
        self.plot.setXRange(0, max(self.capture.duration, 1e-6), padding=0.02)
        self.plot.addItem(self.cursor_a)
        self.plot.addItem(self.cursor_b)
        self.cursor_a.setValue(self.capture.duration * 0.25)
        self.cursor_b.setValue(self.capture.duration * 0.75)
        self.update_cursor_label()
        self.render_decode_annotations()

    def update_cursor_label(self):
        delta = abs(self.cursor_b.value() - self.cursor_a.value())
        if delta > 0:
            self.cursor_label.setText(
                f"Delta T: {fmt_time(delta)} | Frequency: {fmt_freq(1.0 / delta)} | Period: {fmt_time(delta)}"
            )
        else:
            self.cursor_label.setText("Delta T: 0")

    def populate_measurement_channels(self):
        self.measure_channel_combo.blockSignals(True)
        self.measure_channel_combo.clear()
        if self.capture:
            self.measure_channel_combo.addItems([f"CH{ch}" for ch in range(self.capture.channels)])
        self.measure_channel_combo.blockSignals(False)
        self.update_measurements_panel()

    def update_measurements_panel(self):
        if not self.capture or not self.capture.measurements:
            self.measure_table.setRowCount(0)
            return
        channel = self.measure_channel_combo.currentIndex()
        measurement = self.capture.measurements.get(channel, {})
        rows = [
            ("Frequency", fmt_freq(measurement["freq"]) if "freq" in measurement else f"static {measurement.get('level', 0)}"),
            ("Period", fmt_time(measurement["period"]) if "period" in measurement else "--"),
            ("Duty cycle", f"{measurement.get('duty', 0):.2f}%" if "duty" in measurement else "--"),
            ("Edge count", str(measurement.get("n_edges", 0))),
            ("Average high", fmt_time(measurement["high_avg"]) if "high_avg" in measurement else "--"),
            ("Average low", fmt_time(measurement["low_avg"]) if "low_avg" in measurement else "--"),
            ("Jitter", fmt_time(measurement["jitter"]) if "jitter" in measurement else "--"),
        ]
        self.measure_table.setRowCount(len(rows))
        for row, (metric, value) in enumerate(rows):
            self.measure_table.setItem(row, 0, QTableWidgetItem(metric))
            self.measure_table.setItem(row, 1, QTableWidgetItem(value))

    def run_decoder(self):
        if not self.capture:
            return
        dialog = DecoderDialog(self.capture.channels, self.capture.sample_rate, self)
        if dialog.exec():
            self.apply_decoder(dialog.get_config())

    def apply_decoder(self, config):
        if not self.capture:
            return
        protocol = config["protocol"]
        rows = []
        if protocol == "UART":
            ch = config["channel"]
            decoded = decode_uart(self.capture.channel_bits(ch), config["baudrate"], self.capture.sample_rate)
            self.capture.decoded_uart = decoded
            for item in decoded:
                t_us = (item["start"] + item["end"]) / 2 / self.capture.sample_rate * 1e6
                rows.append({"time_us": t_us, "protocol": "UART", "event": "BYTE", "value": f"0x{item['value']:02X}", "channel": ch})
        elif protocol == "I2C":
            sda = config["sda"]
            decoded = decode_i2c(self.capture.channel_bits(sda), self.capture.channel_bits(config["scl"]), self.capture.sample_rate)
            self.capture.decoded_i2c = decoded
            for item in decoded:
                t_us = (item["start"] + item["end"]) / 2 / self.capture.sample_rate * 1e6
                value = "" if item["value"] is None else f"0x{item['value']:02X}"
                rows.append({"time_us": t_us, "protocol": "I2C", "event": item["kind"], "value": value, "channel": sda})
        elif protocol == "SPI":
            decoded = decode_spi(
                self.capture.channel_bits(config["mosi"]),
                self.capture.channel_bits(config["sck"]),
                self.capture.channel_bits(config["cs"]),
                self.capture.sample_rate,
                miso=self.capture.channel_bits(config["miso"]),
                mode=config["mode"],
            )
            self.capture.decoded_spi = decoded
            for item in decoded:
                t_us = (item["start"] + item["end"]) / 2 / self.capture.sample_rate * 1e6
                rows.append({"time_us": t_us, "protocol": "SPI", "event": "MOSI", "value": f"0x{item['mosi']:02X}", "channel": config["mosi"]})
                if item["miso"] is not None:
                    rows.append({"time_us": t_us, "protocol": "SPI", "event": "MISO", "value": f"0x{item['miso']:02X}", "channel": config["miso"]})
        else:
            dq = config["dq"]
            decoded = decode_onewire(self.capture.channel_bits(dq), self.capture.sample_rate)
            self.capture.decoded_onewire = decoded
            for item in decoded:
                t_us = (item["start"] + item["end"]) / 2 / self.capture.sample_rate * 1e6
                value = "" if item["value"] is None else f"0x{item['value']:02X}"
                rows.append({"time_us": t_us, "protocol": "ONEWIRE", "event": item["kind"], "value": value, "channel": dq})

        self.decode_rows = sorted(rows, key=lambda row: row["time_us"])
        self.populate_decode_table()
        self.render_decode_annotations()
        self.status_label.setText(f"{protocol}: {len(self.decode_rows)} decode rows")

    def populate_decode_table(self):
        self.decode_table.setRowCount(len(self.decode_rows))
        for row_index, row in enumerate(self.decode_rows):
            values = [f"{row['time_us']:.3f}", row["protocol"], row["event"], row["value"]]
            for col, value in enumerate(values):
                self.decode_table.setItem(row_index, col, QTableWidgetItem(value))

    def render_decode_annotations(self):
        for item in self.annotations:
            self.plot.removeItem(item)
        self.annotations = []
        if not self.capture:
            return
        for row in self.decode_rows[:400]:
            timestamp = row["time_us"] / 1e6
            channel = min(int(row.get("channel", 0)), self.capture.channels - 1)
            label = row["value"] or row["event"]
            item = pg.TextItem(label, color=(0, 0, 0), anchor=(0.5, 1), fill=pg.mkBrush("#ffd54f"))
            item.setPos(timestamp, channel_offset(channel, self.capture.channels) + 1.0)
            self.plot.addItem(item)
            self.annotations.append(item)

    def center_on_decode_row(self, row, _column):
        if not self.capture or row >= len(self.decode_rows):
            return
        center = self.decode_rows[row]["time_us"] / 1e6
        view_range = self.plot.viewRange()[0]
        width = max(view_range[1] - view_range[0], self.capture.duration * 0.02, 1e-6)
        left = max(0, center - width / 2)
        right = min(self.capture.duration, center + width / 2)
        if right <= left:
            right = left + width
        self.plot.setXRange(left, right, padding=0)

    def save_current_capture(self):
        if not self.capture:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Capture", "capture.npz", "Capture (*.npz)")
        if path:
            if not path.endswith(".npz"):
                path += ".npz"
            save_capture(path, self.capture)
            self.status_label.setText(f"Saved {path}")

    def open_saved_capture(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Capture", "", "Capture (*.npz)")
        if not path:
            return
        try:
            self.capture = open_capture(path)
            if not self.capture.measurements:
                measure_capture(self.capture)
            self.decode_rows = self._rows_from_saved_decoders()
            self.render_capture()
            self.populate_measurement_channels()
            self.populate_decode_table()
            self._set_capture_actions_enabled(True)
            self.status_label.setText(f"Opened {path}")
        except Exception as error:
            QMessageBox.critical(self, "Open Failed", str(error))

    def _rows_from_saved_decoders(self):
        if not self.capture:
            return []
        rows = []
        for item in self.capture.decoded_uart:
            t_us = (item["start"] + item["end"]) / 2 / self.capture.sample_rate * 1e6
            rows.append({"time_us": t_us, "protocol": "UART", "event": "BYTE", "value": f"0x{item['value']:02X}", "channel": 0})
        for item in self.capture.decoded_i2c:
            t_us = (item["start"] + item["end"]) / 2 / self.capture.sample_rate * 1e6
            value = "" if item["value"] is None else f"0x{item['value']:02X}"
            rows.append({"time_us": t_us, "protocol": "I2C", "event": item["kind"], "value": value, "channel": 0})
        for item in self.capture.decoded_spi:
            t_us = (item["start"] + item["end"]) / 2 / self.capture.sample_rate * 1e6
            rows.append({"time_us": t_us, "protocol": "SPI", "event": "MOSI", "value": f"0x{item['mosi']:02X}", "channel": 0})
        for item in self.capture.decoded_onewire:
            t_us = (item["start"] + item["end"]) / 2 / self.capture.sample_rate * 1e6
            value = "" if item["value"] is None else f"0x{item['value']:02X}"
            rows.append({"time_us": t_us, "protocol": "ONEWIRE", "event": item["kind"], "value": value, "channel": 0})
        return sorted(rows, key=lambda row: row["time_us"])

    def export_csv(self):
        if not self.capture:
            return
        if self.decode_rows:
            path, _ = QFileDialog.getSaveFileName(self, "Export Decode CSV", "decoded.csv", "CSV (*.csv)")
            if path:
                if not path.endswith(".csv"):
                    path += ".csv"
                export_decode_csv(path, self.decode_rows)
                self.status_label.setText(f"Exported {path}")
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Export Raw CSV", "raw.csv", "CSV (*.csv)")
            if path:
                if not path.endswith(".csv"):
                    path += ".csv"
                export_raw_csv(path, self.capture)
                self.status_label.setText(f"Exported {path}")


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = LogicAnalyzerWindow()
    window.show()
    sys.exit(app.exec())
