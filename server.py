#!/usr/bin/env python3
import argparse
import io
import sys
from typing import Optional
import httpx
import uvicorn
from fastapi import FastAPI, Form, HTTPException, UploadFile
from openai import AsyncOpenAI
import os

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Whisper Typing Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the server to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=18031, help="Port to bind the server to (default: 18031)")
    
    # Transcription Settings
    parser.add_argument("--use-groq", action="store_true", help="Use Groq API instead of local Whisper model")
    parser.add_argument("--groq-api-key", default=os.environ.get("GROQ_API_KEY", ""), help="Groq API Key (or set GROQ_API_KEY env var)")
    
    # LLM Settings
    parser.add_argument("--llm-provider", choices=["ollama", "groq", "none"], default="none", help="LLM provider for text processing (default: none)")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama API base URL")
    parser.add_argument("--llm-model", help="Model name for processing (e.g. llama-3.1-8b-instant for groq, mistral for ollama)")
    parser.add_argument("--llm-prompt", default="Тебе придет текст распознанный из аудио. Твоя задача — исправить пунктуацию и грамматические ошибки, сделав текст читаемым, но сохранив смысл и стиль. Верни ТОЛЬКО исправленный текст без своих комментариев.", help="System prompt for LLM")

    # Use parse_known_args to avoid errors if uvicorn passes extra args
    args, _ = parser.parse_known_args()
    return args

server_args = parse_args()

# Global configuration
USE_GROQ_WHISPER = server_args.use_groq
GROQ_API_KEY = server_args.groq_api_key
LLM_PROVIDER = server_args.llm_provider
OLLAMA_BASE_URL = server_args.ollama_url
LLM_MODEL = server_args.llm_model
LLM_PROMPT = server_args.llm_prompt

# Set default model if not provided
if LLM_PROVIDER == "groq" and not LLM_MODEL:
    LLM_MODEL = "llama-3.1-8b-instant"
elif LLM_PROVIDER == "ollama" and not LLM_MODEL:
    LLM_MODEL = "mistral"

# Load CUDA paths for local Whisper Model
if not USE_GROQ_WHISPER:
    venv_path = os.path.join(os.getcwd(), ".venv", "Lib", "site-packages")
    nvidia_paths = [
        os.path.join(venv_path, "nvidia", "cudnn", "bin"),
        os.path.join(venv_path, "nvidia", "cublas", "bin")
    ]
    for path in nvidia_paths:
        if os.path.exists(path):
            os.add_dll_directory(path)
            os.environ["PATH"] = path + os.pathsep + os.environ["PATH"]
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        pass

app = FastAPI()

# Initialize local model on startup if needed
model = None
if not USE_GROQ_WHISPER:
    model = WhisperModel("small", device="cuda", compute_type="int8_float16")

async def process_text_llm(text: str) -> str:
    """Process text using configured LLM provider"""
    if LLM_PROVIDER == "none" or not text:
        return text

    try:
        if LLM_PROVIDER == "ollama":
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={"model": LLM_MODEL, "prompt": f"{LLM_PROMPT}\n\n{text}", "stream": False},
                )
                if response.status_code == 200:
                    return response.json().get("response", text)
                
        elif LLM_PROVIDER == "groq":
            if not GROQ_API_KEY:
                print("Error: Groq API Key missing for LLM")
                return text
            
            client = AsyncOpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": LLM_PROMPT},
                    {"role": "user", "content": text}
                ]
            )
            return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"LLM processing error ({LLM_PROVIDER}): {e}")
    
    return text

@app.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = Form(...),
):
    """Transcribe uploaded audio file to text with optional LLM processing"""
    try:
        file_content = await file.read()
        transcription = ""

        if USE_GROQ_WHISPER:
            if not GROQ_API_KEY:
                raise HTTPException(status_code=500, detail="Groq API Key is not set.")
            
            client = AsyncOpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
            response = await client.audio.transcriptions.create(
                file=(file.filename, file_content),
                model="whisper-large-v3",
                response_format="json"
            )
            transcription = response.text.strip()
        else:
            file_stream = io.BytesIO(file_content)
            segments, info = model.transcribe(
                audio=file_stream,
                beam_size=5,
                initial_prompt="Hello, this is a technical conversation about device, software, coding, and development in Russian and English.",
                vad_filter=True,
                without_timestamps=True,
            )
            transcription = "".join([s.text for s in segments]).strip()

        # Always try to process with LLM if a provider is set
        formatted_text = await process_text_llm(transcription)
        
        if formatted_text != transcription:
            return {"transcription": transcription, "formatted_text": formatted_text}
        return {"transcription": transcription}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    print(f"Starting Whisper Typing Server on {server_args.host}:{server_args.port}")
    print(f"Whisper Mode: {'Groq Cloud' if USE_GROQ_WHISPER else 'Local Faster-Whisper'}")
    print(f"LLM Provider: {LLM_PROVIDER} ({LLM_MODEL if LLM_PROVIDER != 'none' else 'N/A'})")

    uvicorn.run(app, host=server_args.host, port=server_args.port)
