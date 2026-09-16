# Image for the generator itself: run it in CI or a pipeline to produce MCP servers.
#
#   docker build -t openapi-to-mcp .
#   docker run --rm -v "$PWD:/work" openapi-to-mcp \
#       generate --spec /work/examples/tickets-openapi.yaml --out /work/out/tickets --name tickets
#
# Generated projects get their own Dockerfile for running the server. That image
# is where a future streamable-HTTP transport will expose a port; the stdio
# transport used today needs stdin and stdout attached per client session
# (`docker run --rm -i ...`), not a published port.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

RUN useradd --create-home --uid 10001 generator
USER generator
WORKDIR /work

ENTRYPOINT ["openapi_to_mcp"]
CMD ["--help"]
