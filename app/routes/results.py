from flask import Blueprint, render_template, redirect, url_for, session, abort
from app.extensions import db
from app.models.assessment import AssessmentAttempt
from app.services.scoring_service import get_section_scores
from app.services.timer_service import check_and_enforce_timer
from app.services.discount_service import create_or_get_discount, get_candidate_previous_history

results_bp = Blueprint("results", __name__)

def verify_candidate_attempt(attempt_id):
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return None, redirect(url_for("main.index"))

    attempt = db.session.get(AssessmentAttempt, attempt_id)
    if not attempt:
        from app.services.rehydration_service import rehydrate_attempt_if_needed
        attempt = rehydrate_attempt_if_needed(attempt_id)

    if not attempt:
        abort(404)

    if attempt.candidate_id != candidate_id:
        abort(403)

    return attempt, None

@results_bp.route("/result/<attempt_id>", methods=["GET"])
def result_view(attempt_id):
    """
    Display completed assessment performance report and competency analysis.
    Per user specification: Once test is done, questions and answer keys are not displayed;
    only the comprehensive assessment reports, scorecards, and domain analytics are shown.
    """
    attempt, redirect_resp = verify_candidate_attempt(attempt_id)
    if redirect_resp:
        return redirect_resp

    if attempt.status == "aborted":
        return redirect(url_for("results.aborted_view", attempt_id=attempt.id))

    from app.services.scoring_service import finalize_and_score_attempt
    finalize_and_score_attempt(attempt.id)

    section_scores = get_section_scores(attempt)

    # Calculate domain competency levels for each section
    for sec in section_scores:
        pct = sec["percentage"]
        if pct >= 80:
            sec["competency"] = "Advanced Mastery"
            sec["badge_class"] = "bg-success text-success border-success"
            sec["description"] = "Demonstrates superior problem formulation, speed, and precision in this domain."
        elif pct >= 60:
            sec["competency"] = "Proficient"
            sec["badge_class"] = "bg-info text-cyan border-info"
            sec["description"] = "Demonstrates consistent conceptual grasp and strong quantitative execution."
        elif pct >= 40:
            sec["competency"] = "Developing"
            sec["badge_class"] = "bg-warning text-warning border-warning"
            sec["description"] = "Sound foundational grasp; additional practice recommended for speed."
        else:
            sec["competency"] = "Needs Focus"
            sec["badge_class"] = "bg-danger text-danger border-danger"
            sec["description"] = "Targeted domain revision recommended to strengthen key principles."

    # Determine overall performance grade
    pct = attempt.percentage
    if pct >= 85:
        grade = "Advanced Mastery"
        grade_badge = "bg-success bg-opacity-20 text-success border border-success border-opacity-30"
        summary_text = "Exceptional performance across all evaluation pillars. Demonstrates outstanding analytical ability, quantitative aptitude, and grammatical accuracy."
    elif pct >= 70:
        grade = "Proficient"
        grade_badge = "bg-primary bg-opacity-20 text-cyan border border-info border-opacity-30"
        summary_text = "Strong performance reflecting solid reasoning, well-developed quantitative methods, and dependable language command."
    elif pct >= 50:
        grade = "Average / Foundational"
        grade_badge = "bg-warning bg-opacity-20 text-warning border border-warning border-opacity-30"
        summary_text = "Satisfactory baseline performance with strong potential for advancement through targeted review in slower sections."
    else:
        grade = "Needs Improvement"
        grade_badge = "badge-grade-needs-improvement"
        summary_text = "Results indicate significant opportunity for growth. Further study of fundamental aptitude and reasoning concepts is strongly advised."

    # Generate or fetch 10-digit discount voucher based on score
    discount = create_or_get_discount(attempt)

    # Fetch candidate previous attempt history and retake cooldown
    candidate_history = get_candidate_previous_history(attempt.candidate_id)

    # Check email delivery audit status
    import json
    from app.models.assessment import AssessmentEvent
    email_event = AssessmentEvent.query.filter_by(
        attempt_id=attempt.id,
        event_type="ASSESSMENT_REPORT_EMAILED"
    ).order_by(AssessmentEvent.timestamp.desc()).first()

    email_delivery_status = "none"
    if email_event and email_event.metadata_json:
        try:
            m = json.loads(email_event.metadata_json)
            email_delivery_status = m.get("delivery_status", "unknown")
        except Exception:
            pass

    return render_template(
        "result.html",
        attempt=attempt,
        section_scores=section_scores,
        grade=grade,
        grade_badge=grade_badge,
        summary_text=summary_text,
        candidate_name=session.get("candidate_name", "Candidate"),
        discount=discount,
        candidate_history=candidate_history,
        email_delivery_status=email_delivery_status
    )

@results_bp.route("/result/<attempt_id>/resend-email", methods=["POST"])
def resend_email_route(attempt_id):
    """Manually trigger or retry sending assessment result email."""
    attempt, redirect_resp = verify_candidate_attempt(attempt_id)
    if redirect_resp:
        return redirect_resp
    from app.services.email_service import send_assessment_result_email
    res = send_assessment_result_email(attempt)
    from flask import flash
    if res and res.get("status") == "sent":
        flash(f"Assessment report successfully sent to {attempt.candidate.email}!", "success")
    elif res and res.get("status") == "smtp_failed":
        flash(f"SMTP delivery failed: {res.get('error', 'Authentication rejected by mail server')}", "danger")
    else:
        flash(f"Report generated and saved locally (SMTP server not configured).", "info")
    return redirect(url_for("results.result_view", attempt_id=attempt.id))

@results_bp.route("/result/<attempt_id>/email-preview", methods=["GET"])
def result_email_preview(attempt_id):
    """Render the exact HTML email report sent to the candidate."""
    from flask import request
    attempt, redirect_resp = verify_candidate_attempt(attempt_id)
    if redirect_resp:
        return redirect_resp

    from app.services.email_service import generate_result_email_html
    from app.services.scoring_service import get_section_scores
    from app.models.discount import CandidateDiscount

    section_scores = get_section_scores(attempt)
    discount = CandidateDiscount.query.filter_by(attempt_id=attempt.id).first()
    html_content = generate_result_email_html(
        attempt.candidate, attempt, section_scores, discount,
        base_url=request.host_url
    )
    return html_content, 200, {"Content-Type": "text/html; charset=utf-8"}

@results_bp.route("/aborted", methods=["GET"])
@results_bp.route("/aborted/<attempt_id>", methods=["GET"])
def aborted_view(attempt_id=None):
    """Display the integrity violation termination screen with retake action."""
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return redirect(url_for("main.index"))

    if attempt_id:
        attempt, redirect_resp = verify_candidate_attempt(attempt_id)
        if redirect_resp:
            return redirect_resp
    else:
        # Find candidate's most recent attempt
        attempt = AssessmentAttempt.query.filter_by(
            candidate_id=candidate_id
        ).order_by(AssessmentAttempt.start_time.desc()).first()
        if not attempt:
            return redirect(url_for("main.index"))

    if attempt.status == "completed":
        return redirect(url_for("results.result_view", attempt_id=attempt.id))

    return render_template(
        "aborted.html",
        attempt=attempt,
        candidate_name=session.get("candidate_name", "Candidate")
    )
