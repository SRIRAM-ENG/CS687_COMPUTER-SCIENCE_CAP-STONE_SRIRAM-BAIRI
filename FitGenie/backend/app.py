# backend/app.py
import os
from datetime import date, datetime

from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError
from dotenv import load_dotenv

# Optional TLS CA bundle for MongoDB Atlas
try:
    import certifi  # type: ignore
    _CERT_PATH = certifi.where()
except Exception:
    _CERT_PATH = None

from models import user_doc, sensordata_doc, feedback_doc
from mcp import MCPBehaviorModel
from ai_engine import generate_plan, generate_nudges

# ----------------- setup -----------------
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME   = os.getenv("DB_NAME", "ai_fitness")

def make_client(uri: str) -> MongoClient:
    """Create a Mongo client that works for both local and Atlas."""
    kwargs = {"serverSelectionTimeoutMS": 30000}
    if uri.startswith("mongodb+srv://") or "mongodb.net" in uri:
        if _CERT_PATH:
            kwargs["tlsCAFile"] = _CERT_PATH
    return MongoClient(uri, **kwargs)

app = Flask(__name__)
CORS(app)

client = make_client(MONGO_URI)
db = client[DB_NAME]

behavior = MCPBehaviorModel(db)

# ----------------- helpers -----------------
def get_user_id():
    return request.headers.get("X-User-Id", "U123")

def _normalize_plan_doc(doc):
    """Return a JSON-safe plan dict: drop _id and ensure date is a string."""
    if not doc:
        return doc
    d = dict(doc)
    d.pop("_id", None)
    if isinstance(d.get("date"), (datetime, date)):
        d["date"] = d["date"].isoformat()
    return d

# ----------------- routes -----------------
@app.get("/")
def root():
    return {
        "service": "ai-fitness-backend",
        "ok": True,
        "endpoints": [
            "/health", "/auth/login", "/me",
            "/me/metrics", "/me/metrics/steps",
            "/me/plan", "/me/plan/complete",
            "/me/recommendations", "/me/nudge", "/me/feedback"
        ]
    }

@app.get("/health")
def health():
    status = "ok"
    try:
        client.admin.command("ping")
    except Exception:
        status = "degraded"
    return {"status": status, "time": datetime.utcnow().isoformat()}

@app.post("/auth/login")
def login():
    body = request.json or {}
    user_id = body.get("userId", "U123")
    name    = body.get("name", "Demo User")
    try:
        if not db.users.find_one({"userId": user_id}):
            db.users.insert_one(user_doc(user_id, name))
        return {"userId": user_id, "name": name}
    except (PyMongoError, ServerSelectionTimeoutError) as e:
        return jsonify({"error": "database_unreachable", "detail": str(e)}), 503

@app.get("/me")
def me():
    user_id = get_user_id()
    try:
        user = db.users.find_one({"userId": user_id}) or user_doc(user_id)
        return {"userId": user_id, "name": user.get("name", "Demo User")}
    except (PyMongoError, ServerSelectionTimeoutError) as e:
        return jsonify({"error": "database_unreachable", "detail": str(e)}), 503

@app.post("/me/metrics")
def ingest_metrics():
    """
    Insert metrics as separate samples (e.g., HR, Steps, SleepScore).
    """
    user_id = get_user_id()
    payload = request.json
    docs = []
    if isinstance(payload, list):
        for m in payload:
            docs.append(sensordata_doc(user_id, m["metricType"], m["value"]))
    else:
        docs.append(sensordata_doc(user_id, payload["metricType"], payload["value"]))
    try:
        if docs:
            db.sensordata.insert_many(docs)
        return {"ingested": len(docs)}
    except (PyMongoError, ServerSelectionTimeoutError) as e:
        return jsonify({"error": "database_unreachable", "detail": str(e)}), 503

@app.post("/me/metrics/steps")
def set_steps():
    """
    Overwrite today's step count for the current user (one record per day).
    """
    user_id = get_user_id()
    body = request.json or {}
    steps = int(body.get("value", 0))
    today = date.today().isoformat()

    # Build a JSON-safe doc and tag with date for idempotent upsert.
    doc = sensordata_doc(user_id, "Steps", steps)
    doc["date"] = today

    try:
        db.sensordata.update_one(
            {"userId": user_id, "metricType": "Steps", "date": today},
            {"$set": doc},
            upsert=True
        )
        return {"ok": True, "steps": steps, "date": today}
    except (PyMongoError, ServerSelectionTimeoutError) as e:
        return jsonify({"error": "database_unreachable", "detail": str(e)}), 503

@app.get("/me/metrics")
def list_metrics():
    user_id = get_user_id()
    try:
        cur = db.sensordata.find({"userId": user_id}).sort("ts", -1).limit(50)
        return jsonify([
            {"metricType": d["metricType"], "value": d["value"], "ts": d["ts"].isoformat()}
            for d in cur
        ])
    except (PyMongoError, ServerSelectionTimeoutError) as e:
        return jsonify({"error": "database_unreachable", "detail": str(e)}), 503

@app.get("/me/plan")
def get_plan():
    """Return today's plan (JSON-safe, no _id)."""
    user_id = get_user_id()
    today = date.today().isoformat()
    try:
        user = db.users.find_one({"userId": user_id}) or user_doc(user_id)
        raw = db.plans.find_one({"userId": user_id, "date": today}, {"_id": 0})
        if not raw:
            plan = generate_plan(user, behavior, db)  # returns plain dict
            return jsonify(_normalize_plan_doc(plan))
        return jsonify(_normalize_plan_doc(raw))
    except (PyMongoError, ServerSelectionTimeoutError) as e:
        return jsonify({"error": "database_unreachable", "detail": str(e)}), 503

@app.post("/me/plan/complete")
def complete_plan():
    user_id = get_user_id()
    today = date.today().isoformat()
    try:
        db.plans.update_one(
            {"userId": user_id, "date": today},
            {"$set": {"status": "Completed"}},
            upsert=True
        )
        return {"status": "Completed"}
    except (PyMongoError, ServerSelectionTimeoutError) as e:
        return jsonify({"error": "database_unreachable", "detail": str(e)}), 503

@app.get("/me/recommendations")
def get_recs():
    user_id = get_user_id()
    try:
        recs = list(db.recommendations.find({"userId": user_id}).sort("ts", -1).limit(20))
        return jsonify([
            {"message": r["message"], "ts": r["ts"].isoformat(), "context": r.get("context", "")}
            for r in recs
        ])
    except (PyMongoError, ServerSelectionTimeoutError) as e:
        return jsonify({"error": "database_unreachable", "detail": str(e)}), 503

@app.post("/me/nudge")
def make_nudge():
    user_id = get_user_id()
    try:
        rec = generate_nudges(user_id, behavior, db)
        return jsonify({"message": rec["message"], "ts": rec["ts"].isoformat()})
    except (PyMongoError, ServerSelectionTimeoutError) as e:
        return jsonify({"error": "database_unreachable", "detail": str(e)}), 503

@app.post("/me/feedback")
def give_feedback():
    user_id = get_user_id()
    body = request.json or {}
    try:
        doc = feedback_doc(
            user_id,
            rpe=body.get("rpe"),
            mood=body.get("mood"),
            pain=body.get("pain", "none"),
            notes=body.get("notes", "")
        )
        db.feedback.insert_one(doc)
        return {"ok": True}
    except (PyMongoError, ServerSelectionTimeoutError) as e:
        return jsonify({"error": "database_unreachable", "detail": str(e)}), 503

# ----------------- main -----------------
if __name__ == "__main__":
    if (MONGO_URI.startswith("mongodb+srv://") or "mongodb.net" in MONGO_URI) and not _CERT_PATH:
        print("[WARN] Using MongoDB Atlas but 'certifi' is not installed. "
              "Install with 'pip install certifi' to avoid TLS errors.")
    app.run(host="0.0.0.0", port=5000)
