# Stage 1: Build — install dependencies in a throwaway layer
FROM python:3.12-slim AS builder

WORKDIR /build

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

RUN pip install --no-cache-dir --prefix=/install ".[smart]"

# Stage 2: Runtime — minimal final image
FROM python:3.12-slim

LABEL maintainer="Firefly.ai <opensource@firefly.ai>"
LABEL description="Generate Terraform providers from OpenAPI specs"
LABEL org.opencontainers.image.source="https://github.com/gofireflyio/api2tf"
LABEL org.opencontainers.image.licenses="MIT"

# Copy only the installed packages from builder
COPY --from=builder /install /usr/local

# Drop privileges — run as non-root
RUN groupadd --gid 1000 api2tf && \
    useradd --uid 1000 --gid api2tf --create-home api2tf

USER api2tf

WORKDIR /workspace

ENTRYPOINT ["api2tf"]
CMD ["--help"]
