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
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama API base URL (default: http://localhost:11434)")
    parser.add_argument("--use-groq", action="store_true", help="Use Groq API instead of local Whisper model")
    parser.add_argument("--groq-api-key", default=os.environ.get("GROQ_API_KEY", ""), help="Groq API Key (or set GROQ_API_KEY env var)")
    
    # Use parse_known_args to avoid errors if uvicorn passes extra args
    args, _ = parser.parse_known_args()
    return args

server_args = parse_args()

# Global configuration
OLLAMA_BASE_URL = server_args.ollama_url
USE_GROQ = server_args.use_groq
GROQ_API_KEY = server_args.groq_api_key

# Load CUDA paths for local Whisper Model
if not USE_GROQ:
    # Добавляем пути к библиотекам NVIDIA в окружение Windows
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

# Initialize model on startup conditionally
model = None
if not USE_GROQ:
    model = WhisperModel("small", device="cuda", compute_type="int8_float16")


async def format_with_ollama(text: str, model_name: str, prompt: str) -> str:
    """Format text using Ollama API"""
    try:
        full_prompt = f"{prompt}\n\n{text}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={"model": model_name, "prompt": full_prompt, "stream": False},
            )

            if response.status_code == 200:
                result = response.json()
                return result.get("response", text)
            else:
                print(f"Ollama API error: {response.status_code}")
                return text

    except Exception as e:
        print(f"Ollama formatting error: {e}")
        return text


@app.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = Form(...),
    use_ollama: bool = Form(False),
    ollama_model: Optional[str] = Form(None),
    ollama_prompt: Optional[str] = Form(None),
):
    """Transcribe uploaded audio file to text with optional Ollama formatting"""
    try:
        # Read uploaded file content
        file_content = await file.read()
        transcription = ""

        if USE_GROQ:
            if not GROQ_API_KEY:
                raise HTTPException(status_code=500, detail="Groq API Key is not set. Pass --groq-api-key or set GROQ_API_KEY.")
            
            client = AsyncOpenAI(
                api_key=GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
            )
            
            try:
                response = await client.audio.transcriptions.create(
                    file=(file.filename, file_content),
                    model="whisper-large-v3",
                    response_format="json"
                )
                transcription = response.text.strip()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Groq API error: {str(e)}")
        else:
            file_stream = io.BytesIO(file_content)

            # Transcribe audio using local model
            segments, info = model.transcribe(
                audio=file_stream,
                beam_size=5,
                initial_prompt="Hello, this is a technical conversation about device, software, coding, and development in Russian and English.",
                vad_filter=True,
                without_timestamps=True,
                condition_on_previous_text=False,
            )

            # Combine segments into single text
            result_text = ""
            for segment in segments:
                result_text += segment.text

            transcription = result_text.strip()

        # Format with Ollama if requested
        if use_ollama and ollama_model and ollama_prompt and transcription:
            formatted_text = await format_with_ollama(
                transcription, ollama_model, ollama_prompt
            )
            return {"transcription": transcription, "formatted_text": formatted_text}

        return {"transcription": transcription}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    print(f"Starting Whisper Typing Server on {server_args.host}:{server_args.port}")
    print(f"Ollama URL: {OLLAMA_BASE_URL}")
    print(f"Using Groq: {USE_GROQ}")

    uvicorn.run(app, host=server_args.host, port=server_args.port)
