import threading
import time
import os
import io
import requests
import sounddevice as sd
import soundfile as sf
import keyboard
import numpy as np

# Константы
SAMPLE_RATE = 16000
SERVER_URL = os.environ.get("WHISPER_SERVER", "http://localhost:18031")
MIN_DURATION = 0.7  # Минимальная длина записи


def play_wav_background(file_path: str):
    """Фоновый звук без блокировки."""
    def _play():
        try:
            data, fs = sf.read(file_path)
            sd.play(data, fs)
            sd.wait()
        except:
            pass
    threading.Thread(target=_play, daemon=True).start()


class VoiceTypingClient:
    def __init__(self):
        self.is_recording = False
        self.audio_data = []
        self.lock = threading.Lock()
        self.recording_thread = None

    def _record_loop(self):
        """Внутренний цикл записи."""
        def callback(indata, frames, t, status):
            if self.is_recording:
                with self.lock:
                    self.audio_data.append(indata.copy())

        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=callback):
                while self.is_recording:
                    time.sleep(0.05)
        except Exception as e:
            print(f"Микрофон: {e}")
            self.is_recording = False

    def _process_audio(self, raw_chunks):
        """Отправка захваченного куска данных на сервер."""
        if not raw_chunks:
            return

        audio_array = np.concatenate(raw_chunks, axis=0)
        duration = len(audio_array) / SAMPLE_RATE

        if duration < MIN_DURATION:
            return

        # WAV в памяти
        buffer = io.BytesIO()
        sf.write(buffer, audio_array, SAMPLE_RATE, format="WAV")
        buffer.seek(0)

        try:
            files = {"file": ("audio.wav", buffer, "audio/wav")}
            r = requests.post(f"{SERVER_URL}/transcribe", files=files)
            if r.status_code == 200:
                data = r.json()
                # Берем любой текст, который пришел
                text = (data.get("formatted_text") or data.get("transcription") or "").strip()
                if text:
                    print(f">> {text}")
                    keyboard.write(text + " ")
        except Exception as e:
            print(f"Ошибка сервера: {e}")

    def toggle(self):
        base_dir = os.path.dirname(__file__)
        
        if not self.is_recording:
            # СТАРТ
            with self.lock:
                self.audio_data = []  # Гарантированная очистка перед началом
            
            self.is_recording = True
            play_wav_background(os.path.join(base_dir, "start.wav"))
            
            self.recording_thread = threading.Thread(target=self._record_loop, daemon=True)
            self.recording_thread.start()
            print("Слушаю...")
        else:
            # СТОП
            self.is_recording = False
            play_wav_background(os.path.join(base_dir, "stop.wav"))
            
            # ИЗОЛЯЦИЯ: Забираем данные под замком и сразу обнуляем буфер
            with self.lock:
                captured_chunks = self.audio_data
                self.audio_data = [] 

            # Обработка того, что успели забрать
            threading.Thread(target=self._process_audio, args=(captured_chunks,), daemon=True).start()

    def run(self):
        print(f"Запущено. Порт: {SERVER_URL}. Кнопка: F9")
        keyboard.add_hotkey('f9', self.toggle)
        keyboard.wait()


if __name__ == "__main__":
    client = VoiceTypingClient()
    client.run()