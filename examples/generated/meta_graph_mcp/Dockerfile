# Container image for the meta_graph MCP server.
#
# stdio transport: the container must be started per client session with stdin and
# stdout attached, for example:
#
#   docker build -t meta_graph-mcp .
#   docker run --rm -i --env-file .env meta_graph-mcp
#
# An HTTP/SSE transport (one long-lived container serving many agents) is on the
# roadmap; when it lands, this image gains an exposed port and a health check.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY tools.json server.py ./
COPY mcp_runtime ./mcp_runtime

# Never bake credentials into the image; pass them per run with -e or --env-file.
RUN useradd --create-home --uid 10001 mcp
USER mcp

ENTRYPOINT ["python", "server.py"]
