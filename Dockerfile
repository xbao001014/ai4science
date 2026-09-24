FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY . ./
WORKDIR /app/fulltext_workflow

EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "gap_ui.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
