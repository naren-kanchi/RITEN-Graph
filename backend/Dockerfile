FROM python:3.12.10-slim-bookworm
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY riten ./riten
RUN useradd --create-home riten
USER riten
CMD ["uvicorn", "riten.main:app", "--host", "0.0.0.0", "--port", "8000"]
