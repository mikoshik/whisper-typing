Set WshShell = CreateObject("WScript.Shell")

' Указываем путь к твоей папке с проектом
strPath = "C:\tools\whisper-typing"
WshShell.CurrentDirectory = strPath

' 1. Запуск сервера (0 - скрыть окно, False - не ждать завершения)
' Используем uv run для запуска в облачном режиме (Whisper + Llama на Groq)
' Убедитесь, что переменная окружения GROQ_API_KEY установлена в системе 
' или замените команду на: "cmd /c uv run server.py --use-groq --llm-provider groq --groq-api-key=ВАШ_КЛЮЧ"
WshShell.Run "cmd /c uv run server.py --use-groq --llm-provider groq --llm-model openai/gpt-oss-20b --groq-api-key=API-key", 0, False


' 2. Пауза 2 секунды (в облачном режиме старт почти мгновенный, модель качать не надо)
WScript.Sleep 2000

' 3. Запуск клиента
' Запускаем клиент в скрытом режиме (0), оверлей сам появится когда нужно.
' Клиент по умолчанию использует оверлей и трей.
WshShell.Run "cmd /c uv run python client.py", 0, False