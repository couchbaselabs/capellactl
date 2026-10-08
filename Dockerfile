FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml ./
COPY capellactl ./capellactl
COPY README.md LICENSE NOTICE ./
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 capellactl
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl \
    && pip uninstall -y -q pip setuptools wheel 2>/dev/null || true
USER 10001
WORKDIR /work
ENTRYPOINT ["capellactl"]
