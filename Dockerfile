FROM python:3.13-slim

WORKDIR /app
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt
COPY server ./server

ENV PORT=4000 DB_PATH=/data/liars_poker.db
VOLUME /data
EXPOSE 4000

# One process on purpose: all game state lives in this process (and is saved to
# DB_PATH), so do not run several workers behind a plain load balancer.
CMD ["sh", "-c", "uvicorn --factory server.app:create_app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --ws-ping-interval 20 --ws-ping-timeout 30"]
