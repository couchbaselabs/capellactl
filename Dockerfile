# Installs the wheel built by `make dist` (CAP-043 AC8): run `make dist` (or `make image`) first.
FROM python:3.12-slim
RUN useradd --create-home --uid 10001 capellactl
COPY dist/capellactl-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/capellactl-*.whl && rm /tmp/capellactl-*.whl \
    && pip uninstall -y -q pip setuptools wheel 2>/dev/null || true
USER 10001
WORKDIR /work
ENTRYPOINT ["capellactl"]
