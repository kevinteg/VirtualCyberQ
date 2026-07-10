# SPDX-License-Identifier: BSD-3-Clause
# VirtualCyberQ container image.
#
# Build (from the repo root):
#     docker build -f docker/Dockerfile -t virtualcyberq .
# Run:
#     docker run --rm -p 8080:8080 -p 9000:9000 virtualcyberq --seed 42
#
# The device plane is exposed on 8080 (point your CyberQ client here) and the
# admin/control plane on 9000 (Swagger UI at /__admin/docs).

FROM python:3.12-slim AS build

# Build the wheel in an isolated stage so the runtime image stays lean.
WORKDIR /src
RUN pip install --no-cache-dir build
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
COPY docs/ ./docs/
RUN python -m build --wheel --outdir /dist


FROM python:3.12-slim AS runtime

# Non-buffered stdout so container logs stream promptly.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install the package from the wheel built above.
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 cyberq
USER cyberq
WORKDIR /home/cyberq

# Device plane / admin plane.
EXPOSE 8080 9000

# Bind on all interfaces so the ports are reachable from outside the container.
# Extra args (e.g. --seed 42 --scenario brisket_with_flaky_wifi --speed 600)
# are appended to this entrypoint.
ENTRYPOINT ["virtual-cyberq", "--host", "0.0.0.0", "--device-port", "8080", "--admin-port", "9000"]
CMD []
