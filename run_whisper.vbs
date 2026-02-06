Set WshShell = CreateObject("WScript.Shell")

' Указываем путь к твоей папке с проектом
strPath = "C:\tools\whisper-typing"
WshShell.CurrentDirectory = strPath

' 1. Запуск сервера (0 - скрыть окно, False - не ждать завершения)
' Используем uv run для запуска в контексте проекта
WshShell.Run "cmd /c uv run server.py", 0, False

' 2. Пауза 8 секунд (даем время серверу загрузить модель в видеокарту)
WScript.Sleep 8000

' 3. Запуск клиента
' Чтобы иконка в системном трее нормально отобразилась, показываем окно клиента (1)
' и передаём аргумент --tray. Если нужен запуск без консоли, можно использовать
' альтернативу через pythonw (py -3w) — закомментированная строка ниже.
WshShell.Run "cmd /c uv run python client.py --tray", 1, False
' Альтернатива (без консоли, если установлен py launcher):
' WshShell.Run "py -3w -m uv run client.py -- --tray", 0, False