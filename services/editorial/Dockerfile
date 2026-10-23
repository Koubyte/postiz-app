FROM python:3.12-slim-bookworm
WORKDIR /studio
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 -m studio && mkdir /data && chown studio:studio /data
RUN mkdir /models && python -c "import urllib.request,hashlib,pathlib; b=urllib.request.urlopen('https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx',timeout=60).read(); assert len(b)==4574861 and hashlib.sha256(b).hexdigest()=='309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8'; pathlib.Path('/models/u2netp.onnx').write_bytes(b)"
COPY --chown=studio:studio *.py ./
COPY --chown=studio:studio static ./static
COPY --chown=studio:studio media-assets ./media-assets
USER studio
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 EDITORIAL_DATA=/data U2NET_HOME=/models
EXPOSE 8788
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8788", "--no-access-log", "--workers", "1"]
