# raw2wav.py
# Companion app for fpvGoggleAudioRecorder to convert raw pcm files to wav files
# Compiling requires python 3, pillow, and PySide6
# Compile command (from raw2wav.py directory): pyinstaller --noconsole --onefile --add-data "background.png;." raw2wav.py
# Background image is 900x720 pixels

import sys
import os
import wave
import threading

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QPushButton,
    QFileDialog,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QListWidget,
    QProgressBar
)

from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, Signal, QObject


# -------------------------
# THREAD SAFE SIGNALS
# -------------------------

class Bridge(QObject):
    log = Signal(str)
    progress = Signal(int)
    status = Signal(str)


def resource_path(name):
    base = getattr(
        sys,
        "_MEIPASS",
        os.path.dirname(os.path.abspath(__file__))
    )
    return os.path.join(base, name)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "FPV Converter PRO"
        )

        self.setFixedSize(
            900,
            720
        )

        self.files = []

        self.use_custom = False
        self.output_folder = ""

        self.bridge = Bridge()

        self.bridge.log.connect(
            self.log_msg
        )

        self.bridge.progress.connect(
            self.progress_set
        )

        self.bridge.status.connect(
            self.status_set
        )

        self.init_ui()

    # -------------------------
    # UI
    # -------------------------

    def init_ui(self):

        self.bg = QLabel(self)

        pix = QPixmap(
            resource_path(
                "background.png"
            )
        )

        self.bg.setPixmap(pix)

        self.bg.setScaledContents(
            True
        )

        self.bg.setGeometry(
            0,
            0,
            900,
            720
        )

        self.bg.lower()

        container = QWidget(self)

        container.setGeometry(
            0,
            0,
            900,
            720
        )

        container.setAttribute(
            Qt.WA_TranslucentBackground
        )

        layout = QVBoxLayout(
            container
        )

        layout.setContentsMargins(
            15,
            15,
            15,
            15
        )

        layout.setSpacing(
            10
        )

        title = QLabel(
            "FPV RAW → WAV CONVERTER PRO"
        )

        title.setStyleSheet("""
            color:white;
            font-size:20px;
            font-weight:bold;
        """)

        layout.addWidget(
            title
        )

        # BUTTONS

        row = QHBoxLayout()

        self.btn_folder = QPushButton(
            "Folder"
        )

        self.btn_files = QPushButton(
            "Files"
        )

        self.btn_start = QPushButton(
            "START"
        )

        self.btn_start.setEnabled(
            False
        )

        self.default_style = """
        QPushButton {
            background: rgba(40,40,40,180);
            color:white;
            padding:8px;
            border-radius:6px;
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
            color:white;
            padding:8px;
            border-radius:6px;
            font-weight:bold;
        }

        QPushButton:hover {
            background: rgba(20,150,255,255);
        }
        """

        self.btn_folder.setStyleSheet(
            self.default_style
        )

        self.btn_files.setStyleSheet(
            self.default_style
        )

        self.btn_start.setStyleSheet(
            self.default_style
        )

        row.addWidget(
            self.btn_folder
        )

        row.addWidget(
            self.btn_files
        )

        row.addWidget(
            self.btn_start
        )

        layout.addLayout(
            row
        )

        # BODY

        body = QHBoxLayout()

        self.queue = QListWidget()

        self.queue.setStyleSheet("""
        QListWidget {
            background: rgba(0,0,0,140);
            color:white;
            border-radius:8px;
        }
        """)

        body.addWidget(
            self.queue,
            2
        )

        right = QVBoxLayout()

        input_row = QHBoxLayout()

        self.input_dot = QLabel(
            "●"
        )

        self.input_label = QLabel(
            "Input: None"
        )

        self.input_label.setStyleSheet("""
            color:red;
            font-size:11px;
            font-family:Consolas;
            font-weight:bold;
        """)

        input_row.addWidget(
            self.input_dot
        )

        input_row.addWidget(
            self.input_label
        )

        right.addLayout(
            input_row
        )

        self.custom_btn = QPushButton(
            "Use Custom Output Folder"
        )

        self.custom_btn.setCheckable(
            True
        )

        self.custom_btn.clicked.connect(
            self.pick_output_folder
        )

        right.addWidget(
            self.custom_btn
        )

        output_row = QHBoxLayout()

        self.output_dot = QLabel(
            "●"
        )

        self.path_label = QLabel(
            "Output: Default (same as input)"
        )
        
        self.path_label.setStyleSheet("""
            color:red;
            font-size:11px;
            font-family:Consolas;
                font-weight:bold;
            """
        )
        
        output_row.addWidget(
            self.output_dot
        )

        output_row.addWidget(
            self.path_label
        )

        right.addLayout(
            output_row
        )

        self.status = QLabel(
            "Idle"
        )

        self.status.setStyleSheet(
            "color:white;"
        )

        right.addWidget(
            self.status
        )

        self.progress = QProgressBar()

        self.progress.setFormat(
            "%p% (%v/%m)"
        )

        right.addWidget(
            self.progress
        )

        right.addStretch()

        body.addLayout(
            right,
            1
        )

        layout.addLayout(
            body
        )

        self.log = QTextEdit()

        self.log.setReadOnly(
            True
        )

        self.log.setStyleSheet("""
        QTextEdit {
            background: rgba(0,0,0,160);
            color:#00FF88;
            font-family:Consolas;
        }
        """)

        layout.addWidget(
            self.log
        )

        self.btn_folder.clicked.connect(
            self.select_folder
        )

        self.btn_files.clicked.connect(
            self.select_files
        )

        self.btn_start.clicked.connect(
            self.convert
        )

        self.update_states()

    # -------------------------

    def update_states(self):

        valid = bool(
            self.files
        )

        active = "#00FF88"
        inactive = "red"

        color = (
            active
            if valid
            else inactive
        )

        # STATUS DOTS

        self.input_dot.setStyleSheet(
            f"""
            color:{color};
            font-size:14px;
            """
        )

        self.output_dot.setStyleSheet(
            f"""
            color:{color};
            font-size:14px;
            """
        )

        # LABELS MATCH DOTS

        label_style = f"""
            color:{color};
            font-size:11px;
            font-family:Consolas;
            font-weight:bold;
        """

        self.input_label.setStyleSheet(
            label_style
        )

        self.path_label.setStyleSheet(
            label_style
        )

        # INPUT LABEL

        if valid:

            if len(
                self.files
            ) == 1:

                self.input_label.setText(
                    f"Input: {self.files[0]}"
                )

            else:

                self.input_label.setText(
                    f"Input: {len(self.files)} files selected"
                )

        else:

            self.input_label.setText(
                "Input: None"
            )

        # OUTPUT LABEL

        if (
            self.use_custom
            and self.output_folder
        ):

            self.path_label.setText(
                f"Output: {self.output_folder}"
            )

        else:

            self.path_label.setText(
                "Output: Default (same as input)"
            )

        # START BUTTON

        self.btn_start.setEnabled(
            valid
        )

        self.btn_start.setStyleSheet(
            self.start_style
            if valid
            else self.default_style
        )

    # -------------------------

    def pick_output_folder(self):

        folder = QFileDialog.getExistingDirectory(
            self
        )

        if folder:

            self.use_custom = True
            self.output_folder = folder

            self.path_label.setText(
                f"Output: {folder}"
            )

        else:

            self.use_custom = False
            self.output_folder = ""

            self.path_label.setText(
                "Output: Default (same as input)"
            )

    def log_msg(self, msg):
        self.log.append(msg)

    def progress_set(self, v):
        self.progress.setValue(v)

    def status_set(self, s):
        self.status.setText(s)

    def select_folder(self):

        folder = QFileDialog.getExistingDirectory(
            self
        )

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
            self,
            "Select RAW files",
            "",
            "RAW Files (*.raw)"
        )

        self.files = files

        self.refresh_queue()

        self.update_states()

    def refresh_queue(self):

        self.queue.clear()

        for f in self.files:

            self.queue.addItem(
                os.path.basename(f)
            )

    def convert(self):

        if not self.files:
            return

        def worker():

            total = len(
                self.files
            )

            self.progress.setMaximum(
                total
            )

            self.bridge.log.emit(
                "---- CONVERSION START ----"
            )

            for i, f in enumerate(
                self.files
            ):

                try:

                    out = (
                        self.output_folder
                        if self.use_custom
                        else os.path.dirname(f)
                    )

                    wav = os.path.join(
                        out,
                        os.path.splitext(
                            os.path.basename(f)
                        )[0] + ".wav"
                    )

                    self.bridge.log.emit(
                        f"[INPUT]  {os.path.abspath(f)}"
                    )

                    with open(
                        f,
                        "rb"
                    ) as r:

                        data = r.read()

                    with wave.open(
                        wav,
                        "wb"
                    ) as w:

                        w.setnchannels(1)
                        w.setsampwidth(2)
                        w.setframerate(
                            44100
                        )
                        w.writeframes(
                            data
                        )

                    self.bridge.log.emit(
                        f"[OUTPUT] {os.path.abspath(wav)}"
                    )

                except Exception as e:

                    self.bridge.log.emit(
                        f"[ERROR] {e}"
                    )

                self.bridge.progress.emit(
                    i + 1
                )

                self.bridge.status.emit(
                    f"{i+1}/{total}"
                )

            self.bridge.log.emit(
                "---- CONVERSION COMPLETE ----"
            )

            self.bridge.status.emit(
                "Done"
            )

        threading.Thread(
            target=worker,
            daemon=True
        ).start()


if __name__ == "__main__":

    app = QApplication(
        sys.argv
    )

    window = MainWindow()

    window.show()

    sys.exit(
        app.exec()
    )