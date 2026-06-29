#!/bin/bash

echo "Starting Config Scanner..."
# اجرای داکر و صبر کردن تا اسکن تمام شود
docker compose up config-scanner --build

echo "Scanner finished. Pushing to GitHub..."

# اضافه کردن فایل‌های جدید خروجی به گیت
git add free-config/working.txt
git add free-config/all_configs.txt

# ایجاد کامیت با تاریخ و ساعت دقیق همان لحظه
git commit -m "Auto-update configs: $(date '+%Y-%m-%d %H:%M:%S')"

# پوش کردن روی سرور گیت‌هاب (مطمئن شوید روی سرور لاگین هستید)
git push origin main

echo "Done!"