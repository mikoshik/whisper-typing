import threading
import time
import os
import io
import sys
import requests
import sounddevice as sd
import soundfile as sf
import keyboard
import numpy as np
import pyperclip
import customtkinter as ctk
from PIL import Image, ImageDraw
import pystray
import tkinter as tk

# Библиотеки для управления звуком на Windows (pycaw)
from comtypes import CoInitialize, CoUninitialize
from pycaw.pycaw import AudioUtilities

# Константы
SAMPLE_RATE = 16000
SERVER_URL = os.environ.get("WHISPER_SERVER", "http://localhost:18031")
MIN_DURATION = 0.5

def play_wav_background(file_path: str):
    def _play():
        try:
            data, fs = sf.read(file_path)
            sd.play(data, fs)
            sd.wait()
        except: pass
    threading.Thread(target=_play, daemon=True).start()

class SystemAudio:
    """Управление системным звуком (mute/unmute) через упрощенный API pycaw."""
    @staticmethod
    def set_mute(mute=True):
        try:
            CoInitialize()
            # Используем встроенное свойство EndpointVolume у объекта устройства
            device = AudioUtilities.GetSpeakers()
            if device and hasattr(device, 'EndpointVolume'):
                volume = device.EndpointVolume
                volume.SetMute(1 if mute else 0, None)
            CoUninitialize()
        except Exception as e:
            print(f"Audio Control Error: {e}")

class ModernOverlay:
    """Современный HUD оверлей на базе customtkinter."""
    def __init__(self, on_restart_callback, on_quit_callback):
        self.root = None
        self.frame = None
        self.text_label = None
        self.menu = None
        self.on_restart = on_restart_callback
        self.on_quit = on_quit_callback
        self.status_colors = {
            'idle': ("#2ecc71", "#27ae60"),
            'recording': ("#e74c3c", "#c0392b"),
            'error': ("#95a5a6", "#7f8c8d")
        }

    def _setup(self):
        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-toolwindow", True)
        self.root.attributes("-alpha", 0.0) 
        
        w, h = 180, 50
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{sh - h - 100}")
        
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Перезагрузить", command=self.on_restart)
        self.menu.add_separator()
        self.menu.add_command(label="Выход", command=self.on_quit)

        self.root.bind("<Button-3>", self._show_context_menu)

        self.frame = ctk.CTkFrame(self.root, corner_radius=25, fg_color=self.status_colors['idle'][0])
        self.frame.pack(fill="both", expand=True)

        self.icon_label = ctk.CTkLabel(self.frame, text="🎙️", font=("Segoe UI Emoji", 22))
        self.icon_label.pack(side="left", padx=(15, 5))

        self.text_label = ctk.CTkLabel(self.frame, text="READY", font=("Inter", 13, "bold"), text_color="white")
        self.text_label.pack(side="left", padx=(5, 15))

    def _show_context_menu(self, event):
        if self.menu:
            self.menu.post(event.x_root, event.y_root)

    def update(self, status):
        if not self.root: return
        color = self.status_colors.get(status, self.status_colors['error'])[0]
        text = "RECORDING" if status == 'recording' else "READY" if status == 'idle' else "ERROR"
        
        self.frame.configure(fg_color=color)
        self.text_label.configure(text=text)
        
        if status == 'recording':
            self.root.attributes("-alpha", 1.0)
        else:
            def hide():
                if self.text_label and self.text_label.cget("text") != "RECORDING":
                    self.root.attributes("-alpha", 0.0)
            self.root.after(3000, hide)

    def run(self):
        self._setup()
        self.root.mainloop()

class VoiceTypingClient:
    def __init__(self):
        self.is_recording = False
        self.audio_data = []
        self.lock = threading.Lock()
        self.typing_lock = threading.Lock()
        self.overlay = ModernOverlay(on_restart_callback=self.restart, on_quit_callback=self.quit)
        self.tray_icon = None

    def _generate_tray_icon(self, color):
        img = Image.new("RGBA", (64, 64), (0,0,0,0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((4, 4, 60, 60), fill=color)
        draw.rectangle((24, 16, 40, 40), fill="white")
        draw.arc((20, 24, 44, 48), start=0, end=180, fill="white", width=4)
        return img

    def _record_loop(self):
        def callback(indata, frames, t, status):
            if self.is_recording:
                with self.lock: self.audio_data.append(indata.copy())
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=callback):
                while self.is_recording: time.sleep(0.05)
        except: 
            self._update_status('error')

    def _insert_text(self, text):
        if not text: return
        with self.typing_lock:
            try:
                old = pyperclip.paste()
                pyperclip.copy(text + " ")
                keyboard.press_and_release('ctrl+v')
                time.sleep(0.2)
                pyperclip.copy(old)
            except: keyboard.write(text + " ")

    def _process_audio(self, raw_chunks):
        if not raw_chunks: return
        audio_array = np.concatenate(raw_chunks, axis=0)
        buffer = io.BytesIO()
        sf.write(buffer, audio_array, SAMPLE_RATE, format="WAV")
        buffer.seek(0)
        try:
            r = requests.post(f"{SERVER_URL}/transcribe", files={"file": ("audio.wav", buffer)}, timeout=60)
            if r.status_code == 200:
                data = r.json()
                text = (data.get("formatted_text") or data.get("transcription") or "").strip()
                self._insert_text(text)
        except: self._update_status('error')

    def toggle(self):
        if not self.is_recording:
            # СТАРТ: 1. Выключаем звук
            SystemAudio.set_mute(True)
            time.sleep(0.5) 

            with self.lock: self.audio_data = []
            self.is_recording = True
            base_dir = os.path.dirname(__file__)
            play_wav_background(os.path.join(base_dir, "start.wav"))
            threading.Thread(target=self._record_loop, daemon=True).start()
            self._update_status('recording')
        else:
            # СТОП: Останавливаем и включаем звук
            self.is_recording = False
            SystemAudio.set_mute(False)

            base_dir = os.path.dirname(__file__)
            play_wav_background(os.path.join(base_dir, "stop.wav"))
            with self.lock:
                chunks = self.audio_data
                self.audio_data = []
            threading.Thread(target=self._process_audio, args=(chunks,), daemon=True).start()
            self._update_status('idle')

    def _update_status(self, status):
        if self.tray_icon:
            color = "#2ecc71" if status == 'idle' else "#e74c3c" if status == 'recording' else "#95a5a6"
            self.tray_icon.icon = self._generate_tray_icon(color)
        if self.overlay.root:
            self.overlay.root.after(0, self.overlay.update, status)

    def restart(self):
        SystemAudio.set_mute(False)
        if self.tray_icon: self.tray_icon.stop()
        os.execv(sys.executable, ['python'] + [os.path.abspath(__file__)] + sys.argv[1:])

    def quit(self):
        SystemAudio.set_mute(False)
        if self.tray_icon: self.tray_icon.stop()
        os._exit(0)

    def run(self):
        keyboard.add_hotkey('ctrl+alt+q', self.toggle)
        def run_tray():
            menu = pystray.Menu(
                pystray.MenuItem('Перезагрузить', self.restart),
                pystray.MenuItem('Выход', self.quit)
            )
            self.tray_icon = pystray.Icon('whisper-typing', self._generate_tray_icon("#2ecc71"), 'Whisper', menu)
            self.tray_icon.run()
        threading.Thread(target=run_tray, daemon=True).start()
        self.overlay.run()

if __name__ == "__main__":
    client = VoiceTypingClient()
    client.run()