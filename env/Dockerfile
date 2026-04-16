# Fallback dev image for an UNINITIALIZED workspace-harness.
# `harness bootstrap` regenerates this file from cli/src/harness/templates/Dockerfile.j2
# once harness.yml exists. Hand-edits inside HARNESS:KEEP blocks survive regeneration.

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

ARG HOST_UID=1000
ARG HOST_GID=1000

RUN apt-get update && apt-get install -y --no-install-recommends \
      git make curl jq ca-certificates build-essential sudo \
      python3 python3-pip python3-venv \
      && rm -rf /var/lib/apt/lists/*

# --- harness CLI ---
COPY cli/ /opt/harness-cli/
RUN pip install --break-system-packages /opt/harness-cli

# HARNESS:KEEP:BEGIN custom-tooling
# Add custom RUN/COPY steps here. They survive `harness bootstrap`.
# HARNESS:KEEP:END custom-tooling

# --- non-root user ---
RUN (userdel -r ubuntu 2>/dev/null || true) && \
    groupadd --non-unique --gid ${HOST_GID} harness && \
    useradd --non-unique --uid ${HOST_UID} --gid ${HOST_GID} \
            --shell /bin/bash --create-home harness && \
    echo 'harness ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/harness && \
    chmod 440 /etc/sudoers.d/harness

USER harness
WORKDIR /work
ENV PATH=/home/harness/.local/bin:$PATH
ENTRYPOINT ["bash", "-lc"]
CMD ["bash"]
