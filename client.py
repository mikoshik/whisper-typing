#!/usr/bin/env python3
import threading
import time
import sounddevice as sd
import soundfile as sf
import sys
from pathlib import Path
from playsound import playsound
import pyperclip
import requests
import sounddevice as sd
import soundfile as sf
import keyboard  # Убедись, что сделал: uv add keyboard

# Optional tray icon imports
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

def play_wav_background(file_path):
    def play():
        try:
            data, fs = sf.read(file_path)
            sd.play(data, fs)
            sd.wait()  # Ждем окончания звука внутри отдельного потока
        except Exception as e:
            print(f"Ошибка звука: {e}")
            
    threading.Thread(target=play, daemon=True).start()


# Constants
SAMPLE_RATE = 16000
DEFAULT_SERVER_URL = "http://localhost:18031"
DEFAULT_OUTPUT_MODE = "direct_type"
ICON_SIZE = 64
ICON_CIRCLE_MARGIN = 8

class VoiceTypingClient:
    def __init__(
        self,
        server_url=DEFAULT_SERVER_URL,
        output_mode=DEFAULT_OUTPUT_MODE,
        enable_tray=False,
        use_ollama=False,
        ollama_model=None,
        ollama_prompt=None,
    ):
        self.is_recording = False
        self.recording_thread = None
        self.server_url = server_url
        self.sample_rate = SAMPLE_RATE
        self.running = True
        self.output_mode = output_mode
        self.enable_tray = enable_tray and TRAY_AVAILABLE
        self.tray_icon = None
        self.tray_thread = None

        self.use_ollama = use_ollama
        self.ollama_model = ollama_model
        self.ollama_prompt = ollama_prompt

    def start_recording(self):
        print("\n[ЗАПИСЬ ЗАПУЩЕНА] Говорите...")
        self.audio_data = []

        def callback(indata, frames, time, status):
            if status:
                print(status)
            self.audio_data.append(indata.copy())

        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=1, callback=callback):
                while self.is_recording and self.running:
                    time.sleep(0.1)
        except Exception as e:
            print(f"Ошибка аудио-устройства: {e}")
            self.is_recording = False

    def stop_recording_and_transcribe(self):
        print("[ОСТАНОВКА] Обработка аудио...")
        if hasattr(self, "audio_data") and self.audio_data:
            import numpy as np
            import io

            audio_array = np.concatenate(self.audio_data, axis=0)
            audio_buffer = io.BytesIO()
            sf.write(audio_buffer, audio_array, self.sample_rate, format="WAV") 
            audio_buffer.seek(0)
            self.transcribe_with_server(audio_buffer)
        else:
            print("Данные не записаны.")

    def transcribe_with_server(self, audio_buffer):
        try:
            files = {"file": ("audio.wav", audio_buffer, "audio/wav")}
            data = {
                "use_ollama": str(self.use_ollama).lower(),
                "ollama_model": self.ollama_model or "",
                "ollama_prompt": self.ollama_prompt or "",
            }
            response = requests.post(f"{self.server_url}/transcribe", files=files, data=data, timeout=60)

            if response.status_code == 200:
                result = response.json()
                text = result.get("formatted_text") or result.get("transcription", "")
                if text.strip():
                    print(f"Распознано: {text}")
                    self.output_text(text)
                else:
                    print("Речь не обнаружена.")
            else:
                print(f"Ошибка сервера: {response.status_code}")
        except Exception as e:
            print(f"Ошибка при связи с сервером: {e}")
        finally:
            if self.enable_tray: self.update_tray_icon()

    def output_text(self, text):
        cleaned_text = text.replace("\n", " ").replace("\r", " ").strip()
        if self.output_mode == "clipboard":
            pyperclip.copy(cleaned_text)
            print("Скопировано в буфер.")
        elif self.output_mode == "direct_type":
            # Используем keyboard.write для прямой печати в Windows
            keyboard.write(cleaned_text)
            print("Текст напечатан.")

    def toggle_recording(self):
            # Замени пути на свои актуальные!
            start_sound = r'C:\tools\whisper-typing\start.wav'
            stop_sound = r'C:\tools\whisper-typing\stop.wav'

            if not self.is_recording:
                play_wav_background(start_sound)
                self.is_recording = True
                self.recording_thread = threading.Thread(target=self.start_recording)
                self.recording_thread.daemon = True
                self.recording_thread.start()
            else:
                self.is_recording = False
                play_wav_background(stop_sound)
                if self.recording_thread:
                    self.recording_thread.join()
                self.stop_recording_and_transcribe()

    def create_icon(self, color):
        image = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (255, 255, 255, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse([ICON_CIRCLE_MARGIN, ICON_CIRCLE_MARGIN, ICON_SIZE-ICON_CIRCLE_MARGIN, ICON_SIZE-ICON_CIRCLE_MARGIN], fill=color)
        return image

    def update_tray_icon(self):
        if self.tray_icon:
            color = "red" if self.is_recording else "green"
            self.tray_icon.icon = self.create_icon(color)

    def setup_tray_icon(self):
        if not self.enable_tray: return
        menu = pystray.Menu(
            pystray.MenuItem("Вкл/Выкл запись", lambda: self.toggle_recording()),
            pystray.MenuItem("Выход", self.quit_application)
        )
        self.tray_icon = pystray.Icon("whisper-typing", self.create_icon("green"), menu=menu, title="Whisper Typing")
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def quit_application(self, icon=None, item=None):
        self.running = False
        if self.tray_icon: self.tray_icon.stop()
        sys.exit(0)

    def run(self):
        print(f"Клиент запущен. Сервер: {self.server_url}")
        print("ГОРЯЧАЯ КЛАВИША: F9")
        
        if self.enable_tray: self.setup_tray_icon()

        # Настройка горячей клавиши через библиотеку keyboard
        keyboard.add_hotkey('f9', self.toggle_recording)

        try:
            # Держим программу запущенной
            keyboard.wait()
        except KeyboardInterrupt:
            self.quit_application()

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    parser.add_argument("--output-mode", choices=["clipboard", "direct_type"], default="direct_type")
    parser.add_argument("--tray", action="store_true")
    args = parser.parse_args()

    client = VoiceTypingClient(
        server_url=args.server_url,
        output_mode=args.output_mode,
        enable_tray=args.tray
    )
    
    try:
        client.run()
    except Exception as e:
        print(f"Ошибка: {e}")
        return 1
    return 0

if __name__ == "__main__":
    main()