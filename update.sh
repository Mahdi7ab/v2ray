#!/bin/bash

echo "Starting Config Scanner..."
docker compose up config-scanner --build

echo "Scanner finished. Pushing to GitHub..."

# اضافه کردن فایل‌های جدید خروجی به گیت (مسیرهای اصلاح شده)
git add free-configs/working.txt
git add free-configs/all_configs.txt
git add update.sh

# ایجاد کامیت با تاریخ و ساعت دقیق همان لحظه
git commit -m "Auto-update configs: $(date '+%Y-%m-%d %H:%M:%S')"

# پوش کردن روی سرور گیت‌هاب
git push origin main

echo "Done!"