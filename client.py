import threading
import time
import os
import io
import requests
import sounddevice as sd
import soundfile as sf
import keyboard
import numpy as np

# Новые зависимости для иконки в трее
from PIL import Image, ImageDraw
import pystray

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


def _create_circle_icon(color, size=64, radius=None):
    """Create a small circular RGBA icon for the tray."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if radius is None:
        radius = int(size * 0.4)
    cx = cy = size // 2
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
    return img


class VoiceTypingClient:
    def __init__(self):
        self.is_recording = False
        self.audio_data = []
        self.lock = threading.Lock()
        self.recording_thread = None

        # Используем только прямой ввод текста через keyboard.write — как раньше

        # typing lock to prevent overlapping concurrent typing
        self.typing_lock = threading.Lock()

        # Tray-related members
        self.tray_icon = None
        # Prepare icons now (PIL Image objects)
        self._green_icon = _create_circle_icon((0, 200, 0, 255), size=64)
        self._red_icon = _create_circle_icon((200, 0, 0, 255), size=64)
        self._gray_icon = _create_circle_icon((120, 120, 120, 255), size=64)

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
            # Обновляем трей в случае ошибки
            try:
                self._set_tray_status('stopped')
            except Exception:
                pass

    # Раньше были фоллбеки через буфер и сложные бэкенды — убраны. Всегда прямой набор.

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

                    # Всегда прямой ввод через keyboard.write — минимальный и стабильный режим
                    with self.typing_lock:
                        try:
                            keyboard.write(text + " ", delay=0.02)
                        except Exception as e:
                            print(f"Ошибка ввода текста: {e}")
        except Exception as e:
            print(f"Ошибка сервера: {e}")
            try:
                self._set_tray_status('stopped')
            except Exception:
                pass

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
            # Обновляем иконку в трее
            try:
                self._set_tray_status('recording')
            except Exception:
                pass
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
            # Обновляем иконку в трее
            try:
                self._set_tray_status('idle')
            except Exception:
                pass

    def run(self, tray=False):
        print(f"Запущено. Порт: {SERVER_URL}. Кнопка: F9")
        if tray:
            # Запускаем обработку горячих клавиш в фоне, чтобы основным потоком занимался трэй
            threading.Thread(target=self._keyboard_loop, daemon=True).start()
            # На Windows трэй работает надёжнее, если message loop запущен в основном потоке
            try:
                self._start_tray_blocking()
            except Exception as e:
                print(f"Не удалось запустить трэй в основном потоке: {e}. Пытаюсь запустить в фоне")
                try:
                    self._start_tray()
                except Exception as e2:
                    print(f"Fallback трэя провалился: {e2}")
        else:
            keyboard.add_hotkey('f9', self.toggle)
            keyboard.wait()

    def _keyboard_loop(self):
        """Helper: регистрирует горячую клавишу и блокирует поток на keyboard.wait()."""
        keyboard.add_hotkey('f9', self.toggle)
        keyboard.wait()

    # ---- Трей: реализация ----
    def _start_tray(self):
        """Создать и запустить иконку в системном трее (в фоне)."""
        if self.tray_icon:
            return

        # меню
        menu = pystray.Menu(
            pystray.MenuItem('Toggle Recording', self._on_tray_toggle),
            pystray.MenuItem('Quit', self._on_tray_quit),
        )

        icon = pystray.Icon('whisper-typing', self._green_icon, 'Whisper Typing (Idle)', menu)
        self.tray_icon = icon

        # Попытка запустить detached backend (если поддерживается), иначе в фоне
        try:
            icon.run_detached()
        except Exception as e:
            # Показываем ошибку для отладки
            print(f"run_detached failed: {e}; запускаю icon.run() в фоне")
            try:
                threading.Thread(target=icon.run, daemon=True).start()
            except Exception as e2:
                print(f"Запуск icon.run() в фоне провалился: {e2}")

    def _start_tray_blocking(self):
        """Создать и запустить иконку в системном трее (blocking, должен быть вызван в основном потоке)."""
        if self.tray_icon:
            return

        menu = pystray.Menu(
            pystray.MenuItem('Toggle Recording', self._on_tray_toggle),
            pystray.MenuItem('Quit', self._on_tray_quit),
        )

        icon = pystray.Icon('whisper-typing', self._green_icon, 'Whisper Typing (Idle)', menu)
        self.tray_icon = icon

        # Установим начальное состояние
        try:
            self._set_tray_status('idle')
        except Exception:
            pass

        try:
            icon.run()
        except Exception as e:
            print(f"Запуск трэя в основном потоке провалился: {e}")

    def _set_tray_status(self, status):
        """Обновить иконку и подсказку в трее в зависимости от статуса."""
        if not self.tray_icon:
            return

        if status == 'recording':
            self.tray_icon.icon = self._red_icon
            self.tray_icon.title = "Whisper Typing (Recording)"
        elif status == 'idle':
            self.tray_icon.icon = self._green_icon
            self.tray_icon.title = "Whisper Typing (Idle)"
        else:
            self.tray_icon.icon = self._gray_icon
            self.tray_icon.title = "Whisper Typing (Stopped/Error)"

    def _on_tray_toggle(self, icon, item):
        # Вызывается в потоке трея
        self.toggle()

    def _on_tray_quit(self, icon, item):
        # Попытка корректно завершить работу и убрать иконку
        try:
            self.is_recording = False
        except Exception:
            pass
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        try:
            icon.stop()
        except Exception:
            pass
        os._exit(0)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Whisper Typing Client")
    parser.add_argument('--tray', action='store_true', help='Enable system tray icon')
    args = parser.parse_args()

    client = VoiceTypingClient()
    client.run(tray=args.tray)