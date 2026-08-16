# 使用官方轻量级 Python 基础镜像
FROM python:3.11-slim

# 设置工作目录与 Python 运行环境变量
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=3000

# 先复制依赖描述并安装 Python 依赖库
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码与资源文件
COPY . .

# 暴露服务端口
EXPOSE 3000

# 容器启动命令
CMD ["python3", "app.py"]
