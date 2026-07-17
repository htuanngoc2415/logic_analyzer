from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class DecoderDialog(QDialog):
    def __init__(self, channels, sample_rate, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Run Decoder")
        self.channels = channels
        self.sample_rate = sample_rate

        layout = QVBoxLayout(self)
        protocol_row = QHBoxLayout()
        protocol_row.addWidget(QLabel("Protocol:"))
        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["UART", "I2C", "SPI", "1-Wire"])
        self.protocol_combo.currentIndexChanged.connect(self._show_protocol_page)
        protocol_row.addWidget(self.protocol_combo)
        layout.addLayout(protocol_row)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_uart_page())
        self.pages.addWidget(self._build_i2c_page())
        self.pages.addWidget(self._build_spi_page())
        self.pages.addWidget(self._build_onewire_page())
        layout.addWidget(self.pages)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        run_button = QPushButton("Run")
        run_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        buttons.addWidget(run_button)
        layout.addLayout(buttons)

    def _channel_spin(self, value=0):
        spin = QSpinBox()
        spin.setRange(0, self.channels - 1)
        spin.setValue(min(value, self.channels - 1))
        spin.setPrefix("CH")
        return spin

    def _build_uart_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.uart_channel = self._channel_spin(0)
        self.uart_baud = QLineEdit("115200")
        form.addRow("RX:", self.uart_channel)
        form.addRow("Baud:", self.uart_baud)
        form.addRow("Sample rate:", QLabel(f"{self.sample_rate} Hz"))
        return page

    def _build_i2c_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.i2c_sda = self._channel_spin(0)
        self.i2c_scl = self._channel_spin(1)
        form.addRow("SDA:", self.i2c_sda)
        form.addRow("SCL:", self.i2c_scl)
        return page

    def _build_spi_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.spi_sck = self._channel_spin(0)
        self.spi_mosi = self._channel_spin(1)
        self.spi_miso = self._channel_spin(2)
        self.spi_cs = self._channel_spin(3)
        self.spi_mode = QSpinBox()
        self.spi_mode.setRange(0, 3)
        form.addRow("SCK:", self.spi_sck)
        form.addRow("MOSI:", self.spi_mosi)
        form.addRow("MISO:", self.spi_miso)
        form.addRow("CS:", self.spi_cs)
        form.addRow("Mode:", self.spi_mode)
        return page

    def _build_onewire_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.onewire_dq = self._channel_spin(0)
        form.addRow("DQ:", self.onewire_dq)
        return page

    def _show_protocol_page(self, index):
        self.pages.setCurrentIndex(index)

    def get_config(self):
        protocol = self.protocol_combo.currentText()
        if protocol == "UART":
            return {
                "protocol": "UART",
                "channel": self.uart_channel.value(),
                "baudrate": int(self.uart_baud.text()),
            }
        if protocol == "I2C":
            return {
                "protocol": "I2C",
                "sda": self.i2c_sda.value(),
                "scl": self.i2c_scl.value(),
            }
        if protocol == "SPI":
            return {
                "protocol": "SPI",
                "sck": self.spi_sck.value(),
                "mosi": self.spi_mosi.value(),
                "miso": self.spi_miso.value(),
                "cs": self.spi_cs.value(),
                "mode": self.spi_mode.value(),
            }
        return {"protocol": "1-Wire", "dq": self.onewire_dq.value()}
