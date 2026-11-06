#!/usr/bin/env bash
# Start the Battery Passport app so the ESP32 can reach it.
# Usage: ./start.sh            (port 8001)
#        PORT=8002 ./start.sh  (another port)
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8001}"
export BP_BASE_URL="${BP_BASE_URL:-http://localhost:$PORT}"

if [ ! -x .venv/bin/uvicorn ]; then
  echo "No virtual environment found. Run first:"
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

# The ESP32 sends to the IP written in secrets.h. Warn if this laptop no longer has it.
SECRETS=esp32/firmware/include/secrets.h
if [ -f "$SECRETS" ]; then
  ESP_IP=$(grep -oP 'SERVER_URL\s+"http://\K[0-9.]+' "$SECRETS" || true)
  ESP_PORT=$(grep -oP 'SERVER_URL\s+"http://[0-9.]+:\K[0-9]+' "$SECRETS" || true)
  if [ -n "$ESP_IP" ] && ! ip -4 -o addr show | grep -q " $ESP_IP/"; then
    echo "WARNING: the ESP32 sends to $ESP_IP, but this laptop's IP is now:"
    ip -4 -o addr show | awk '$2 != "lo" {print "  " $2 "  " $4}'
    echo "Update SERVER_URL in $SECRETS and flash the board again."
    echo
  fi
  if [ -n "$ESP_PORT" ] && [ "$ESP_PORT" != "$PORT" ]; then
    echo "WARNING: the ESP32 sends to port $ESP_PORT, but the app starts on $PORT."
    echo
  fi
fi

echo "Battery Passport: http://localhost:$PORT  (Ctrl+C to stop)"
exec .venv/bin/uvicorn app:app --host 0.0.0.0 --port "$PORT"
