FROM python:3.9-slim
WORKDIR /app
# 这一行非常重要，确保日志能实时打印出来
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
CMD ["python", "app.py"]
