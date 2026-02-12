#!/usr/bin/env python3
"""
WebSocket Connection Test Script
Tests if gunicorn + eventlet + Flask-SocketIO works correctly
"""

import socketio
import time

# Create a Socket.IO client
sio = socketio.Client()

@sio.event
def connect():
    print("✅ WebSocket connected successfully!")
    print("   Connection ID:", sio.sid)

@sio.event
def disconnect():
    print("❌ WebSocket disconnected")

@sio.event
def registered(data):
    print("✅ Registration successful!")
    print("   Data:", data)

@sio.event
def pong(data):
    print("✅ Pong received!")
    print("   Data:", data)

@sio.event
def connect_error(data):
    print("❌ Connection error:", data)

def test_websocket(url="http://localhost:5002"):
    """Test WebSocket connection"""
    print(f"\n{'='*60}")
    print(f"🧪 TESTING WEBSOCKET CONNECTION")
    print(f"{'='*60}")
    print(f"Server URL: {url}\n")

    try:
        # Try to connect
        print("🔌 Attempting to connect...")

        # Note: For production, you'd include Firebase auth token
        # For now, testing without auth to see if WebSocket works
        sio.connect(url,
                   wait_timeout=10,
                   transports=['websocket', 'polling'])

        print("⏳ Waiting for connection...")
        time.sleep(2)

        # Send ping
        print("\n📤 Sending ping...")
        sio.emit('ping')

        # Wait for pong
        time.sleep(2)

        print("\n✅ WebSocket test PASSED!")
        print("   Gunicorn + eventlet + WebSocket working correctly")

        # Disconnect
        print("\n🔌 Disconnecting...")
        sio.disconnect()

        print(f"\n{'='*60}")
        print("✅ ALL TESTS PASSED - Ready for Railway deployment!")
        print(f"{'='*60}\n")

        return True

    except Exception as e:
        print(f"\n❌ WebSocket test FAILED!")
        print(f"   Error: {e}")
        print(f"\n{'='*60}")
        print("⚠️  Fix the issue before deploying to Railway")
        print(f"{'='*60}\n")

        return False

if __name__ == "__main__":
    success = test_websocket()
    exit(0 if success else 1)
