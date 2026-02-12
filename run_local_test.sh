#!/bin/bash

echo "========================================"
echo "🧪 LOCAL PRODUCTION TEST"
echo "========================================"
echo ""

# Set port
export PORT=5002

echo "1️⃣  Testing dependencies..."
python3 -c "import eventlet; import gunicorn; print('✅ eventlet and gunicorn installed')" || {
    echo "❌ Missing dependencies. Run: pip install -r requirements.txt"
    exit 1
}

echo ""
echo "2️⃣  Starting gunicorn server..."
echo "   Command: gunicorn app:app --worker-class eventlet --workers 1 --bind 0.0.0.0:$PORT"
echo ""
echo "   Press Ctrl+C to stop the server"
echo "   Then test in another terminal:"
echo ""
echo "   curl http://localhost:$PORT/health"
echo ""
echo "========================================"
echo ""

gunicorn app:app --worker-class eventlet --workers 1 --timeout 120 --graceful-timeout 30 --keep-alive 5 --log-level info --bind 0.0.0.0:$PORT
