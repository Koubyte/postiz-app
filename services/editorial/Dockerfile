FROM python:3.12-slim-bookworm
WORKDIR /studio
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 -m studio && mkdir /data && chown studio:studio /data
COPY --chown=studio:studio *.py ./
COPY --chown=studio:studio static ./static
COPY --chown=studio:studio media-assets ./media-assets
USER studio
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 EDITORIAL_DATA=/data
EXPOSE 8788
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8788", "--no-access-log", "--workers", "1"]
