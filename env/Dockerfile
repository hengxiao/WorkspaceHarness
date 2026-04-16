# Fallback dev image for an UNINITIALIZED workspace-harness.
# `harness bootstrap` regenerates this file from cli/src/harness/templates/Dockerfile.j2
# once harness.yml exists. Hand-edits inside HARNESS:KEEP blocks survive regeneration.

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      git make curl jq ca-certificates build-essential \
      python3 python3-pip python3-venv \
      && rm -rf /var/lib/apt/lists/*

# --- harness CLI ---
COPY cli/ /opt/harness-cli/
RUN pip install --break-system-packages /opt/harness-cli

# HARNESS:KEEP:BEGIN custom-tooling
# Add custom RUN/COPY steps here. They survive `harness bootstrap`.
# HARNESS:KEEP:END custom-tooling

WORKDIR /work
ENTRYPOINT ["bash", "-lc"]
CMD ["bash"]
