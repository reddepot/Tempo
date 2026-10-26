FROM python:3.13-alpine
RUN apk add --no-cache tzdata
WORKDIR /app
COPY tempo.py .
ENV TZ=Europe/Paris PYTHONUNBUFFERED=1 STATE_FILE=/data/state.json
VOLUME /data
CMD ["python", "tempo.py", "run"]
