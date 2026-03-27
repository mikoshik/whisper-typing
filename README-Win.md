# Запуск система 
Примеры запуска:
1. Полностью облачная версия (и Whisper, и Llama на Groq):

bash
python server.py --use-groq --llm-provider groq --groq-api-key="ВАШ_КЛЮЧ"
2. Гибридная версия (распознавание локально, обработка в облаке):

bash
python server.py --llm-provider groq --groq-api-key="ВАШ_КЛЮЧ"
3. Полностью локальная версия (Whisper локально, Llama через Ollama):

bash
python server.py --llm-provider ollama --llm-model "mistral"
4. Только распознавание без обработки текстом (самый быстрый вариант):

bash
python server.py --use-groq --llm-provider none
Нюанс: В 

client.py
 я уже реализовал логику, которая автоматически подхватывает formatted_text, если сервер его присылает, так что на стороне клиента ничего менять не нужно. Просто запустите сервер с нужными флагами.