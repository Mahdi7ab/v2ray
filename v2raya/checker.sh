#!/bin/bash

SUB_URL="$1"

if [ -z "$SUB_URL" ]; then
    echo "Usage:"
    echo "./checker.sh <subscription_url>"
    exit 1
fi

TMP_FILE=$(mktemp)

echo "Downloading subscription..."
curl -L -s "$SUB_URL" -o "$TMP_FILE"

if grep -q "^vmess://" "$TMP_FILE"; then
    cp "$TMP_FILE" decoded.txt
else
    base64 -d "$TMP_FILE" > decoded.txt 2>/dev/null
fi

grep -E '^(vmess|vless|trojan)://' decoded.txt \
    | sort -u \
    > working.txt

COUNT=$(wc -l < working.txt)

echo ""
echo "Finished."
echo "Valid configs found: $COUNT"
echo "Saved to:"
echo "$(pwd)/working.txt"

rm -f "$TMP_FILE"