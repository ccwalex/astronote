#!/bin/bash

echo "=== Astronote Diagnostic Test ==="

echo "\n[1] Checking if Backend is running on Port 8000..."
if command -v lsof >/dev/null 2>&1; then
  lsof -i:8000
  if [ $? -eq 0 ]; then
    echo "✅ Backend is running."
  else
    echo "❌ Backend is not running on port 8000."
  fi
else
  echo "lsof not installed, falling back to curl"
  if curl -s http://localhost:8000 >/dev/null 2>&1; then
    echo "✅ Backend is running and reachable via HTTP."
  else
    echo "❌ Backend is not reachable on port 8000."
  fi
fi

echo "\n[2] Checking if Frontend (Vite) is running on Port 5173..."
if command -v lsof >/dev/null 2>&1; then
  lsof -i:5173
  if [ $? -eq 0 ]; then
    echo "✅ Frontend is running."
  else
    echo "❌ Frontend is not running on port 5173."
  fi
fi

echo "\n[3] Testing Backend API (/api/workspace) reachability..."
HTTP_STATUS=$(curl -o /dev/null -s -w "%{http_code}\n" http://localhost:8000/api/workspace || echo "FAILED")
if [ "$HTTP_STATUS" = "FAILED" ]; then
  echo "❌ Failed to connect to Backend API."
else
  echo "API returned HTTP status: $HTTP_STATUS"
fi

echo "\n=== Diagnostic Complete ==="
