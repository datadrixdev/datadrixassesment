import os
import json
import random
from app.extensions import db
from app.models.question import Question
from app.models.assessment import AttemptQuestion

SECTION_NAMES = [
    "Reasoning",
    "General Aptitude",
    "Logical Reasoning",
    "English Grammar"
]

def seed_questions_from_file(filepath=None):
    """Seed the Question table from the questions.json file if empty or missing questions."""
    if filepath is None:
        base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        filepath = os.path.join(base_dir, "seed", "questions.json")

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Questions seed file not found at: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    inserted = 0
    for item in data:
        existing = Question.query.filter_by(code=item["code"]).first()
        if not existing:
            q = Question(
                code=item["code"],
                section=item["section"],
                question_text=item["question_text"],
                option_a=item["option_a"],
                option_b=item["option_b"],
                option_c=item["option_c"],
                option_d=item["option_d"],
                correct_option=item["correct_option"],
                explanation=item.get("explanation"),
                difficulty=item.get("difficulty", "Medium"),
                is_active=True
            )
            db.session.add(q)
            inserted += 1

    if inserted > 0:
        db.session.commit()
    return inserted

def generate_questions_for_attempt(attempt, questions_per_section=5):
    """
    Select exactly 5 random active questions from each of the 4 sections,
    creating exactly 20 AttemptQuestion records for the attempt.
    """
    selected_questions = []

    for section in SECTION_NAMES:
        available = Question.query.filter_by(section=section, is_active=True).all()
        if len(available) < questions_per_section:
            raise ValueError(f"Insufficient active questions for section '{section}': found {len(available)}, required {questions_per_section}")
        chosen = random.sample(available, questions_per_section)
        selected_questions.extend(chosen)

    # Maintain section groupings with order 1..20
    created_attempt_questions = []
    for order, q in enumerate(selected_questions, start=1):
        aq = AttemptQuestion(
            attempt_id=attempt.id,
            question_id=q.id,
            question_order=order,
            selected_option=None,
            is_marked_for_review=False
        )
        db.session.add(aq)
        created_attempt_questions.append(aq)

    db.session.commit()
    return created_attempt_questions

def get_candidate_assessment_payload(attempt):
    """
    Returns candidate-facing assessment data:
    - Attempt ID, timing, candidate info
    - Exactly 20 questions WITHOUT correct answers or explanations
    - Current selected answers and review statuses
    """
    attempt_questions = AttemptQuestion.query.filter_by(attempt_id=attempt.id).order_by(AttemptQuestion.question_order.asc()).all()
    questions_list = []

    for aq in attempt_questions:
        q = aq.question
        questions_list.append({
            "order": aq.question_order,
            "section": q.section,
            "question_text": q.question_text,
            "options": {
                "A": q.option_a,
                "B": q.option_b,
                "C": q.option_c,
                "D": q.option_d
            },
            "selected_option": aq.selected_option,
            "is_marked_for_review": aq.is_marked_for_review
        })

    return questions_list

def get_attempt_review_data(attempt):
    """
    Returns detailed review data for a completed attempt:
    - Question text, options, candidate answer, correct answer, explanation, correctness
    """
    attempt_questions = AttemptQuestion.query.filter_by(attempt_id=attempt.id).order_by(AttemptQuestion.question_order.asc()).all()
    review_items = []

    for aq in attempt_questions:
        q = aq.question
        is_correct = (aq.selected_option == q.correct_option) if aq.selected_option else False
        is_unanswered = aq.selected_option is None

        review_items.append({
            "order": aq.question_order,
            "section": q.section,
            "question_text": q.question_text,
            "options": {
                "A": q.option_a,
                "B": q.option_b,
                "C": q.option_c,
                "D": q.option_d
            },
            "selected_option": aq.selected_option,
            "correct_option": q.correct_option,
            "explanation": q.explanation,
            "is_correct": is_correct,
            "is_unanswered": is_unanswered,
            "status": "correct" if is_correct else ("unanswered" if is_unanswered else "incorrect")
        })

    return review_items
