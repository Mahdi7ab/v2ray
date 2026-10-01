#!/bin/bash

# ۱. اجرای سرویس‌های اصلی در پس‌زمینه (در صورتی که اجرا نباشند، استارت می‌شوند)
echo "Starting V2RayA and Xray Server..."
docker compose up -d v2raya xray-server

# ۲. اجرای اسکنر و صبر کردن تا پایان اسکن
echo "Starting Config Scanner..."
docker compose up config-scanner --build

# ۳. آپلود در گیت‌هاب
echo "Scanner finished. Pushing to GitHub..."

git add free-configs/working.txt
git add free-configs/all_configs.txt
git add free-configs/gemini_configs.txt

git commit -m "Auto-update configs: $(date '+%Y-%m-%d %H:%M:%S')"
git push origin main

echo "Done!"