FROM python:3.12-slim-bookworm
WORKDIR /speech
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small',device='cpu',compute_type='int8',download_root='/models')"
RUN useradd -u 10002 -m speech
COPY app.py ./
USER speech
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1
EXPOSE 8789
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8789","--workers","1","--no-access-log"]
