# 🗄️ Database Configuration Guide

Your application now supports **environment-based database configuration**!

---

## 🎯 How It Works

The app automatically switches between SQLite and PostgreSQL based on the `USE_SQLITE` environment variable:

| Environment | USE_SQLITE | Checkpoint | Memory Store | Use Case |
|------------|-----------|-----------|--------------|----------|
| **Local Development** | `true` | SQLite | SQLite (InMemory) | Simple, no setup |
| **Production** | `false` | SQLite | PostgreSQL | Scalable, persistent |

---

## 🚀 Quick Start

### Local Development (Default)

**No setup required!** Just run:

```bash
cd backend
python app.py
```

Your `.env` is already configured:
```bash
USE_SQLITE=true  # ✅ Using SQLite for local dev
```

**What happens:**
- ✅ No PostgreSQL installation needed
- ✅ Memory stored in-memory (fast, simple)
- ✅ Checkpoints stored in SQLite file
- ✅ All data resets when you restart (good for testing)

---

### Production Deployment

When deploying to Render/Railway/Heroku:

1. **Update `.env` on your server:**
   ```bash
   USE_SQLITE=false
   POSTGRES_URL=postgresql://user:pass@host:5432/dbname
   ```

2. **What happens:**
   - ✅ Memory persisted in PostgreSQL (durable)
   - ✅ Handles concurrent users
   - ✅ Scalable and production-ready

---

## 📊 What Changed

### Before (Mixed Setup)
```
┌─────────────┐
│   SQLite    │  ← Checkpoint
└─────────────┘
┌─────────────┐
│ PostgreSQL  │  ← Memory Store (required PG setup locally)
└─────────────┘
```

### After (Configurable)
```
Local Dev:
┌─────────────┐
│   SQLite    │  ← Checkpoint
└─────────────┘
┌─────────────┐
│   SQLite    │  ← Memory Store (in-memory)
└─────────────┘

Production:
┌─────────────┐
│   SQLite    │  ← Checkpoint
└─────────────┘
┌─────────────┐
│ PostgreSQL  │  ← Memory Store (persistent)
└─────────────┘
```

---

## 🔍 Where Memory is Stored

### SQLite Mode (Local)
- **Checkpoint**: `backend/voicelog_memory.db` (conversation history)
- **Memory Store**: In-memory (resets on restart)
- **User Preferences**: Lost on restart (for testing only)

### PostgreSQL Mode (Production)
- **Checkpoint**: `backend/voicelog_memory.db` (conversation history)
- **Memory Store**: PostgreSQL database (persistent)
- **User Preferences**: Saved permanently

---

## 🧪 Testing Both Modes

### Test SQLite (Local)
```bash
# .env
USE_SQLITE=true

# Run
python app.py

# Check logs - should see:
# 🔧 Initializing SQLite store (local development mode)...
# ✅ SQLite store initialized
# 🧠 SQLite Store: Ready
```

### Test PostgreSQL (Production)
```bash
# .env
USE_SQLITE=false
POSTGRES_URL=postgresql://...

# Run
python app.py

# Check logs - should see:
# 🔧 Initializing PostgreSQL store (production mode)...
# ✅ PostgreSQL store initialized
# 🧠 PostgreSQL Store: Ready
```

---

## ⚠️ Important Notes

### SQLite Mode Limitations
- ❌ Memory is NOT persistent (resets on restart)
- ❌ User preferences won't be remembered between sessions
- ✅ Perfect for local development and testing
- ✅ No database setup required

### PostgreSQL Mode Benefits
- ✅ Memory persists across restarts
- ✅ User preferences remembered forever
- ✅ Production-ready
- ❌ Requires PostgreSQL setup

---

## 🎯 Recommended Workflow

1. **Local Development:**
   - Use `USE_SQLITE=true`
   - Test features quickly
   - No database setup needed

2. **Staging/Testing:**
   - Use `USE_SQLITE=false`
   - Test with real PostgreSQL
   - Verify persistence works

3. **Production:**
   - Use `USE_SQLITE=false`
   - Deploy with managed PostgreSQL (Render, Railway, etc.)
   - Monitor performance

---

## 🔧 Troubleshooting

### Issue: "Cannot connect to PostgreSQL"
**Solution:** Make sure `USE_SQLITE=true` in your `.env` file for local development.

### Issue: "Preferences not saving"
**Expected:** In SQLite mode (local), preferences reset on restart. This is intentional for testing.
**Solution:** Use PostgreSQL mode if you need persistence.

### Issue: "Store setup warning"
**Check:**
1. Is `USE_SQLITE` set correctly?
2. If using PostgreSQL, is the database running?
3. Is `POSTGRES_URL` correct?

---

## 📝 Migration Path

### From SQLite to PostgreSQL

When you're ready to deploy:

1. Set `USE_SQLITE=false` in production `.env`
2. Add PostgreSQL connection string
3. Deploy
4. Memory will start fresh in PostgreSQL

**Note:** No migration needed - preferences start fresh in production (this is usually desired).

---

## 🎉 Summary

You now have:
- ✅ Simple SQLite setup for local development
- ✅ Production-ready PostgreSQL support
- ✅ Easy switching via environment variable
- ✅ No code changes needed
- ✅ Best of both worlds!

Happy coding! 🚀
