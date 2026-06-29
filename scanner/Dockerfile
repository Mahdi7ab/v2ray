FROM python:3.9-slim

WORKDIR /app

# نصب پکیج‌های سیستمی مورد نیاز
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# دانلود و نصب xray-core (ورژن جدیدتر پیشنهاد می‌شود اما طبق سورس شما 1.8.23 استفاده شده)
RUN wget https://github.com/XTLS/Xray-core/releases/download/v1.8.23/Xray-linux-64.zip && \
    unzip Xray-linux-64.zip && \
    mv xray /usr/local/bin/ && \
    chmod +x /usr/local/bin/xray && \
    rm Xray-linux-64.zip

# اطمینان از نصب موفق xray
RUN xray version

# نصب پیش‌نیازهای پایتون
RUN pip install requests

# ایجاد پوشه دیتا برای نگهداری فایل خروجی
RUN mkdir -p /app/data

# کپی کردن اسکریپت جدید
COPY scanner.py .

VOLUME /app/data

CMD ["python", "-u", "scanner.py"]