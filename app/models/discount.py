import secrets
from datetime import datetime, timezone, timedelta
from app.extensions import db

def utc_now():
    return datetime.now(timezone.utc)

class CandidateDiscount(db.Model):
    """
    Candidate discount voucher generated upon assessment completion.
    Stored locally in SQLite/PostgreSQL and synced to MongoDB collection 'candidate_discounts'.
    """
    __tablename__ = "candidate_discount"

    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_id = db.Column(db.String(36), db.ForeignKey("assessment_attempt.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # 10-digit unique PIN / key
    pin = db.Column(db.String(10), unique=True, nullable=False, index=True)
    
    # Discount percentage (20, 15, 10)
    discount_percent = db.Column(db.Integer, nullable=False)
    
    # Candidate details snapshot
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False, index=True)
    phone = db.Column(db.String(30), nullable=False)
    
    # Assessment score info
    score = db.Column(db.Integer, nullable=False)
    max_score = db.Column(db.Integer, default=20, nullable=False)
    
    # Validity (valid for 3 days)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    valid_days = db.Column(db.Integer, default=3, nullable=False)
    
    is_used = db.Column(db.Boolean, default=False, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    
    # MongoDB sync metadata
    mongo_synced = db.Column(db.Boolean, default=False, nullable=False)
    mongo_id = db.Column(db.String(50), nullable=True)

    # Relationships
    candidate = db.relationship("Candidate", backref=db.backref("discounts", lazy=True, cascade="all, delete-orphan", order_by="CandidateDiscount.created_at.desc()"))
    attempt = db.relationship("AssessmentAttempt", backref=db.backref("discount", uselist=False, cascade="all, delete-orphan"))

    def is_active(self):
        now = utc_now()
        exp = self.expires_at.replace(tzinfo=timezone.utc) if self.expires_at.tzinfo is None else self.expires_at
        return (not self.is_used) and (now <= exp)

    def hours_until_expiration(self):
        now = utc_now()
        exp = self.expires_at.replace(tzinfo=timezone.utc) if self.expires_at.tzinfo is None else self.expires_at
        diff = (exp - now).total_seconds()
        return max(0, int(diff // 3600))

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "score": self.score,
            "max_score": self.max_score,
            "discount_percent": self.discount_percent,
            "pin": self.pin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "valid_days": self.valid_days,
            "is_used": self.is_used,
            "is_active": self.is_active(),
            "mongo_synced": self.mongo_synced,
            "mongo_id": self.mongo_id
        }

    def __repr__(self):
        return f"<CandidateDiscount {self.email}: {self.discount_percent}% (PIN: {self.pin})>"
