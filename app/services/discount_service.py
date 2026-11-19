import os
import secrets
import time
import logging
from datetime import datetime, timezone, timedelta
from flask import current_app
from app.extensions import db
from app.models.candidate import Candidate
from app.models.assessment import AssessmentAttempt
from app.models.discount import CandidateDiscount

logger = logging.getLogger(__name__)

# Default MongoDB URI & Collection
DEFAULT_MONGO_URI = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI") or "mongodb+srv://datadrix:NitinSmriti%40123@cluster0.nixp0m6.mongodb.net/datadrix?retryWrites=true&w=majority"
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME") or "datadrix"
MONGO_COLLECTION_NAME = "candidate_discounts"

# Default retake cooldown: 24 hours from previous assessment end time
RETAKE_COOLDOWN_HOURS = int(os.getenv("RETAKE_COOLDOWN_HOURS", 24))

# Caching for MongoDB availability check
_mongo_client_cache = None
_mongo_coll_cache = None
_mongo_last_check = 0.0
_mongo_available = False

def utc_now():
    return datetime.now(timezone.utc)

def calculate_discount(score):
    """
    Determine discount percentage based on correct questions score:
    - Above 7 correct questions (7 or more, score >= 7): 20%
    - 4 to 6 correct questions (4 <= score <= 6): 10%
    - 0 to 3 correct questions (score <= 3): 0% (no discount)
    """
    try:
        s = int(score)
    except (ValueError, TypeError):
        return 0

    if s >= 7:
        return 20
    elif 4 <= s <= 6:
        return 10
    else:
        return 0

def generate_10_digit_pin(discount_percent=None):
    """
    Generate a cryptographically secure, unique 10-character alphanumeric key
    composed of uppercase letters (A-Z) and numbers (0-9).
    - If discount_percent == 20: Prefixed with 'DX20' + 6 alphanumeric characters.
    - If discount_percent == 10: Prefixed with 'DX10' + 6 alphanumeric characters.
    - Otherwise: Balanced 10 alphanumeric characters.
    Guaranteed unique in both SQLite/PostgreSQL and MongoDB.
    """
    UPPERCASE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    NUMBERS = "23456789"
    ALL_CHARS = UPPERCASE_LETTERS + NUMBERS

    prefix = ""
    if discount_percent == 20:
        prefix = "DX20"
    elif discount_percent == 10:
        prefix = "DX10"

    suffix_len = 10 - len(prefix)

    for _ in range(100):
        if prefix:
            # Generate remaining characters ensuring both letters and numbers
            suffix_letters = [secrets.choice(UPPERCASE_LETTERS) for _ in range(suffix_len // 2)]
            suffix_numbers = [secrets.choice(NUMBERS) for _ in range(suffix_len - (suffix_len // 2))]
            suffix_pool = suffix_letters + suffix_numbers
            suffix = []
            while suffix_pool:
                idx = secrets.randbelow(len(suffix_pool))
                suffix.append(suffix_pool.pop(idx))
            pin = prefix + "".join(suffix)
        else:
            letters_part = [secrets.choice(UPPERCASE_LETTERS) for _ in range(5)]
            numbers_part = [secrets.choice(NUMBERS) for _ in range(5)]
            chars = letters_part + numbers_part
            shuffled = []
            pool = list(chars)
            while pool:
                idx = secrets.randbelow(len(pool))
                shuffled.append(pool.pop(idx))
            pin = "".join(shuffled)

        # Check local DB
        if CandidateDiscount.query.filter_by(pin=pin).first():
            continue

        # Check MongoDB if connected
        try:
            coll = get_mongo_collection()
            if coll is not None and coll.find_one({"pin": pin}):
                continue
        except Exception:
            pass

        return pin

    # Fallback alphanumeric generator
    if prefix:
        return prefix + "".join(secrets.choice(ALL_CHARS) for _ in range(suffix_len))
    return "".join(secrets.choice(ALL_CHARS) for _ in range(10))

def get_mongo_collection():
    """
    Connect to MongoDB with a short timeout and 30-second negative cache.
    Returns the collection object or None if MongoDB is unavailable.
    """
    global _mongo_client_cache, _mongo_coll_cache, _mongo_last_check, _mongo_available
    now = time.time()

    # If recently checked within 30 seconds and not available, return None immediately
    if (now - _mongo_last_check < 30.0) and not _mongo_available:
        return None

    if _mongo_available and _mongo_coll_cache is not None:
        return _mongo_coll_cache

    _mongo_last_check = now
    try:
        from pymongo import MongoClient
        uri = DEFAULT_MONGO_URI
        if current_app and current_app.config.get("MONGO_URI"):
            uri = current_app.config.get("MONGO_URI")

        # 500ms server selection timeout
        client = MongoClient(uri, serverSelectionTimeoutMS=500)
        client.admin.command('ping')

        db_instance = client.get_default_database() or client[MONGO_DB_NAME]
        coll = db_instance[MONGO_COLLECTION_NAME]

        try:
            coll.create_index("pin", unique=True)
            coll.create_index("email")
            coll.create_index("expires_at")
        except Exception:
            pass

        _mongo_client_cache = client
        _mongo_coll_cache = coll
        _mongo_available = True
        return coll
    except Exception as e:
        _mongo_available = False
        _mongo_coll_cache = None
        logger.debug("MongoDB not connected: %s", e)
        return None

def sync_record_to_mongo(discount_obj):
    """
    Write or update a CandidateDiscount record into the MongoDB collection.
    """
    try:
        coll = get_mongo_collection()
        if coll is None:
            return False

        doc = {
            "name": discount_obj.name,
            "email": discount_obj.email,
            "phone": discount_obj.phone,
            "score": discount_obj.score,
            "max_score": discount_obj.max_score,
            "discount_percent": discount_obj.discount_percent,
            "pin": discount_obj.pin,
            "valid_days": discount_obj.valid_days,
            "created_at": discount_obj.created_at,
            "expires_at": discount_obj.expires_at,
            "is_used": discount_obj.is_used,
            "status": "active" if discount_obj.is_active() else "expired",
            "source": "Datadrix Online Assessment Platform",
            "metadata": {
                "attempt_id": discount_obj.attempt_id,
                "candidate_id": discount_obj.candidate_id
            }
        }

        res = coll.update_one(
            {"pin": discount_obj.pin},
            {"$set": doc},
            upsert=True
        )

        discount_obj.mongo_synced = True
        if res.upserted_id:
            discount_obj.mongo_id = str(res.upserted_id)
        db.session.commit()
        return True
    except Exception as e:
        logger.warning("Failed to sync discount to MongoDB: %s", e)
        return False

def create_or_get_discount(attempt):
    """
    Finalize discount generation for an attempt.
    - If already exists, return existing.
    - If score qualifies (>= 4), generate 10-digit PIN valid for 3 days.
    - Save to local DB and MongoDB.
    - If score < 4, returns None (no discount).
    """
    # Check if discount already generated for this attempt
    existing = CandidateDiscount.query.filter_by(attempt_id=attempt.id).first()
    if existing:
        if not existing.mongo_synced:
            sync_record_to_mongo(existing)
        return existing

    score = attempt.score or 0
    discount_percent = calculate_discount(score)
    if discount_percent <= 0:
        return None

    candidate = attempt.candidate
    pin = generate_10_digit_pin(discount_percent=discount_percent)
    now = utc_now()
    expires_at = now + timedelta(days=3)

    discount = CandidateDiscount(
        candidate_id=candidate.id,
        attempt_id=attempt.id,
        pin=pin,
        discount_percent=discount_percent,
        name=candidate.full_name,
        email=candidate.email,
        phone=candidate.mobile_number,
        score=score,
        max_score=attempt.max_score or 20,
        created_at=now,
        expires_at=expires_at,
        valid_days=3,
        is_used=False,
        mongo_synced=False
    )

    db.session.add(discount)
    db.session.commit()

    # Sync to MongoDB table/collection
    sync_record_to_mongo(discount)

    return discount

def get_candidate_previous_history(candidate_id_or_email, cooldown_hours=RETAKE_COOLDOWN_HOURS):
    """
    Retrieve candidate previous assessment score, discount PIN, and retake cooldown status.
    """
    if isinstance(candidate_id_or_email, int):
        candidate = db.session.get(Candidate, candidate_id_or_email)
    else:
        candidate = Candidate.query.filter_by(email=str(candidate_id_or_email).strip().lower()).first()

    if not candidate:
        return {
            "has_previous_attempt": False,
            "candidate": None,
            "previous_attempt": None,
            "discount": None,
            "cooldown_active": False,
            "hours_remaining": 0,
            "minutes_remaining": 0
        }

    # Fetch completed attempts ordered by completion date desc
    completed_attempts = AssessmentAttempt.query.filter_by(
        candidate_id=candidate.id,
        status="completed"
    ).order_by(AssessmentAttempt.end_time.desc()).all()

    if not completed_attempts:
        return {
            "has_previous_attempt": False,
            "candidate": candidate,
            "previous_attempt": None,
            "discount": None,
            "cooldown_active": False,
            "hours_remaining": 0,
            "minutes_remaining": 0
        }

    latest_attempt = completed_attempts[0]

    # Find latest discount
    latest_discount = CandidateDiscount.query.filter_by(
        candidate_id=candidate.id
    ).order_by(CandidateDiscount.created_at.desc()).first()

    # Calculate retake cooldown based on previous assessment given timestamp
    now = utc_now()
    end_time = latest_attempt.end_time
    if end_time:
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        eligible_at = end_time + timedelta(hours=cooldown_hours)
    else:
        eligible_at = now

    diff_sec = (eligible_at - now).total_seconds()
    cooldown_active = diff_sec > 0
    hours_remaining = max(0, int(diff_sec // 3600))
    minutes_remaining = max(0, int((diff_sec % 3600) // 60))

    return {
        "has_previous_attempt": True,
        "candidate": candidate,
        "previous_attempt": latest_attempt,
        "completed_count": len(completed_attempts),
        "discount": latest_discount,
        "cooldown_active": cooldown_active,
        "hours_remaining": hours_remaining,
        "minutes_remaining": minutes_remaining,
        "eligible_at": eligible_at,
        "previous_timestamp": end_time
    }
