FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app


EXPOSE 7860

ENV PYTHONUNBUFFERED=1

# # Download all required fonts
# ADD "https://github.com/satbyy/go-noto-universal/releases/download/v7.0/GoNotoKurrent-Regular.ttf" /app/
# ADD "https://github.com/timelic/source-han-serif/releases/download/main/SourceHanSerifCN-Regular.ttf" /app/
# ADD "https://github.com/timelic/source-han-serif/releases/download/main/SourceHanSerifTW-Regular.ttf" /app/
# ADD "https://github.com/timelic/source-han-serif/releases/download/main/SourceHanSerifJP-Regular.ttf" /app/
# ADD "https://github.com/timelic/source-han-serif/releases/download/main/SourceHanSerifKR-Regular.ttf" /app/

RUN apt-get update && \
     apt-get install --no-install-recommends -y libgl1 libglib2.0-0 libxext6 libsm6 libxrender1 build-essential git && \
     rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN uv pip install --system --no-cache -r pyproject.toml

COPY . .

# BABELDOC_REF is one full lowercase commit. Reject other values before install.
ARG BABELDOC_REF
RUN if ! printf '%s' "$BABELDOC_REF" | grep -Eq '^[0-9a-f]{40}$'; then \
      echo "BABELDOC_REF must match ^[0-9a-f]{40}$" >&2; \
      exit 1; \
    fi

RUN uv pip install --system --no-cache . && uv pip install --system --no-cache --compile-bytecode -U "babeldoc @ git+https://github.com/TopCircle/BabelDOC.git@${BABELDOC_REF}" "pymupdf>=1.26.7,<2" && babeldoc --version && babeldoc --warmup
RUN pdf2zh --version
CMD ["pdf2zh", "--gui"]
