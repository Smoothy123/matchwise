FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models/huggingface \
    TOKENIZERS_PARALLELISM=false

WORKDIR /app

# CPU-only torch from PyTorch's own index. The default PyPI wheel for x86_64 Linux
# bundles about 2 GB of CUDA libraries that this app never uses.
ARG TORCH_VERSION=2.14.1
RUN pip install torch==${TORCH_VERSION} --index-url https://download.pytorch.org/whl/cpu

# Install dependencies before copying code, so code edits don't invalidate this layer.
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt -r requirements-dev.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "matchwise.api:app", "--host", "0.0.0.0", "--port", "8000"]
