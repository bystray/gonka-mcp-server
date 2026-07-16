FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bind all interfaces inside the container so the EXPOSE'd port is actually
# reachable — server.py defaults to 127.0.0.1 (correct for the production
# systemd+nginx deployment, wrong for a standalone container).
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8643

EXPOSE 8643

CMD ["python", "server.py"]
