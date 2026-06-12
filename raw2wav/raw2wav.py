# raw2wav.py
# Companion app for fpvGoggleAudioRecorder to convert raw pcm files to wav files
# Compiling requires python 3, pillow, and PySide6
# Compile command (from raw2wav.py directory): pyinstaller --noconsole --onefile --add-data "background.png;." --add-data "icon.png;." raw2wav.py
# Background image is 900x750 pixels, Icon image should be 32x32 or 64x64 pixels

import sys
import os
import wave
import threading
import subprocess

# Natively handle Windows taskbar ID registry to ensure the icon displays correctly
if sys.platform == "win32":
    import ctypes
    myappid = "mycompany.fpvconverter.raw2wav.1.0"  # Arbitrary unique string descriptor
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QFileDialog, 
    QLabel, QVBoxLayout, QHBoxLayout, QTextBrowser, QTableWidget, QTableWidgetItem, QProgressBar,
    QGraphicsDropShadowEffect, QHeaderView
)
from PySide6.QtGui import QPixmap, QColor, QFont, QIcon
from PySide6.QtCore import Qt, Signal, QObject, QUrl

# -------------------------
# THREAD SAFE SIGNALS
# -------------------------

class Bridge(QObject):
    log = Signal(str)
    progress = Signal(int)
    status = Signal(str)


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def get_raw_file_size_str(filepath):
    """Calculates file size and returns a clean MB string layout."""
    try:
        bytes_size = os.path.getsize(filepath)
        mb_size = bytes_size / (1024 * 1024)
        return f"{mb_size:.2f} MB"
    except Exception:
        return "0.00 MB"


def get_raw_duration(filepath):
    """Calculates the playtime of a raw PCM file based on 44100Hz, 16-bit, Mono."""
    try:
        file_size = os.path.getsize(filepath)
        # 1 channel * 2 bytes per sample (16-bit) * 44100 samples per second = 88200 bytes per second
        total_seconds = int(file_size / 88200)
        
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"
    except Exception:
        return "00:00"


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("FPV Converter PRO")
        self.setFixedSize(900, 750)

        # SET CUSTOM WINDOW & TASKBAR ICON
        # Looks for an "icon.png" inside your local file script tree or compiled executable bundle
        self.setWindowIcon(QIcon(resource_path("icon.png")))

        self.files = []
        self.use_custom = False
        self.output_folder = ""

        self.bridge = Bridge()
        self.bridge.log.connect(self.log_msg)
        self.bridge.progress.connect(self.progress_set)
        self.bridge.status.connect(self.status_set)

        self.init_ui()

    # -------------------------
    # UI
    # -------------------------

    def init_ui(self):
        # Background Setup
        self.bg = QLabel(self)
        pix = QPixmap(resource_path("background.png"))
        self.bg.setPixmap(pix)
        self.bg.setScaledContents(True)
        self.bg.setGeometry(0, 0, 900, 750)
        self.bg.lower()

        # Container
        container = QWidget(self)
        container.setGeometry(0, 0, 900, 750)
        container.setAttribute(Qt.WA_TranslucentBackground)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # CENTERED & GLOWING TITLE
        title = QLabel("FPV RAW → WAV CONVERTER PRO")
        title.setAlignment(Qt.AlignCenter)
        
        font = title.font()
        font.setPointSize(22)
        font.setBold(True)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 1)
        title.setFont(font)
        
        palette = title.palette()
        palette.setColor(title.foregroundRole(), QColor("#FFFFFF"))
        title.setPalette(palette)
        title.setContentsMargins(10, 10, 10, 10)
        
        glow_effect = QGraphicsDropShadowEffect(title)
        glow_effect.setBlurRadius(20)
        glow_effect.setColor(QColor(0, 150, 255, 255))
        glow_effect.setOffset(0, 0)
        title.setGraphicsEffect(glow_effect)
        
        layout.addWidget(title)

        # BUTTONS ROW
        row = QHBoxLayout()
        self.btn_folder = QPushButton("Folder")
        self.btn_files = QPushButton("Files")
        self.btn_start = QPushButton("START")
        self.btn_start.setEnabled(False)

        self.default_style = """
        QPushButton {
            background: rgba(40,40,40,180);
            color: white;
            padding: 8px;
            border-radius: 6px;
        }
        QPushButton:hover {
            background: rgba(70,70,70,200);
        }
        QPushButton:disabled {
            background: rgba(25,25,25,140);
            color: rgba(255,255,255,120);
        }
        """

        self.start_style = """
        QPushButton {
            background: rgba(0,120,255,230);
            color: white;
            padding: 8px;
            border-radius: 6px;
            font-weight: bold;
        }
        QPushButton:hover {
            background: rgba(20,150,255,255);
        }
        """

        self.btn_folder.setStyleSheet(self.default_style)
        self.btn_files.setStyleSheet(self.default_style)
        self.btn_start.setStyleSheet(self.default_style)

        row.addWidget(self.btn_folder)
        row.addWidget(self.btn_files)
        row.addWidget(self.btn_start)
        layout.addLayout(row)

        # BODY LAYOUT
        body = QHBoxLayout()

        # Left Column Container (Queue Table)
        left_panel = QVBoxLayout()

        self.queue = QTableWidget()
        self.queue.setColumnCount(3)
        self.queue.setHorizontalHeaderLabels(["File Name", "Size", "Duration"])
        self.queue.verticalHeader().setVisible(False)
        self.queue.setSelectionBehavior(QTableWidget.SelectRows)
        self.queue.setEditTriggers(QTableWidget.NoEditTriggers)

        self.queue.setStyleSheet("""
        QTableWidget {
            background: rgba(0,0,0,140);
            color: white;
            gridline-color: rgba(255, 255, 255, 30);
            border-radius: 8px;
            font-family: Consolas;
            font-size: 12px;
        }
        QHeaderView::section {
            background-color: rgba(20, 20, 20, 180);
            color: #00FF88;
            font-family: Consolas;
            font-weight: bold;
            font-size: 11px;
            padding: 6px;
            border: none;
        }
        QTableWidget::item {
            padding: 4px;
        }
        """)

        header = self.queue.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.queue.setColumnWidth(1, 100)
        self.queue.setColumnWidth(2, 90)

        left_panel.addWidget(self.queue)
        body.addLayout(left_panel, 2)

        # Right Side Control Panel
        right = QVBoxLayout()

        input_row = QHBoxLayout()
        self.input_dot = QLabel("●")
        self.input_label = QLabel("Input: None")
        input_row.addWidget(self.input_dot)
        input_row.addWidget(self.input_label)
        right.addLayout(input_row)

        self.custom_btn = QPushButton("Use Custom Output Folder")
        self.custom_btn.setCheckable(True)
        self.custom_btn.clicked.connect(self.toggle_output_mode)
        right.addWidget(self.custom_btn)

        output_row = QHBoxLayout()
        self.output_dot = QLabel("●")
        self.path_label = QLabel("Output: Default (same as input)")
        output_row.addWidget(self.output_dot)
        output_row.addWidget(self.path_label)
        right.addLayout(output_row)

        self.status = QLabel("Idle")
        self.status.setStyleSheet("color: white;")
        right.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setFormat("%p% (%v/%m)")
        right.addWidget(self.progress)

        right.addStretch()
        body.addLayout(right, 1)
        layout.addLayout(body)

        # INTERACTIVE LOG WINDOW
        self.log = QTextBrowser()
        self.log.setReadOnly(True)
        self.log.setOpenLinks(False)
        self.log.setStyleSheet("""
        QTextBrowser {
            background: rgba(0,0,0,160);
            color: #00FF88;
            font-family: Consolas;
        }
        a {
            color: #00FF88;
            text-decoration: underline;
        }
        a:hover {
            color: #00FFFF;
        }
        """)
        layout.addWidget(self.log)

        # Connections
        self.btn_folder.clicked.connect(self.select_folder)
        self.btn_files.clicked.connect(self.select_files)
        self.btn_start.clicked.connect(self.convert)
        self.log.anchorClicked.connect(self.open_path_in_explorer)
        self.queue.itemChanged.connect(self.handle_item_checked_changed)

        self.update_states()

    # -------------------------
    # UTILITIES / HANDLERS
    # -------------------------

    def open_path_in_explorer(self, url: QUrl):
        """Cross-platform directory handler to open path in OS explorer and highlight target file."""
        local_path = url.toLocalFile()
        if not os.path.exists(local_path):
            return

        try:
            if sys.platform == "win32":
                subprocess.run(['explorer', '/select,', os.path.normpath(local_path)])
            elif sys.platform == "darwin":
                subprocess.run(['open', '-R', local_path])
            else:
                folder = os.path.dirname(local_path)
                subprocess.run(['xdg-open', folder])
        except Exception as e:
            print(f"Failed to launch OS file browser: {e}")

    def update_states(self):
        checked_count = 0
        for i in range(self.queue.rowCount()):
            item = self.queue.item(i, 0)
            if item and item.checkState() == Qt.Checked:
                checked_count += 1

        valid = checked_count > 0
        active = "#00FF88"
        inactive = "red"
        color = active if valid else inactive

        label_style = f"color: {color}; font-size: 11px; font-family: Consolas; font-weight: bold;"
        self.input_dot.setStyleSheet(f"color: {color}; font-size: 14px;")
        self.output_dot.setStyleSheet(f"color: {color}; font-size: 14px;")
        self.input_label.setStyleSheet(label_style)
        self.path_label.setStyleSheet(label_style)

        if valid:
            if checked_count == 1:
                for i in range(self.queue.rowCount()):
                    item = self.queue.item(i, 0)
                    if item and item.checkState() == Qt.Checked:
                        self.input_label.setText(f"Input: {self.files[i]}")
                        break
            else:
                self.input_label.setText(f"Input: {checked_count} files selected to convert")
        else:
            self.input_label.setText("Input: None (No files checked)")

        if self.use_custom and self.output_folder:
            self.path_label.setText(f"Output: {self.output_folder}")
        else:
            self.path_label.setText("Output: Default (same as input)")

        self.btn_start.setEnabled(valid)
        self.btn_start.setStyleSheet(self.start_style if valid else self.default_style)

    def handle_item_checked_changed(self, item):
        if item.column() == 0:
            self.update_states()

    def toggle_output_mode(self):
        if self.custom_btn.isChecked():
            folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
            if folder:
                self.use_custom = True
                self.output_folder = folder
            else:
                self.custom_btn.setChecked(False)
                self.use_custom = False
                self.output_folder = ""
        else:
            self.use_custom = False
            self.output_folder = ""
        
        self.update_states()

    def log_msg(self, msg):
        if "[INPUT]" in msg or "[OUTPUT]" in msg:
            prefix, path = msg.split("]", 1)
            path = path.strip()
            url = QUrl.fromLocalFile(path).toString()
            html_msg = f"{prefix}] <a href='{url}'>{path}</a>"
            self.log.append(html_msg)
        else:
            self.log.append(msg)

    def progress_set(self, v):
        self.progress.setValue(v)

    def status_set(self, s):
        self.status.setText(s)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder Containing RAW Files")
        if not folder:
            return

        self.files = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(".raw")
        ]
        self.refresh_queue()
        self.update_states()

    def select_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select RAW files", "", "RAW Files (*.raw)"
        )
        if files:
            self.files = files
            self.refresh_queue()
            self.update_states()

    def refresh_queue(self):
        self.queue.blockSignals(True)
        self.queue.setRowCount(0)
        self.queue.setRowCount(len(self.files))
        
        for row_index, f in enumerate(self.files):
            filename = os.path.basename(f)
            size_str = get_raw_file_size_str(f)
            duration_str = get_raw_duration(f)
            
            name_item = QTableWidgetItem(filename)
            name_item.setFlags(name_item.flags() | Qt.ItemIsUserCheckable)
            name_item.setCheckState(Qt.Checked)
            self.queue.setItem(row_index, 0, name_item)
            
            size_item = QTableWidgetItem(size_str)
            size_item.setTextAlignment(Qt.AlignCenter) 
            self.queue.setItem(row_index, 1, size_item)
            
            duration_item = QTableWidgetItem(duration_str)
            duration_item.setTextAlignment(Qt.AlignCenter)
            self.queue.setItem(row_index, 2, duration_item)
            
        self.queue.blockSignals(False)

    def convert(self):
        if not self.files:
            return

        checked_indices = []
        for i in range(self.queue.rowCount()):
            item = self.queue.item(i, 0)
            if item and item.checkState() == Qt.Checked:
                checked_indices.append(i)

        if not checked_indices:
            return

        def worker():
            total = len(checked_indices)
            self.progress.setMaximum(total)
            self.bridge.log.emit("---- CONVERSION START ----")

            for progress_index, file_index in enumerate(checked_indices):
                f = self.files[file_index]
                try:
                    out = self.output_folder if self.use_custom else os.path.dirname(f)
                    wav = os.path.join(
                        out, os.path.splitext(os.path.basename(f))[0] + ".wav"
                    )

                    self.bridge.log.emit(f"[INPUT]  {os.path.abspath(f)}")

                    with open(f, "rb") as r:
                        data = r.read()

                    with wave.open(wav, "wb") as w:
                        w.setnchannels(1)
                        w.setsampwidth(2)
                        w.setframerate(44100)
                        w.writeframes(data)

                    self.bridge.log.emit(f"[OUTPUT] {os.path.abspath(wav)}")

                except Exception as e:
                    self.bridge.log.emit(f"[ERROR] {e}")

                self.bridge.progress.emit(progress_index + 1)
                self.bridge.status.emit(f"{progress_index+1}/{total}")

            self.bridge.log.emit("---- CONVERSION COMPLETE ----")
            self.bridge.status.emit("Done")

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())