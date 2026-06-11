import os
import sys
import wave
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading

class RawToWavConverterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("FPV Goggle Audio Converter")
        self.root.geometry("580x480")
        self.root.minsize(550, 420)
        
        # Audio specs configuration (matches RP2040 output)
        self.sample_rate = 44100
        self.channels = 1
        self.sample_width = 2 # 16-bit
        
        self.setup_ui()

    def setup_ui(self):
        # Main Layout Frame
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title / Description Header
        header_label = ttk.Label(
            main_frame, 
            text="FPV Goggle Audio RAW ➔ WAV Converter", 
            font=("Segoe UI", 14, "bold")
        )
        header_label.pack(anchor=tk.W, pady=(0, 2))
        
        sub_label = ttk.Label(
            main_frame, 
            text="Format Specs: Signed 16-bit Little Endian, 44100 Hz, Mono", 
            font=("Segoe UI", 9, "italic")
        )
        sub_label.pack(anchor=tk.W, pady=(0, 15))

        # Action Buttons Frame
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        self.btn_folder = ttk.Button(btn_frame, text="Convert Whole Folder", command=self.start_folder_conversion)
        self.btn_folder.pack(side=tk.LEFT, padx=(0, 10), ipady=2)

        self.btn_files = ttk.Button(btn_frame, text="Select Specific Files...", command=self.start_file_conversion)
        self.btn_files.pack(side=tk.LEFT, ipady=2)

        # Output Directory Configuration Frame
        out_frame = ttk.LabelFrame(main_frame, text=" Output Settings ", padding="10")
        out_frame.pack(fill=tk.X, pady=(5, 10))

        self.use_custom_out = tk.BooleanVar(value=False)
        self.chk_custom_out = ttk.Checkbutton(
            out_frame, 
            text="Choose a custom output directory (Otherwise keeps files in source folder)", 
            variable=self.use_custom_out,
            command=self.toggle_output_fields
        )
        self.chk_custom_out.pack(anchor=tk.W, pady=(0, 5))

        path_selection_frame = ttk.Frame(out_frame)
        path_selection_frame.pack(fill=tk.X)

        self.custom_path_var = tk.StringVar()
        self.entry_path = ttk.Entry(path_selection_frame, textvariable=self.custom_path_var, state=tk.DISABLED)
        self.entry_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        self.btn_browse_out = ttk.Button(path_selection_frame, text="Browse...", command=self.browse_output_directory, state=tk.DISABLED)
        self.btn_browse_out.pack(side=tk.RIGHT)

        # Progress Section
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=(5, 10))
        
        self.progress_label = ttk.Label(progress_frame, text="Status: Idle", font=("Segoe UI", 10))
        self.progress_label.pack(anchor=tk.W, pady=(0, 5))
        
        self.progress_bar = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill=tk.X)

        # Console / Log Window
        log_label = ttk.Label(main_frame, text="Conversion Log:", font=("Segoe UI", 9, "bold"))
        log_label.pack(anchor=tk.W, pady=(5, 2))

        self.log_text = tk.Text(main_frame, wrap=tk.WORD, height=8, state=tk.DISABLED, bg="#f8f9fa", font=("Consolas", 10))
        self.log_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        
        scrollbar = ttk.Scrollbar(main_frame, command=self.log_text.yview)
        scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.log_text.config(yscrollcommand=scrollbar.set)

    def toggle_output_fields(self):
        """Enables/Disables entry fields depending on checkbox state"""
        if self.use_custom_out.get():
            self.entry_path.config(state=tk.NORMAL)
            self.btn_browse_out.config(state=tk.NORMAL)
        else:
            self.entry_path.config(state=tk.DISABLED)
            self.btn_browse_out.config(state=tk.DISABLED)

    def browse_output_directory(self):
        folder = filedialog.askdirectory(title="Select Destination Folder for WAV Files")
        if folder:
            self.custom_path_var.set(os.path.normpath(folder))

    def log(self, message):
        """Thread-safe logging mechanism into the Text view component"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def set_ui_state(self, active):
        """Locks UI during intensive multi-threaded execution operations"""
        state = tk.NORMAL if active else tk.DISABLED
        self.btn_folder.config(state=state)
        self.btn_files.config(state=state)
        self.chk_custom_out.config(state=state)
        if active:
            self.toggle_output_fields()
        else:
            self.entry_path.config(state=tk.DISABLED)
            self.btn_browse_out.config(state=tk.DISABLED)

    def start_folder_conversion(self):
        folder_selected = filedialog.askdirectory(title="Select Directory Containing .raw Files")
        if not folder_selected:
            return
            
        raw_files = [os.path.join(folder_selected, f) for f in os.listdir(folder_selected) if f.lower().endswith('.raw')]
        
        if not raw_files:
            messagebox.showinfo("No Files Found", "There are no .raw audio files present inside the selected directory.")
            return
            
        threading.Thread(target=self.process_conversion_queue, args=(raw_files,), daemon=True).start()

    def start_file_conversion(self):
        files_selected = filedialog.askopenfilenames(
            title="Select .raw Files to Convert",
            filetypes=[("Raw Audio Files", "*.raw"), ("All Files", "*.*")]
        )
        if not files_selected:
            return
            
        threading.Thread(target=self.process_conversion_queue, args=(list(files_selected),), daemon=True).start()

    def process_conversion_queue(self, file_paths):
        self.set_ui_state(False)
        total_files = len(file_paths)
        self.progress_bar["maximum"] = total_files
        self.progress_bar["value"] = 0
        
        # Verify custom destination if checked
        dest_dir = None
        if self.use_custom_out.get():
            dest_dir = self.custom_path_var.get().strip()
            if not dest_dir or not os.path.isdir(dest_dir):
                self.log("[ABORTED] Custom destination directory invalid or missing.")
                self.set_ui_state(True)
                messagebox.showerror("Error", "The specified custom output directory does not exist.")
                return

        self.log(f"--- Starting Processing Queue: Found {total_files} file(s) ---")
        if dest_dir:
            self.log(f"Destination folder: {dest_dir}")
        
        success_count = 0
        for idx, raw_path in enumerate(file_paths, start=1):
            filename = os.path.basename(raw_path)
            wav_filename = os.path.splitext(filename)[0] + ".wav"
            
            # Decide layout positioning directory path
            output_folder = dest_dir if dest_dir else os.path.dirname(raw_path)
            wav_path = os.path.join(output_folder, wav_filename)
            
            self.progress_label.config(text=f"Processing {idx}/{total_files}: {filename}")
            self.log(f"Converting: {filename} ➔ {wav_filename}")
            self.root.update_idletasks()
            
            try:
                with open(raw_path, "rb") as raw_file:
                    raw_data = raw_file.read()

                with wave.open(wav_path, "wb") as wav_file:
                    wav_file.setnchannels(self.channels)
                    wav_file.setsampwidth(self.sample_width)
                    wav_file.setframerate(self.sample_rate)
                    wav_file.writeframes(raw_data)
                    
                self.log(f"   ↳ [OK] Created target file.")
                success_count += 1
            except Exception as e:
                self.log(f"   ↳ [ERROR] Failed to compile {filename}: {str(e)}")
                
            self.progress_bar["value"] = idx
            
        self.progress_label.config(text="Status: Completed")
        self.log(f"\n--- Batch Process Finished! Successfully converted ({success_count}/{total_files}) items. ---\n")
        self.set_ui_state(True)
        messagebox.showinfo("Batch Process Complete", f"Successfully structured {success_count} audio tracks into production WAV format.")

if __name__ == "__main__":
    root = tk.Tk()
    app = RawToWavConverterGUI(root)
    root.mainloop()