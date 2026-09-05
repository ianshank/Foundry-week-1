# A reproducible regression environment. NOT a way to run the MCP server.
#
# The server is launched *by VS Code over stdio* (runbook step 3.5): Agent
# Builder spawns the process and speaks JSON-RPC on its stdin/stdout. Putting
# it behind a container boundary breaks that registration flow, and the spike's
# whole premise is that it talks to a locally installed planlint and a local
# Ollama box. Containerising the server would be ceremony that makes the thing
# harder to run.
#
# What a container *is* good for here: proving the suite passes on the declared
# Python floor, with nothing else installed, on a machine that is not the
# author's. That is the claim CI makes, and this is how it is reproduced
# locally when CI and a laptop disagree.
#
#   make docker-test        # contract suite on the floor interpreter
#   make docker-test-full   # + the SDK, so the transport job runs too
#
# 3.10 on purpose: it is the floor declared in mcp_server/pyproject.toml. If
# the suite only passes on something newer, the floor is a lie and this image
# is where that shows up.
FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /spike

# Dependency layer first so edits to source do not re-resolve the world.
COPY mcp_server/pyproject.toml ./mcp_server/pyproject.toml
RUN python -m pip install --upgrade pip && python -m pip install pytest ruff mypy

# ---------------------------------------------------------------- contract
# The suite that must pass with no third-party dependency installed. Its whole
# value is that it needs nothing, so nothing is installed here.
FROM base AS contract
COPY . .
CMD ["python", "-m", "pytest", "-q"]

# --------------------------------------------------------------- transport
# The SDK is installed here and only here, so the two claims stay separable:
# "the verdict logic is correct" and "the server starts" are different facts
# and a single green tick should not be able to stand in for both.
FROM base AS transport
COPY . .
RUN python -m pip install -e "./mcp_server[dev]"
ENV REQUIRE_MCP=1
CMD ["python", "-m", "pytest", "-q"]

# ------------------------------------------------------------------- lint
FROM base AS lint
COPY . .
CMD ["sh", "-c", "ruff check . && mypy"]
