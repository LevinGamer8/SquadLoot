FROM python:3.13-alpine
WORKDIR /app
COPY server.py dashboard.html ./
ENV PYTHONDONTWRITEBYTECODE=1 SQUAD_BIND=0.0.0.0 SQUAD_PORT=8765 SQUAD_DB=/data/squadloot.sqlite3
RUN mkdir -p /data && adduser -D -u 10001 squad && touch /data/.init && chown -R squad:squad /data
USER squad
EXPOSE 8765
CMD ["python", "-u", "server.py"]
