FROM python:3.12-slim
WORKDIR /opt/alfa
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY backend/ /opt/alfa/backend/
COPY frontend/ /opt/alfa/frontend/
WORKDIR /opt/alfa/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
