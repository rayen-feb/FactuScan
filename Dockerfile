FROM python:3.10-slim

WORKDIR /app

# Install system dependencies (poppler for PDF->image, OpenGL for OpenCV)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    libgl1 \
    libglib2.0-0 \
    poppler-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install dependencies. PaddleOCR uses PaddlePaddle (not PyTorch), so we do NOT
# install torch here — it would add >1GB and massively increase OOM risk on
# free-tier hosts (512MB RAM). Models load lazily on first scan (see app.py).
RUN pip install --no-cache-dir -r requirements.txt && \
    rm -rf /root/.cache/pip

# Copy the entire project
COPY . .

# Create uploads directory
RUN mkdir -p uploads

# Fast API / Flask port
EXPOSE 5000

# Set environment variables
ENV FLASK_APP=backend/app.py
ENV PYTHONUNBUFFERED=1
# Keep OCR lazy by default to avoid OOM at startup (status 137)
ENV EAGER_OCR=0

# Start application (binds to $PORT which Render/Railway/HF inject)
CMD ["python", "backend/app.py"]
