Set WshShell = CreateObject("WScript.Shell")

' Указываем путь к твоей папке с проектом
strPath = "C:\tools\whisper-typing"
WshShell.CurrentDirectory = strPath

' 1. Запуск сервера (0 - скрыть окно, False - не ждать завершения)
' Используем uv run для запуска в контексте проекта
WshShell.Run "cmd /c uv run server.py", 0, False

' 2. Пауза 8 секунд (даем время серверу загрузить модель в видеокарту)
WScript.Sleep 8000

' 3. Запуск клиента (0 - скрыть окно)
WshShell.Run "cmd /c uv run client.py", 0, False