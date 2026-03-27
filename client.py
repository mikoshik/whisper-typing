import threading
import time
import os
import io
import requests
import sounddevice as sd
import soundfile as sf
import keyboard
import numpy as np
import pyperclip
import customtkinter as ctk
from PIL import Image, ImageDraw
import pystray

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

class ModernOverlay:
    """Современный HUD оверлей на базе customtkinter."""
    def __init__(self):
        self.root = None
        self.label = None
        self.status_colors = {
            'idle': ("#2ecc71", "#27ae60"),      # Зеленый
            'recording': ("#e74c3c", "#c0392b"), # Красный
            'error': ("#95a5a6", "#7f8c8d")      # Серый
        }

    def _setup(self):
        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.0) # Начинаем невидимыми
        
        # Размеры и позиция (внизу по центру)
        w, h = 160, 45
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{sh - h - 100}")
        
        # Прозрачный фон окна (Windows-specific trick if needed, but CTk handles bg well)
        self.root.wm_attributes("-transparentcolor", self.root._apply_appearance_mode(self.root.cget("fg_color")))

        # "Пилюля" с иконкой и текстом
        self.frame = ctk.CTkFrame(self.root, corner_radius=20, fg_color=self.status_colors['idle'][0])
        self.frame.pack(fill="both", expand=True)

        # Используем Unicode символ микрофона (Segoe UI Emoji)
        self.icon_label = ctk.CTkLabel(self.frame, text="🎙️", font=("Segoe UI Emoji", 20))
        self.icon_label.pack(side="left", padx=(15, 5))

        self.text_label = ctk.CTkLabel(self.frame, text="READY", font=("Inter", 12, "bold"), text_color="white")
        self.text_label.pack(side="left", padx=(5, 15))

    def update(self, status):
        if not self.root: return
        
        color = self.status_colors.get(status, self.status_colors['error'])[0]
        text = "RECORDING" if status == 'recording' else "READY" if status == 'idle' else "ERROR"
        
        # Анимация появления/скрытия или просто смена цвета
        self.frame.configure(fg_color=color)
        self.text_label.configure(text=text)
        
        if status == 'recording':
            self.root.attributes("-alpha", 1.0)
        else:
            # Скрываем через 2 секунды если idle
            def hide():
                if self.text_label.cget("text") != "RECORDING":
                    self.root.attributes("-alpha", 0.0)
            self.root.after(2000, hide)

    def run(self):
        self._setup()
        self.root.mainloop()

class VoiceTypingClient:
    def __init__(self):
        self.is_recording = False
        self.audio_data = []
        self.lock = threading.Lock()
        self.typing_lock = threading.Lock()
        self.overlay = ModernOverlay()
        self.tray_icon = None

    def _generate_tray_icon(self, color):
        """Генерирует иконку на лету без внешних файлов."""
        img = Image.new("RGBA", (64, 64), (0,0,0,0))
        draw = ImageDraw.Draw(img)
        # Рисуем красивый кружочек
        draw.ellipse((4, 4, 60, 60), fill=color)
        # И схематичный микрофон внутри
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
        except Exception as e:
            print(f"Mic error: {e}")
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
                text = (r.json().get("formatted_text") or r.json().get("transcription") or "").strip()
                self._insert_text(text)
        except: self._update_status('error')

    def toggle(self):
        if not self.is_recording:
            with self.lock: self.audio_data = []
            self.is_recording = True
            base_dir = os.path.dirname(__file__)
            play_wav_background(os.path.join(base_dir, "start.wav"))
            threading.Thread(target=self._record_loop, daemon=True).start()
            self._update_status('recording')
        else:
            self.is_recording = False
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

    def run(self):
        keyboard.add_hotkey('ctrl+alt+q', self.toggle)
        
        def run_tray():
            self.tray_icon = pystray.Icon('whisper-typing', self._generate_tray_icon("#2ecc71"), 'Whisper')
            self.tray_icon.run()

        threading.Thread(target=run_tray, daemon=True).start()
        print("Running with modern HUD. Ctrl+Alt+Q to toggle.")
        self.overlay.run()

if __name__ == "__main__":
    client = VoiceTypingClient()
    client.run()