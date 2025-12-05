FROM python:3.9-slim

WORKDIR /app

# 1. 设置时区为上海 (非常重要，否则你的日志时间会不对)
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 2. 确保 Python 日志不缓存，实时打印
ENV PYTHONUNBUFFERED=1

# 3. 先拷贝依赖文件 (利用 Docker 缓存层，依赖不变时不用重新下载)
COPY requirements.txt .

# 4. 安装依赖 (加了清华源，构建速度更快)
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 5. 核心修改：把当前目录下所有文件（app.py, database.py, templates文件夹等）全拷进去
COPY . .

# 6. 启动命令
CMD ["python", "app.py"]
