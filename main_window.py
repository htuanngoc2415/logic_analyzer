import numpy as np
import sys
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QComboBox, QLabel, QSpinBox)
from PyQt6.QtCore import QTimer
import pyqtgraph as pg
from serial.tools import list_ports

from data_parser import DataParser
from serial_worker import SerialWorker
from mock_device import MockWorker

class LogicAnalyzerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Logic Analyzer")
        self.resize(1000, 600)

        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.layout = QVBoxLayout(central_widget)
        
        # Toolbar
        self.toolbar_layout = QHBoxLayout()
        self.layout.addLayout(self.toolbar_layout)

        # Port Selection
        self.port_combo = QComboBox()
        self.refresh_ports()
        self.toolbar_layout.addWidget(QLabel("Port:"))
        self.toolbar_layout.addWidget(self.port_combo)

        # Refresh Ports Button
        self.btn_refresh = QPushButton("Refresh Ports")
        self.btn_refresh.clicked.connect(self.refresh_ports)
        self.toolbar_layout.addWidget(self.btn_refresh)
        
        # Clear Plot Button
        self.btn_clear = QPushButton("Clear View")
        self.btn_clear.clicked.connect(self.clear_plot_data)
        self.toolbar_layout.addWidget(self.btn_clear)

        # Baudrate Selection
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "115200", "230400", "921600", "1000000", "2000000"])
        self.baud_combo.setCurrentText("115200")
        self.toolbar_layout.addWidget(QLabel("Baud:"))
        self.toolbar_layout.addWidget(self.baud_combo)

        # Data Format
        self.format_combo = QComboBox()
        self.format_combo.addItems(["binary", "text"])
        self.toolbar_layout.addWidget(QLabel("Format:"))
        self.toolbar_layout.addWidget(self.format_combo)

        # Channels Selection
        self.channels_spin = QSpinBox()
        self.channels_spin.setRange(2, 24)
        self.channels_spin.setValue(8)
        self.toolbar_layout.addWidget(QLabel("Channels:"))
        self.toolbar_layout.addWidget(self.channels_spin)

        # Start/Stop Button
        self.btn_start = QPushButton("Start Capture")
        self.btn_start.clicked.connect(self.toggle_capture)
        self.toolbar_layout.addWidget(self.btn_start)
        
        self.toolbar_layout.addStretch()

        # pyqtgraph configuration
        pg.setConfigOptions(antialias=False)  # turn off for digital signals to look sharp
        self.plot_widget = pg.PlotWidget()
        self.layout.addWidget(self.plot_widget)

        # Setup plot axes
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel('bottom', "Time / Samples")
        self.plot_widget.setLabel('left', "Channels")
        self.plot_widget.setLimits(xMin=-1)
        
        # Internal state
        self.is_capturing = False
        self.worker = None
        self.parser = None
        self.plot_curves = []
        
        self.channel_data = [] # List of numpy arrays
        self.time_data = np.array([], dtype=np.uint32)
        self.sample_count = 0
        
        # Timer to update plot so UI doesn't freeze
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_plot)
        self.update_timer.setInterval(40) # ~25 FPS

    def refresh_ports(self):
        self.port_combo.clear()
        self.port_combo.addItem("MOCK (Simulator)")
        ports = [port.device for port in list_ports.comports()]
        self.port_combo.addItems(ports)

    def clear_plot_data(self):
        channels = self.channels_spin.value()
        self.channel_data = [np.array([], dtype=np.int8) for _ in range(channels)]
        self.time_data = np.array([], dtype=np.uint32)
        self.sample_count = 0
        if not self.is_capturing:
            self.init_plot()

    def init_plot(self):
        self.plot_widget.clear()
        self.plot_curves = []
        channels = self.channels_spin.value()
        
        # Define some bright colors for the channels
        COLORS = [
            (0, 255, 255),   # Cyan
            (255, 0, 255),   # Magenta
            (255, 255, 0),   # Yellow
            (0, 255, 0),     # Green
            (255, 100, 100), # Red
            (100, 150, 255), # Blue
            (255, 165, 0),   # Orange
            (200, 200, 200), # White
        ]
        
        # Create Y-axis custom ticks
        ticks = []
        for i in range(channels):
            color = COLORS[i % len(COLORS)]
            pen = pg.mkPen(color=color, width=2)
            curve = pg.PlotCurveItem(pen=pen)
            self.plot_widget.addItem(curve)
            self.plot_curves.append(curve)
            ticks.append((i * 2 + 0.5, f"CH {i}"))
            
        ax = self.plot_widget.getAxis('left')
        ax.setTicks([ticks])
        self.plot_widget.setYRange(-1, channels * 2)

    def toggle_capture(self):
        if not self.is_capturing:
            self.start_capture()
        else:
            self.stop_capture()

    def start_capture(self):
        self.btn_start.setText("Stop Capture")
        self.is_capturing = True
        
        # Setup Data
        channels = self.channels_spin.value()
        mode = self.format_combo.currentText()
        self.parser = DataParser(channels=channels, mode=mode)
        
        self.channel_data = [np.array([], dtype=np.int8) for _ in range(channels)]
        self.time_data = np.array([], dtype=np.uint32)
        self.sample_count = 0
        
        self.init_plot()
        
        # Lock UI config
        self.port_combo.setEnabled(False)
        self.baud_combo.setEnabled(False)
        self.format_combo.setEnabled(False)
        self.channels_spin.setEnabled(False)
        self.btn_refresh.setEnabled(False)

        # Setup Worker
        port = self.port_combo.currentText()
        baudrate = int(self.baud_combo.currentText())
        
        if port == "MOCK (Simulator)":
            self.worker = MockWorker(mode=mode, channels=channels, baudrate=baudrate)
        else:
            self.worker = SerialWorker(port=port, baudrate=baudrate)
            
        self.worker.data_received.connect(self.process_raw_data)
        self.worker.start()
        
        self.update_timer.start()

    def stop_capture(self):
        self.btn_start.setText("Start Capture")
        self.is_capturing = False
        
        if self.worker:
            self.worker.stop()
            self.worker = None
            
        self.update_timer.stop()
        self.update_plot() # Final update
        
        # Unlock UI config
        self.port_combo.setEnabled(True)
        self.baud_combo.setEnabled(True)
        self.format_combo.setEnabled(True)
        self.channels_spin.setEnabled(True)
        self.btn_refresh.setEnabled(True)

    def process_raw_data(self, raw_bytes):
        samples = self.parser.parse(raw_bytes)
        if not samples:
            return
            
        new_ch_data = self.parser.extract_channels_numpy(samples)
        num_new_samples = len(samples)
        
        new_time = np.arange(self.sample_count, self.sample_count + num_new_samples, dtype=np.uint32)
        self.sample_count += num_new_samples
        
        self.time_data = np.concatenate([self.time_data, new_time])
        for i in range(self.parser.channels):
            self.channel_data[i] = np.concatenate([self.channel_data[i], new_ch_data[i]])

    def update_plot(self):
        if self.sample_count == 0:
            return
            
        # Limit points to plot for performance (last 50000 points)
        max_points = 50000
        start_idx = max(0, self.sample_count - max_points)
        
        t = self.time_data[start_idx:]
        if len(t) == 0:
            return
            
        # Manual step mode conversion to avoid pyqtgraph stepMode shape bugs
        x_step = np.empty(2 * len(t), dtype=t.dtype)
        x_step[0::2] = t
        x_step[1::2] = t + 1
        
        for i, curve in enumerate(self.plot_curves):
            y = self.channel_data[i][start_idx:]
            y_step = np.repeat(y, 2)
            y_offset = i * 2
            curve.setData(x_step, y_step + y_offset)
