from datetime import datetime, timezone
from app.extensions import db

def utc_now():
    return datetime.now(timezone.utc)

class Candidate(db.Model):
    """Candidate registered for the assessment."""
    __tablename__ = "candidate"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False, index=True)
    mobile_number = db.Column(db.String(30), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    # Relationships
    attempts = db.relationship("AssessmentAttempt", back_populates="candidate", cascade="all, delete-orphan", order_by="AssessmentAttempt.attempt_number.desc()")

    def __repr__(self):
        return f"<Candidate {self.id}: {self.email}>"
