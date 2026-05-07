from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QSpinBox, QLineEdit, QPushButton, QWidget)

class DecoderDialog(QDialog):
    def __init__(self, channels, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Protocol Decoder")
        self.channels = channels
        self.layout = QVBoxLayout(self)
        
        # Protocol selection
        self.proto_layout = QHBoxLayout()
        self.proto_layout.addWidget(QLabel("Protocol:"))
        self.proto_combo = QComboBox()
        self.proto_combo.addItems(["UART", "SPI"])
        self.proto_combo.currentIndexChanged.connect(self.update_ui)
        self.proto_layout.addWidget(self.proto_combo)
        self.layout.addLayout(self.proto_layout)
        
        # UART config
        self.uart_widget = QWidget()
        self.uart_layout = QVBoxLayout(self.uart_widget)
        
        ch_layout = QHBoxLayout()
        ch_layout.addWidget(QLabel("RX Channel:"))
        self.uart_ch = QComboBox()
        self.uart_ch.addItems([f"CH {i}" for i in range(channels)])
        ch_layout.addWidget(self.uart_ch)
        self.uart_layout.addLayout(ch_layout)
        
        baud_layout = QHBoxLayout()
        baud_layout.addWidget(QLabel("Baudrate:"))
        self.baud_input = QLineEdit("115200")
        baud_layout.addWidget(self.baud_input)
        
        baud_layout.addWidget(QLabel("Sample Rate (Hz):"))
        self.sample_input = QLineEdit("1000000")
        baud_layout.addWidget(self.sample_input)
        self.uart_layout.addLayout(baud_layout)
        
        self.layout.addWidget(self.uart_widget)
        
        # SPI config
        self.spi_widget = QWidget()
        self.spi_layout = QVBoxLayout(self.spi_widget)
        
        for name in ["SCK", "MOSI", "MISO", "CS"]:
            l = QHBoxLayout()
            l.addWidget(QLabel(f"{name} Channel:"))
            cb = QComboBox()
            cb.addItem("None")
            cb.addItems([f"CH {i}" for i in range(channels)])
            setattr(self, f"spi_{name.lower()}", cb)
            l.addWidget(cb)
            self.spi_layout.addLayout(l)
            
        self.layout.addWidget(self.spi_widget)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_decode = QPushButton("Decode")
        self.btn_decode.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_decode)
        self.layout.addLayout(btn_layout)
        
        self.update_ui()
        
    def update_ui(self):
        proto = self.proto_combo.currentText()
        if proto == "UART":
            self.uart_widget.setVisible(True)
            self.spi_widget.setVisible(False)
        else:
            self.uart_widget.setVisible(False)
            self.spi_widget.setVisible(True)

    def get_config(self):
        proto = self.proto_combo.currentText()
        if proto == "UART":
            return {
                "protocol": "UART",
                "channel": self.uart_ch.currentIndex(),
                "baudrate": int(self.baud_input.text()),
                "sample_rate": int(self.sample_input.text())
            }
        else:
            return {
                "protocol": "SPI",
                "sck": self.spi_sck.currentIndex() - 1,
                "mosi": self.spi_mosi.currentIndex() - 1,
                "miso": self.spi_miso.currentIndex() - 1,
                "cs": self.spi_cs.currentIndex() - 1
            }
