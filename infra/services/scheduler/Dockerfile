FROM python:3.12-slim
WORKDIR /app
COPY app.py .
# -u: unbuffered stdout so logs stream immediately to kubectl logs
CMD ["python", "-u", "app.py"]
