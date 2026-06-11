import os
import sys
import wave
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


class RawToWavConverterGUI:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "FPV Goggle Audio Converter"
        )

        self.root.geometry(
            "900x720"
        )

        self.root.minsize(
            900,
            720
        )

        self.sample_rate = 44100
        self.channels = 1
        self.sample_width = 2

        self.load_background()
        self.build_ui()

    def resource(self, filename):

        if getattr(sys, "frozen", False):

            return os.path.join(
                sys._MEIPASS,
                filename
            )

        return os.path.join(
            os.path.dirname(
                os.path.abspath(
                    __file__
                )
            ),
            filename
        )

    def load_background(self):

        try:

            self.bg = tk.PhotoImage(
                file=self.resource(
                    "background.png"
                )
            )

            self.bg_label = tk.Label(
                self.root,
                image=self.bg,
                bd=0
            )

            self.bg_label.place(
                x=0,
                y=0,
                relwidth=1,
                relheight=1
            )

        except Exception as e:

            print(
                "Background error:",
                e
            )

    def build_ui(self):

        y = 20

        title = tk.Label(
            self.bg_label,
            text="FPV Goggle Audio RAW → WAV Converter",
            font=("Segoe UI", 18, "bold"),
            fg="white",
            bg="#222222"
        )

        title.place(
            x=20,
            y=y
        )

        y += 50

        self.btn_folder = ttk.Button(
            self.bg_label,
            text="Convert Folder",
            command=self.start_folder
        )

        self.btn_folder.place(
            x=20,
            y=y
        )

        self.btn_files = ttk.Button(
            self.bg_label,
            text="Convert Specific Files",
            command=self.start_files
        )

        self.btn_files.place(
            x=180,
            y=y
        )

        y += 55

        self.use_custom = tk.BooleanVar()

        self.chk = tk.Checkbutton(
            self.bg_label,
            text="Use custom output folder",
            variable=self.use_custom,
            command=self.toggle_output,
            bg="#222222",
            fg="white",
            selectcolor="#222222"
        )

        self.chk.place(
            x=20,
            y=y
        )

        y += 35

        self.output_path = tk.StringVar()

        self.entry = ttk.Entry(
            self.bg_label,
            textvariable=self.output_path,
            width=65,
            state="disabled"
        )

        self.entry.place(
            x=20,
            y=y
        )

        self.btn_browse = ttk.Button(
            self.bg_label,
            text="Browse",
            state="disabled",
            command=self.pick_output_folder
        )

        self.btn_browse.place(
            x=520,
            y=y
        )

        y += 60

        self.status = tk.Label(
            self.bg_label,
            text="Status: Idle",
            fg="white",
            bg="#222222"
        )

        self.status.place(
            x=20,
            y=y
        )

        y += 35

        self.progress = ttk.Progressbar(
            self.bg_label,
            length=760
        )

        self.progress.place(
            x=20,
            y=y
        )

        y += 50

        self.log = tk.Text(
            self.bg_label,
            bg="#111111",
            fg="#00FF88",
            insertbackground="white",
            font=("Consolas", 10)
        )

        self.log.place(
            x=20,
            y=y,
            width=840,
            height=300
        )

    def toggle_output(self):

        state = (
            "normal"
            if self.use_custom.get()
            else "disabled"
        )

        self.entry.config(
            state=state
        )

        self.btn_browse.config(
            state=state
        )

    def pick_output_folder(self):

        folder = filedialog.askdirectory()

        if folder:

            self.output_path.set(
                folder
            )

    def write_log(self, msg):

        self.log.insert(
            tk.END,
            msg + "\n"
        )

        self.log.see(
            tk.END
        )

    def start_folder(self):

        folder = filedialog.askdirectory()

        if not folder:
            return

        files = []

        for f in os.listdir(folder):

            if f.lower().endswith(".raw"):

                files.append(
                    os.path.join(
                        folder,
                        f
                    )
                )

        if not files:

            messagebox.showinfo(
                "None Found",
                "No RAW files found."
            )

            return

        threading.Thread(
            target=self.convert,
            args=(files,),
            daemon=True
        ).start()

    def start_files(self):

        files = filedialog.askopenfilenames(
            title="Select RAW files",
            filetypes=[
                (
                    "RAW Files",
                    "*.raw"
                )
            ]
        )

        if files:

            threading.Thread(
                target=self.convert,
                args=(list(files),),
                daemon=True
            ).start()

    def convert(self, files):

        self.progress["maximum"] = len(
            files
        )

        ok = 0

        for i, raw in enumerate(files):

            try:

                wav_name = (
                    os.path.splitext(
                        os.path.basename(
                            raw
                        )
                    )[0]
                    + ".wav"
                )

                if (
                    self.use_custom.get()
                    and self.output_path.get()
                ):

                    wav = os.path.join(
                        self.output_path.get(),
                        wav_name
                    )

                else:

                    wav = os.path.join(
                        os.path.dirname(
                            raw
                        ),
                        wav_name
                    )

                with open(
                    raw,
                    "rb"
                ) as r:

                    data = r.read()

                with wave.open(
                    wav,
                    "wb"
                ) as w:

                    w.setnchannels(
                        self.channels
                    )

                    w.setsampwidth(
                        self.sample_width
                    )

                    w.setframerate(
                        self.sample_rate
                    )

                    w.writeframes(
                        data
                    )

                ok += 1

                self.write_log(
                    "[OK] "
                    + wav_name
                )

            except Exception as e:

                self.write_log(
                    "[ERROR] "
                    + str(e)
                )

            self.progress["value"] = i + 1

            self.status.config(
                text=f"{i+1}/{len(files)}"
            )

            self.root.update_idletasks()

        self.status.config(
            text="Completed"
        )

        messagebox.showinfo(
            "Done",
            f"Converted {ok}/{len(files)} files"
        )


root = tk.Tk()

RawToWavConverterGUI(
    root
)

root.mainloop()