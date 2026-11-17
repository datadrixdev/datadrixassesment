from app.extensions import db

class Question(db.Model):
    """Question item in the question bank."""
    __tablename__ = "question"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    section = db.Column(db.String(50), nullable=False, index=True)
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.Text, nullable=False)
    option_b = db.Column(db.Text, nullable=False)
    option_c = db.Column(db.Text, nullable=False)
    option_d = db.Column(db.Text, nullable=False)
    correct_option = db.Column(db.String(1), nullable=False)  # "A", "B", "C", "D"
    explanation = db.Column(db.Text, nullable=True)
    difficulty = db.Column(db.String(20), default="Medium")
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def to_public_dict(self):
        """Returns question data for active assessment, strictly concealing answer and explanation."""
        return {
            "code": self.code,
            "section": self.section,
            "question_text": self.question_text,
            "options": {
                "A": self.option_a,
                "B": self.option_b,
                "C": self.option_c,
                "D": self.option_d,
            },
            "difficulty": self.difficulty
        }

    def __repr__(self):
        return f"<Question {self.code}: {self.section}>"
