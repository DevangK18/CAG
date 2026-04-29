#!/bin/bash

echo "Testing CAG API Smoke Test..."
echo "=============================="
echo ""

echo "1. Health Check:"
curl -s http://localhost:8000/health
echo ""
echo ""

echo "2. Chat Stream Test:"
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"What is PRIASoft?","style":"adaptive"}'
echo ""
