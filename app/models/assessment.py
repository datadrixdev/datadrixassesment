import uuid
from datetime import datetime, timezone
from app.extensions import db

def utc_now():
    return datetime.now(timezone.utc)

class AssessmentAttempt(db.Model):
    """An individual assessment attempt by a candidate."""
    __tablename__ = "assessment_attempt"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id = db.Column(db.Integer, db.ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number = db.Column(db.Integer, default=1, nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    deadline = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default="in_progress", nullable=False)  # "in_progress", "completed", "aborted"
    violation_count = db.Column(db.Integer, default=0, nullable=False)  # Navigation/tab-switch strikes
    vision_warning_count = db.Column(db.Integer, default=0, nullable=False)  # Vision AI proctoring warnings
    score = db.Column(db.Integer, default=0, nullable=False)
    max_score = db.Column(db.Integer, default=20, nullable=False)
    correct_count = db.Column(db.Integer, default=0, nullable=False)
    incorrect_count = db.Column(db.Integer, default=0, nullable=False)
    unanswered_count = db.Column(db.Integer, default=20, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    # Relationships
    candidate = db.relationship("Candidate", back_populates="attempts")
    attempt_questions = db.relationship(
        "AttemptQuestion",
        back_populates="attempt",
        cascade="all, delete-orphan",
        order_by="AttemptQuestion.question_order.asc()"
    )
    events = db.relationship(
        "AssessmentEvent",
        back_populates="attempt",
        cascade="all, delete-orphan",
        order_by="AssessmentEvent.timestamp.asc()"
    )
    proctoring_events = db.relationship(
        "ProctoringEvent",
        back_populates="attempt",
        cascade="all, delete-orphan",
        order_by="ProctoringEvent.timestamp.asc()"
    )

    @property
    def percentage(self):
        if self.max_score <= 0:
            return 0.0
        return round((self.score / self.max_score) * 100, 1)

    @property
    def is_expired(self):
        return utc_now() >= self.deadline.replace(tzinfo=timezone.utc) if self.deadline.tzinfo is None else utc_now() >= self.deadline

    def remaining_seconds(self):
        now = utc_now()
        dl = self.deadline.replace(tzinfo=timezone.utc) if self.deadline.tzinfo is None else self.deadline
        diff = (dl - now).total_seconds()
        return max(0, int(diff))

    def __repr__(self):
        return f"<AssessmentAttempt {self.id} (Candidate {self.candidate_id}, Status: {self.status})>"

class AttemptQuestion(db.Model):
    """Link between an attempt and a selected question with the candidate's answer."""
    __tablename__ = "attempt_question"
    __table_args__ = (
        db.UniqueConstraint("attempt_id", "question_order", name="uq_attempt_question_order"),
    )

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.String(36), db.ForeignKey("assessment_attempt.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    question_order = db.Column(db.Integer, nullable=False)  # 1 to 20
    selected_option = db.Column(db.String(1), nullable=True)  # "A", "B", "C", "D" or None
    is_marked_for_review = db.Column(db.Boolean, default=False, nullable=False)
    answered_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    attempt = db.relationship("AssessmentAttempt", back_populates="attempt_questions")
    question = db.relationship("Question")

    def __repr__(self):
        return f"<AttemptQuestion Attempt {self.attempt_id} Q#{self.question_order}: {self.selected_option}>"

class AssessmentEvent(db.Model):
    """Audit log of security, status, and integrity events during an assessment."""
    __tablename__ = "assessment_event"

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.String(36), db.ForeignKey("assessment_attempt.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = db.Column(db.String(50), nullable=False)  # e.g., "SESSION_STARTED", "VIOLATION_WARNING", "VIOLATION_ABORT"
    timestamp = db.Column(db.DateTime, default=utc_now, nullable=False)
    metadata_json = db.Column(db.Text, nullable=True)

    # Relationships
    attempt = db.relationship("AssessmentAttempt", back_populates="events")

    def __repr__(self):
        return f"<AssessmentEvent {self.attempt_id} {self.event_type} at {self.timestamp}>"

class ProctoringEvent(db.Model):
    """
    Dedicated audit table for browser-based AI vision proctoring detections.
    Tracks mobile phone detections, head movement deviations, and hardware status.
    """
    __tablename__ = "proctoring_event"

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.String(36), db.ForeignKey("assessment_attempt.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = db.Column(db.String(60), nullable=False, index=True)
    confidence = db.Column(db.Float, nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)
    client_event_id = db.Column(db.String(100), nullable=True, index=True)
    metadata_json = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=utc_now, nullable=False)

    # Relationship back to attempt
    attempt = db.relationship("AssessmentAttempt", back_populates="proctoring_events")

    def __repr__(self):
        return f"<ProctoringEvent {self.attempt_id} {self.event_type} (conf={self.confidence}) at {self.timestamp}>"
