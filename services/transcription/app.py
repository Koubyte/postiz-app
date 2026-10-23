"""Private CPU transcription: short recordings, no retention, no paid API."""
import asyncio
import hmac
import io
import os
import subprocess
import threading
import wave
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException,Request
from faster_whisper import WhisperModel

lock=threading.Lock()
model=None
@asynccontextmanager
async def lifespan(app):
    global model
    model=WhisperModel('small',device='cpu',compute_type='int8',cpu_threads=2,num_workers=1,download_root='/models',local_files_only=True)
    yield
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
@app.get('/health')
def health():return {'ready':model is not None}

def recognize(data):
    try:
        # Decode under a wall-clock and duration bound; no arbitrary URLs/files.
        decoded=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-protocol_whitelist','pipe','-i','pipe:0','-t','181','-vn','-ac','1','-ar','16000','-f','s16le','pipe:1'],input=data,capture_output=True,timeout=25)
        raw=decoded.stdout
        if decoded.returncode or not raw or len(raw)>180*16000*2:raise HTTPException(422,'Invalid recording or duration over 180 seconds.')
        wav=io.BytesIO()
        with wave.open(wav,'wb') as output:
            output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(raw)
        wav.seek(0)
        segments,info=model.transcribe(wav,language='fr',beam_size=3,vad_filter=True,condition_on_previous_text=False,initial_prompt='Planète Laser, instruments de musique, piano, guitare, Hailun, Pianova, Casio, Yamaha, Roland, Algam, sonorisation, éclairage.')
        text=' '.join(s.text.strip() for s in segments).strip()
        return {'text':text[:6000]}
    finally:lock.release()

@app.post('/transcribe')
async def transcribe(request:Request):
    expected=os.environ.get('TRANSCRIPTION_TOKEN','')
    if not expected or not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+expected):raise HTTPException(401)
    if not lock.acquire(blocking=False):raise HTTPException(429)
    handed_off=False
    try:
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>12*1024*1024:raise HTTPException(413)
        if not data:raise HTTPException(422)
        handed_off=True
        return await asyncio.to_thread(recognize,bytes(data))
    finally:
        if not handed_off:lock.release()
