FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1
ENV PYTHONIOENCODING=utf-8
ENV PYGAME_HIDE_SUPPORT_PROMPT=1
ENV SDL_AUDIODRIVER=dummy
ENV CUDA_HOME=/usr/local/cuda
ENV PATH="${CUDA_HOME}/bin:${PATH}"
ENV LD_LIBRARY_PATH="${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ffmpeg \
    fonts-wqy-microhei \
    git \
    libasound2 \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    libsm6 \
    libsndfile1 \
    libxext6 \
    libxrender1 \
    portaudio19-dev \
    python3-dev \
    python3-pip \
    python3.10 \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt .

RUN python3 -m pip install --no-cache-dir \
    torch==2.0.1+cu118 \
    torchvision==0.15.2+cu118 \
    --index-url https://download.pytorch.org/whl/cu118
RUN grep -v -E '^(torch|torchvision)==' requirements.txt > /tmp/requirements-docker.txt \
    && git config --global http.version HTTP/1.1 \
    && for attempt in 1 2 3; do \
        python3 -m pip install --no-cache-dir -r /tmp/requirements-docker.txt && break; \
        if [ "$attempt" = "3" ]; then exit 1; fi; \
        sleep 10; \
    done

COPY . .

RUN g++ -O3 -std=c++17 -Wall -Wextra \
    cpp_gateway/aiglass_cam_gateway.cpp \
    -o /usr/local/bin/aiglass_cam_gateway

RUN mkdir -p recordings model music voice static templates runtime_logs

EXPOSE 8765/tcp 22346/tcp 12345/udp 22345/udp 54321/udp

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f "http://localhost:${AIGLASS_PORT:-8765}/api/health" || exit 1

CMD ["python3", "-u", "app_main.py"]
