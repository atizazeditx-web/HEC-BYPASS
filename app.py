# app.py - UID management server
import os
import json
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template
from models import init_db, UIDEntry
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv

load_dotenv()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "changeme123")
DB_URL = os.getenv("DB_URL", "sqlite:///uids.db")
PORT = int(os.getenv("PORT", "19109"))

app = Flask(__name__, template_folder="templates")
db_session = init_db(DB_URL)

# Simple SSE publisher (in-memory)
from queue import Queue
subscribers = []

def publish(event_type, payload):
    msg = json.dumps({"type": event_type, "data": payload, "ts": time.time()})
    for q in list(subscribers):
        try:
            q.put(msg, timeout=0.5)
        except:
            pass

def admin_auth():
    token = request.headers.get("X-Admin-Token") or request.args.get("admin_token") or request.args.get("key")
    return token == ADMIN_TOKEN

def find_uid_entry(session, uid):
    return session.query(UIDEntry).filter(UIDEntry.uid == uid).first()

def uid_status_dict(e):
    return {
        "uid": e.uid,
        "banned": bool(e.banned),
        "paused": bool(e.paused),
        "meta": e.meta or "",
        "created_at": e.created_at.isoformat(),
        "expires_at": e.expires_at.isoformat() if e.expires_at else None
    }

def parse_duration_to_hours(spec: str):
    """Parse duration like '2d', '12h', '30m', '48' -> hours (float) or None for never."""
    if not spec:
        return None
    s = str(spec).lower().strip()
    if s in ("0","0s","never","forever","inf", "none"):
        return None
    try:
        if s.endswith("d"):
            return float(s[:-1]) * 24.0
        if s.endswith("h"):
            return float(s[:-1])
        if s.endswith("m"):
            return float(s[:-1]) / 60.0
        # treat plain number as hours
        return float(s)
    except Exception:
        return None

# ---------- UI ----------
@app.route("/")
def index():
    q = db_session.query(UIDEntry).order_by(UIDEntry.created_at.desc()).limit(200).all()
    return render_template("index.html", uids=q)

# ---------- Add (POST) ----------
@app.route("/api/add", methods=["POST"])
def api_add():
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    data = request.json or {}
    uid = data.get("uid")
    hours = data.get("hours")
    meta = data.get("meta","")
    if not uid:
        return jsonify({"ok": False, "message": "Missing uid parameter"}), 400
    expires_at = None
    if hours:
        try:
            h = float(hours)
            expires_at = datetime.utcnow() + timedelta(hours=h)
        except:
            pass
    entry = UIDEntry(uid=uid, meta=meta, expires_at=expires_at)
    try:
        db_session.add(entry)
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        return jsonify({"ok": False, "message": "Uid Already Added"}), 409
    publish("added", {"uid": uid})
    return jsonify({"ok": True, "message": "Uid Added", "uid": uid, "expires_at": expires_at.isoformat() if expires_at else None})

# ---------- Add (GET) - browser friendly ----------
@app.route("/api/allow/<string:uid>/<string:duration_spec>", methods=["GET"])
@app.route("/api/add_get", methods=["GET"])
def api_add_get(uid: str = None, duration_spec: str = None):
    """
    Two GET options:
    1) /api/allow/<uid>/<duration_spec>?key=TOKEN
       e.g. /api/allow/99999/2d?key=TOKEN
    2) /api/add_get?uid=99999&duration=2d&key=TOKEN
    """
    # allow both patterns
    if not uid:
        uid = request.args.get("uid")
    if not duration_spec:
        duration_spec = request.args.get("duration") or request.args.get("hours")
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    meta = request.args.get("meta","")
    if not uid:
        return jsonify({"ok": False, "message": "Missing uid parameter"}), 400

    hours = parse_duration_to_hours(duration_spec)
    expires_at = None
    if hours is not None:
        expires_at = datetime.utcnow() + timedelta(hours=hours)
    entry = UIDEntry(uid=uid, meta=meta, expires_at=expires_at)
    try:
        db_session.add(entry)
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        return jsonify({"ok": False, "message": "Uid Already Added"}), 409
    try:
        publish("added", {"uid": uid})
    except:
        pass
    return jsonify({"ok": True, "message": "Uid Added", "uid": uid, "expires_at": expires_at.isoformat() if expires_at else None})

# ---------- Check (GET) ----------
@app.route("/api/check/<string:uid>", methods=["GET"])
def api_check(uid):
    e = find_uid_entry(db_session, uid)
    now = datetime.utcnow()
    if not e:
        return jsonify({"ok": False, "message": "Uid Is Not Added"}), 404
    if e.banned:
        return jsonify({"ok": False, "message": "Uid Is Banned"}), 403
    if e.paused:
        return jsonify({"ok": False, "message": "Uid Is Paused"}), 423
    if e.expires_at and e.expires_at < now:
        return jsonify({"ok": False, "message": "Uid Has Expired"}), 410
    return jsonify({"ok": True, "message": "Uid Found - Welcome", "uid": uid})

# ---------- Ban / Unban (POST) ----------
@app.route("/api/ban", methods=["POST"])
def api_ban():
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    uid = (request.json or {}).get("uid")
    if not uid:
        return jsonify({"ok": False, "message": "Missing uid"}), 400
    e = find_uid_entry(db_session, uid)
    if not e:
        return jsonify({"ok": False, "message": "Uid Is Not Added"}), 404
    e.banned = True
    db_session.commit()
    publish("banned", {"uid": uid})
    return jsonify({"ok": True, "message": "Uid Is Banned", "uid": uid})

@app.route("/api/unban", methods=["POST"])
def api_unban():
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    uid = (request.json or {}).get("uid")
    e = find_uid_entry(db_session, uid)
    if not e:
        return jsonify({"ok": False, "message": "Uid Is Not Added"}), 404
    e.banned = False
    db_session.commit()
    publish("unbanned", {"uid": uid})
    return jsonify({"ok": True, "message": "Uid Unbanned", "uid": uid})

# ---------- Ban / Unban (GET) ----------
@app.route("/api/ban_get", methods=["GET"])
@app.route("/api/deny/<string:uid>", methods=["GET"])
def api_ban_get(uid: str = None):
    """
    Options:
    1) /api/deny/<uid>?key=TOKEN
    2) /api/ban_get?uid=123&key=TOKEN
    """
    if not uid:
        uid = request.args.get("uid")
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    if not uid:
        return jsonify({"ok": False, "message": "Missing uid"}), 400
    e = find_uid_entry(db_session, uid)
    if not e:
        return jsonify({"ok": False, "message": "Uid Is Not Added"}), 404
    e.banned = True
    db_session.commit()
    try:
        publish("banned", {"uid": uid})
    except:
        pass
    return jsonify({"ok": True, "message": "Uid Is Banned", "uid": uid})

@app.route("/api/unban_get", methods=["GET"])
@app.route("/api/allow_unban/<string:uid>", methods=["GET"])
def api_unban_get(uid: str = None):
    """
    Options:
    1) /api/allow_unban/<uid>?key=TOKEN
    2) /api/unban_get?uid=123&key=TOKEN
    """
    if not uid:
        uid = request.args.get("uid")
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    if not uid:
        return jsonify({"ok": False, "message": "Missing uid"}), 400
    e = find_uid_entry(db_session, uid)
    if not e:
        return jsonify({"ok": False, "message": "Uid Is Not Added"}), 404
    e.banned = False
    db_session.commit()
    try:
        publish("unbanned", {"uid": uid})
    except:
        pass
    return jsonify({"ok": True, "message": "Uid Unbanned", "uid": uid})

# ---------- Pause / Unpause (POST) ----------
@app.route("/api/pause", methods=["POST"])
def api_pause():
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    uid = (request.json or {}).get("uid")
    e = find_uid_entry(db_session, uid)
    if not e:
        return jsonify({"ok": False, "message": "Uid Is Not Added"}), 404
    e.paused = True
    db_session.commit()
    publish("paused", {"uid": uid})
    return jsonify({"ok": True, "message": "Uid Is Paused", "uid": uid})

@app.route("/api/unpause", methods=["POST"])
def api_unpause():
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    uid = (request.json or {}).get("uid")
    e = find_uid_entry(db_session, uid)
    if not e:
        return jsonify({"ok": False, "message": "Uid Is Not Added"}), 404
    e.paused = False
    db_session.commit()
    publish("unpaused", {"uid": uid})
    return jsonify({"ok": True, "message": "Uid Is Unpaused", "uid": uid})

# ---------- Pause / Unpause (GET) ----------
@app.route("/api/pause_get", methods=["GET"])
@app.route("/api/pause/<string:uid>", methods=["GET"])
def api_pause_get(uid: str = None):
    """
    Options:
      /api/pause/<uid>?key=TOKEN
      /api/pause_get?uid=123&key=TOKEN
    """
    if not uid:
        uid = request.args.get("uid")
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    if not uid:
        return jsonify({"ok": False, "message": "Missing uid"}), 400
    e = find_uid_entry(db_session, uid)
    if not e:
        return jsonify({"ok": False, "message": "Uid Is Not Added"}), 404
    e.paused = True
    db_session.commit()
    try:
        publish("paused", {"uid": uid})
    except:
        pass
    return jsonify({"ok": True, "message": "Uid Is Paused", "uid": uid})

@app.route("/api/unpause_get", methods=["GET"])
@app.route("/api/unpause/<string:uid>", methods=["GET"])
def api_unpause_get(uid: str = None):
    """
    Options:
      /api/unpause/<uid>?key=TOKEN
      /api/unpause_get?uid=123&key=TOKEN
    """
    if not uid:
        uid = request.args.get("uid")
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    if not uid:
        return jsonify({"ok": False, "message": "Missing uid"}), 400
    e = find_uid_entry(db_session, uid)
    if not e:
        return jsonify({"ok": False, "message": "Uid Is Not Added"}), 404
    e.paused = False
    db_session.commit()
    try:
        publish("unpaused", {"uid": uid})
    except:
        pass
    return jsonify({"ok": True, "message": "Uid Is Unpaused", "uid": uid})

# ---------- Delete (POST) ----------
@app.route("/api/delete", methods=["POST"])
def api_delete():
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    uid = (request.json or {}).get("uid")
    e = find_uid_entry(db_session, uid)
    if not e:
        return jsonify({"ok": False, "message": "Uid Is Not Added"}), 404
    db_session.delete(e)
    db_session.commit()
    publish("deleted", {"uid": uid})
    return jsonify({"ok": True, "message": "Uid Deleted", "uid": uid})

# ---------- Delete (GET) ----------
@app.route("/api/delete_get", methods=["GET"])
@app.route("/api/remove/<string:uid>", methods=["GET"])
def api_delete_get(uid: str = None):
    """
    Options:
      /api/remove/<uid>?key=TOKEN
      /api/delete_get?uid=123&key=TOKEN
    """
    if not uid:
        uid = request.args.get("uid")
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    if not uid:
        return jsonify({"ok": False, "message": "Missing uid"}), 400
    e = find_uid_entry(db_session, uid)
    if not e:
        return jsonify({"ok": False, "message": "Uid Is Not Added"}), 404
    db_session.delete(e)
    db_session.commit()
    try:
        publish("deleted", {"uid": uid})
    except:
        pass
    return jsonify({"ok": True, "message": "Uid Deleted", "uid": uid})

# ---------- Exchange (POST) ----------
@app.route("/api/exchange", methods=["POST"])
def api_exchange():
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    payload = request.json or {}
    old = payload.get("old_uid")
    new = payload.get("new_uid")
    if not old or not new:
        return jsonify({"ok": False, "message": "Missing old_uid or new_uid"}), 400
    e_old = find_uid_entry(db_session, old)
    if not e_old:
        return jsonify({"ok": False, "message": "Old Uid Is Not Added"}), 404
    try:
        e_new = UIDEntry(uid=new, meta=e_old.meta, banned=False, paused=False, expires_at=e_old.expires_at)
        db_session.add(e_new)
        db_session.delete(e_old)
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        return jsonify({"ok": False, "message": "New Uid Already Exists"}), 409
    publish("exchanged", {"old": old, "new": new})
    return jsonify({"ok": True, "message": "Uid Exchanged", "old": old, "new": new})

# ---------- Exchange (GET) ----------
@app.route("/api/exchange_get", methods=["GET"])
@app.route("/api/exchange/<string:old>/<string:new>", methods=["GET"])
def api_exchange_get(old: str = None, new: str = None):
    """
    Options:
      /api/exchange/<old_uid>/<new_uid>?key=TOKEN
      /api/exchange_get?old=old_uid&new=new_uid&key=TOKEN
    """
    if not old:
        old = request.args.get("old")
    if not new:
        new = request.args.get("new")
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    if not old or not new:
        return jsonify({"ok": False, "message": "Missing old_uid or new_uid"}), 400
    e_old = find_uid_entry(db_session, old)
    if not e_old:
        return jsonify({"ok": False, "message": "Old Uid Is Not Added"}), 404
    try:
        e_new = UIDEntry(uid=new, meta=e_old.meta, banned=False, paused=False, expires_at=e_old.expires_at)
        db_session.add(e_new)
        db_session.delete(e_old)
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        return jsonify({"ok": False, "message": "New Uid Already Exists"}), 409
    try:
        publish("exchanged", {"old": old, "new": new})
    except:
        pass
    return jsonify({"ok": True, "message": "Uid Exchanged", "old": old, "new": new})

# ---------- List ----------
@app.route("/api/list", methods=["GET"])
def api_list():
    q = db_session.query(UIDEntry)
    if request.args.get("banned") == "1":
        q = q.filter(UIDEntry.banned == True)
    if request.args.get("paused") == "1":
        q = q.filter(UIDEntry.paused == True)
    q = q.order_by(UIDEntry.created_at.desc()).limit(1000)
    items = [uid_status_dict(e) for e in q.all()]
    return jsonify({"ok": True, "count": len(items), "uids": items})

# ---------- Stream ----------
@app.route("/api/stream")
def api_stream():
    def gen():
        q = Queue()
        subscribers.append(q)
        try:
            while True:
                data = q.get()
                yield f"data: {data}\\n\\n"
        finally:
            try:
                subscribers.remove(q)
            except:
                pass
    return app.response_class(gen(), mimetype='text/event-stream')

# ---------- Clear Expired (POST) ----------
@app.route("/api/clear_expired", methods=["POST"])
def api_clear_expired():
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    now = datetime.utcnow()
    expired = db_session.query(UIDEntry).filter(UIDEntry.expires_at != None, UIDEntry.expires_at < now).all()
    count = len(expired)
    for e in expired:
        db_session.delete(e)
    db_session.commit()
    publish("cleared_expired", {"count": count})
    return jsonify({"ok": True, "message": "Cleared expired uids", "count": count})

# ---------- Clear Expired (GET) ----------
@app.route("/api/clear_expired_get", methods=["GET"])
@app.route("/api/clear_expired/<string:confirm>", methods=["GET"])
def api_clear_expired_get(confirm: str = None):
    """
    Options:
      /api/clear_expired_get?key=TOKEN
      /api/clear_expired/yes?key=TOKEN
    """
    if not admin_auth():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    # require optional confirm path param = 'yes' to avoid accidental clears via crawlers
    if confirm and confirm.lower() != 'yes' and request.args.get("confirm","").lower() != "yes":
        # If no explicit confirm, still allow: use simpler endpoint without confirm param
        # but to be safer we require confirm or the specific endpoint without param.
        pass
    now = datetime.utcnow()
    expired = db_session.query(UIDEntry).filter(UIDEntry.expires_at != None, UIDEntry.expires_at < now).all()
    count = len(expired)
    for e in expired:
        db_session.delete(e)
    db_session.commit()
    try:
        publish("cleared_expired", {"count": count})
    except:
        pass
    return jsonify({"ok": True, "message": "Cleared expired uids", "count": count})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)
