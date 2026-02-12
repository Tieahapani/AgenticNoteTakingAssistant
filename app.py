# app.py - Flask REST API backend for VoiceLog AI

import os
import json
import tempfile
import subprocess
from datetime import datetime

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from utils.timing import LatencyTracker
from auth import verify_token
from utils.firebase_client import FirebaseClient
from utils.user_profile import get_user_profile

from agents.voicelog_graph import voicelog_app, _memory_store

load_dotenv()

# ============================================
# FIREBASE CREDENTIALS FILE (Render-safe)
# ============================================

firebase_cred_path = None

if os.getenv("FIREBASE_CREDENTIALS_JSON"):
    print("🔧 Loading Firebase credentials from environment variable...")
    creds_json = json.loads(os.getenv("FIREBASE_CREDENTIALS_JSON"))

    temp_creds = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json")
    json.dump(creds_json, temp_creds)
    temp_creds.close()

    firebase_cred_path = temp_creds.name
    print(f"✅ Firebase credentials loaded to temp file: {firebase_cred_path}")
else:
    firebase_cred_path = os.path.join(os.path.dirname(__file__), "firebase-credentials.json")
    print(f"🔧 Using local Firebase credentials: {firebase_cred_path}")


# ============================================
# APP SETUP
# ============================================

app = Flask(__name__)
CORS(app, origins="*")

print(f"App Startup - Store available: {_memory_store is not None}")

# ============================================
# WHISPER MODEL (lazy-loaded)
# ============================================

_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        print("⏳ Loading Whisper model (base)...")
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        print("✅ Whisper model loaded")
    return _whisper_model

# ============================================
# INITIALIZE CLIENTS
# ============================================

firebase_client = FirebaseClient()
user_profile = get_user_profile()

# ============================================
# API ENDPOINTS WITH AUTHENTICATION
# ============================================

@app.route("/api/user/timezone", methods=["POST"])
@verify_token
def set_user_timezone():
    user_id = request.user_id
    data = request.get_json()
    timezone = data.get("timezone")

    if not timezone:
        return jsonify({"success": False, "error": "Timezone required"}), 400

    try:
        user_profile.set_timezone(user_id, timezone)
        return jsonify({"success": True, "timezone": timezone})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/user/profile", methods=["GET"])
@verify_token
def get_user_profile_endpoint():
    user_id = request.user_id
    try:
        profile = user_profile.get_profile(user_id)
        return jsonify({"success": True, "profile": profile})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/create_folder", methods=["POST"])
@verify_token
def api_create_folder():
    user_id = request.user_id
    data = request.get_json()
    folder_name = data["folder_name"].strip().title()
    emoji = data.get("emoji", "").strip()
    result = firebase_client.create_folder(folder_name, emoji, user_id)
    return jsonify({"result": result})


@app.route("/api/create_task", methods=["POST"])
@verify_token
def api_create_task():
    user_id = request.user_id
    data = request.get_json()
    result = firebase_client.create_task(
        data["task_name"],
        data["folder_name"],
        user_id,
        data.get("recurrence", "once"),
        data.get("time", ""),
        data.get("duration", ""),
    )
    return jsonify({"result": result})


@app.route("/api/move_task", methods=["POST"])
@verify_token
def api_move_task():
    user_id = request.user_id
    data = request.get_json()
    result = firebase_client.move_task(data["task_name"], data["destination_folder"], user_id)
    return jsonify({"result": result})


@app.route("/api/delete_task", methods=["POST"])
@verify_token
def api_delete_task():
    user_id = request.user_id
    data = request.get_json()
    result = firebase_client.delete_task(data["task_name"], user_id)
    return jsonify({"result": result})


@app.route("/api/delete_folder", methods=["POST"])
@verify_token
def api_delete_folder():
    user_id = request.user_id
    data = request.get_json()
    result = firebase_client.delete_folder(data["folder_name"], user_id)
    return jsonify({"result": result})


@app.route("/api/edit_folder_name", methods=["POST"])
@verify_token
def api_edit_folder_name():
    user_id = request.user_id
    data = request.get_json()
    result = firebase_client.edit_folder_name(
        data["old_name"],
        data["new_name"],
        data.get("new_emoji"),
        user_id,
    )
    return jsonify({"result": result})


@app.route("/api/edit_task", methods=["POST"])
@verify_token
def api_edit_task():
    user_id = request.user_id
    data = request.get_json()
    result = firebase_client.edit_task(
        data["old_task_name"],
        data.get("new_task_name"),
        data.get("new_folder"),
        data.get("new_recurrence"),
        data.get("new_time"),
        data.get("new_duration"),
        user_id,
    )
    return jsonify({"result": result})


@app.route("/api/get_folder_contents", methods=["POST"])
@verify_token
def api_get_folder_contents():
    user_id = request.user_id
    data = request.get_json()
    result = firebase_client.get_folder_contents(data["folder_name"], user_id)
    return jsonify({"result": result})


@app.route("/api/list_all_folders", methods=["GET"])
@verify_token
def api_list_all_folders():
    user_id = request.user_id
    result = firebase_client.list_all_folders(user_id)
    return jsonify({"result": result})


@app.route("/api/mark_task_complete", methods=["POST"])
@verify_token
def api_mark_task_complete():
    user_id = request.user_id
    data = request.get_json()
    task_name = data.get("task_name", "").strip()

    if not task_name:
        return jsonify({"result": "Error: Task name is required"}), 400

    result = firebase_client.mark_task_complete(task_name, user_id)
    return jsonify({"result": result})


@app.route("/api/mark_task_incomplete", methods=["POST"])
@verify_token
def api_mark_task_incomplete():
    user_id = request.user_id
    data = request.get_json()
    task_name = data.get("task_name", "").strip()

    if not task_name:
        return jsonify({"result": "Error: Task name is required"}), 400

    result = firebase_client.mark_task_incomplete(task_name, user_id)
    return jsonify({"result": result})


@app.route("/api/toggle_task", methods=["POST"])
@verify_token
def api_toggle_task():
    user_id = request.user_id
    data = request.get_json()
    task_id = data.get("task_id", "").strip()
    completed = data.get("completed", False)

    if not task_id:
        return jsonify({"result": "Error: Task ID is required"}), 400

    result = firebase_client.toggle_task(task_id, completed, user_id)
    return jsonify({"result": result})


# ============================================
# WHISPER TRANSCRIPTION ROUTE
# ============================================

def _convert_to_wav(input_path):
    """Convert any audio format to 16kHz mono WAV for Whisper."""
    wav_path = input_path + ".wav"

    # Log input file size
    fsize = os.path.getsize(input_path) if os.path.exists(input_path) else 0
    print(f"🔄 Converting audio: {input_path} ({fsize} bytes)")

    # Try ffmpeg first
    try:
        result = subprocess.run(
            ['ffmpeg', '-y', '-i', input_path, '-ar', '16000', '-ac', '1', '-f', 'wav', wav_path],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"✅ ffmpeg conversion OK → {wav_path}")
            return wav_path
        print(f"⚠️ ffmpeg failed (code {result.returncode}): {result.stderr[:300]}")
    except FileNotFoundError:
        print("⚠️ ffmpeg not found, trying afconvert...")

    # macOS built-in fallback
    try:
        result = subprocess.run(
            ['afconvert', '-f', 'WAVE', '-d', 'LEI16@16000', '-c', '1', input_path, wav_path],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"✅ afconvert conversion OK → {wav_path}")
            return wav_path
        print(f"⚠️ afconvert failed (code {result.returncode}): {result.stderr[:300]}")
    except FileNotFoundError:
        print("⚠️ afconvert not found")

    print("❌ All audio conversion methods failed")
    return None


@app.route("/transcribe", methods=["POST"])
@verify_token
def transcribe_audio():
    if 'audio' not in request.files:
        return jsonify({"success": False, "error": "No audio file provided"}), 400

    audio_file = request.files['audio']

    suffix = os.path.splitext(audio_file.filename or "audio.m4a")[1] or ".m4a"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    wav_path = None
    try:
        audio_file.save(tmp.name)
        tmp.close()

        # Check file isn't empty (< 1KB means no real audio)
        fsize = os.path.getsize(tmp.name)
        if fsize < 1000:
            print(f"⚠️ Audio file too small ({fsize} bytes) — recording may have failed")
            return jsonify({"success": False, "error": "Recording too short or empty"}), 400

        # Convert to WAV so Whisper can always decode it
        wav_path = _convert_to_wav(tmp.name)
        audio_path = wav_path if wav_path else tmp.name

        model = get_whisper_model()
        segments, info = model.transcribe(audio_path, beam_size=5)
        text = " ".join([segment.text for segment in segments]).strip()

        print(f"🎤 Whisper: \"{text}\" (lang={info.language}, {info.duration:.1f}s)")

        return jsonify({
            "success": True,
            "text": text,
            "language": info.language,
            "duration": round(info.duration, 2),
        })
    except Exception as e:
        print(f"❌ Transcription error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        if wav_path:
            try:
                os.unlink(wav_path)
            except Exception:
                pass


# ============================================
# MAIN AGENT ROUTE
# ============================================

@app.route("/process_command", methods=["POST"])
@verify_token 
def process_command():
    data = request.json
    user_command = data.get("command", "")
    user_id = request.user_id

    if not user_command:
        return jsonify({"error": "No command provided", "success": False}), 400

    thread_id = f"user_{user_id}"

    print(f"\n{'='*60}")
    print(f"📨 User: {user_id}")
    print(f"💬 Command: {user_command}")
    print(f"🧵 Thread: {thread_id}")
    print(f"{'='*60}")

    try:
        tracker = LatencyTracker()
        tracker.start("Total Request")

        config_to_use = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
        user_timezone = user_profile.get_timezone(user_id)

        result = voicelog_app.invoke(
            {"user_command": user_command, "user_timezone": user_timezone},
            config_to_use,
        )

        tracker.end("Total Request")

        response = result.get("final_response", "Command processed!")
        route = result.get("route_decision", "unknown")
        summary = tracker.get_summary()

        print(f"\n🔀 Route: {route.upper()}")
        print("\n📊 TIMING SUMMARY:")
        print(f"   Total: {summary['total_time']}s")
        for op, time_val in summary["operations"].items():
            if op != "Total Request":
                print(f"   - {op}: {time_val}s")
        print(f"✅ Response: {response}")
        print(f"{'='*60}\n")

        tracker.log_to_file(user_command, response)

        return jsonify({
            "success": True,
            "response": response,
            "latency": summary["total_time"],
            "breakdown": summary["operations"],
        })

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print(f"{'='*60}\n")

        return jsonify({"success": False, "error": str(e)}), 500


# ============================================
# HEALTH CHECK
# ============================================

@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "server": "flask",
        "langgraph_initialized": voicelog_app is not None,
        "firebase_connected": firebase_client.db is not None,
        "firebase_auth_enabled": True,
        "whisper_loaded": _whisper_model is not None,
        "checkpointer": "SQLite (voicelog_memory.db)",
        "store": "SQLite/PostgreSQL Store (environment-based)",
    })


# ============================================
# MOBILE APP ROUTES
# ============================================

@app.route("/folders")
@verify_token
def get_folders():
    user_id = request.user_id
    folders = firebase_client.db.collection("users").document(user_id).collection("folders").stream()
    folder_list = []

    for folder in folders:
        folder_data = folder.to_dict()
        folder_list.append({
            "id": folder.id,
            "name": folder_data["name"],
            "emoji": folder_data.get("emoji", ""),
        })

    return jsonify({"folders": folder_list, "success": True})


@app.route("/folders/<fid>/tasks")
@verify_token
def get_tasks(fid):
    user_id = request.user_id
    tasks = (
        firebase_client.db.collection("users")
        .document(user_id)
        .collection("tasks")
        .where("folder", "==", fid)
        .stream()
    )

    task_list = []
    for task in tasks:
        task_data = task.to_dict()
        task_list.append({
            "id": task.id,
            "name": task_data["name"],
            "completed": task_data.get("completed", False),
            "recurrence": task_data.get("recurrence", "once"),
            "time": task_data.get("time"),
            "duration": task_data.get("duration"),
            "folder": task_data["folder"],
            "created_at": firebase_client._timestamp_to_iso(task_data.get("created_at")),
            "completed_at": firebase_client._timestamp_to_iso(task_data.get("completed_at")),
            "due_date": firebase_client._timestamp_to_iso(task_data.get("due_date")),
            "is_high_priority": task_data.get("is_high_priority", False),
        })

    return jsonify({"tasks": task_list, "success": True})


@app.route("/tasks")
@verify_token
def all_tasks():
    user_id = request.user_id
    tasks = firebase_client.db.collection("users").document(user_id).collection("tasks").stream()
    task_list = []

    for task in tasks:
        task_data = task.to_dict()
        task_list.append({
            "id": task.id,
            "name": task_data["name"],
            "completed": task_data.get("completed", False),
            "folder": task_data["folder"],
            "recurrence": task_data.get("recurrence", "once"),
            "time": task_data.get("time"),
            "duration": task_data.get("duration"),
            "created_at": firebase_client._timestamp_to_iso(task_data.get("created_at")),
            "completed_at": firebase_client._timestamp_to_iso(task_data.get("completed_at")),
            "due_date": firebase_client._timestamp_to_iso(task_data.get("due_date")),
            "is_high_priority": task_data.get("is_high_priority", False),
        })

    return jsonify({"tasks": task_list, "success": True})


# ============================================
# START SERVER
# ============================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))

    print(f"\n{'='*60}")
    print("🎯 VoiceLog AI Backend Server")
    print(f"{'='*60}")
    print(f"📡 HTTP Server: http://localhost:{port}")
    print("🔐 Authentication: Firebase Auth Enabled")
    print("\n📋 Endpoints:")
    print("   POST /transcribe - Whisper speech-to-text (Auth Required)")
    print("   POST /process_command - Main chat (Auth Required)")
    print("   GET  /health - Health check (No Auth)")
    print(f"{'='*60}\n")

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
