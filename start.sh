#!/usr/bin/env bash
# Start the Store Intelligence System

echo "Starting Store Intelligence API..."
DATABASE_URL=sqlite:///store_intelligence.db venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 > api.log 2>&1 &
API_PID=$!

echo "Starting Store Intelligence Dashboard..."
DATABASE_URL=sqlite:///store_intelligence.db venv/bin/streamlit run src/dashboard/app.py --server.port 8501 --server.address 127.0.0.1 > dashboard.log 2>&1 &
DASH_PID=$!

echo "Platform is running!"
echo "Dashboard: http://127.0.0.1:8501"
echo "API Docs: http://127.0.0.1:8000/docs"
echo "To stop, run: kill $API_PID $DASH_PID"
