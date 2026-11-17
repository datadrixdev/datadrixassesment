from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app.extensions import db
from app.models.candidate import Candidate
from app.forms import CandidateRegistrationForm
from app.services.discount_service import get_candidate_previous_history

main_bp = Blueprint("main", __name__)

@main_bp.route("/", methods=["GET"])
def index():
    """Candidate landing and registration page."""
    # Reset candidate session on landing page to ensure a clean slate
    session.pop("candidate_id", None)
    session.pop("candidate_name", None)
    session.pop("candidate_email", None)
    form = CandidateRegistrationForm()
    return render_template("index.html", form=form)

@main_bp.route("/api/candidate/lookup", methods=["GET"])
def candidate_lookup():
    """
    Look up previous test results, 10-digit discount PIN, and retake cooldown for an email.
    Called in real-time as candidate enters email on registration screen.
    """
    email = request.args.get("email", "").strip().lower()
    if not email:
        return jsonify({"found": False})

    history = get_candidate_previous_history(email)
    if not history["has_previous_attempt"]:
        return jsonify({"found": False})

    prev = history["previous_attempt"]
    disc = history["discount"]
    cand = history["candidate"]

    return jsonify({
        "found": True,
        "full_name": cand.full_name,
        "email": cand.email,
        "score": prev.score,
        "max_score": prev.max_score,
        "percentage": round(prev.percentage, 1),
        "completed_count": history.get("completed_count", 1),
        "completed_at": prev.end_time.strftime("%b %d, %Y at %I:%M %p UTC") if prev.end_time else None,
        "has_discount": bool(disc and disc.discount_percent > 0),
        "discount_percent": disc.discount_percent if disc else 0,
        "pin": disc.pin if disc else None,
        "pin_expires_at": disc.expires_at.strftime("%b %d, %Y at %I:%M %p UTC") if disc else None,
        "pin_is_active": disc.is_active() if disc else False,
        "cooldown_active": history["cooldown_active"],
        "hours_remaining": history["hours_remaining"],
        "minutes_remaining": history["minutes_remaining"],
        "eligible_at": history["eligible_at"].strftime("%b %d, %Y at %I:%M %p UTC") if history.get("eligible_at") else None
    })

@main_bp.route("/register", methods=["POST"])
def register():
    """Process candidate registration, normalize inputs, and establish candidate session."""
    form = CandidateRegistrationForm()
    if form.validate_on_submit():
        # Server-side normalization
        full_name = " ".join(form.full_name.data.strip().split()).title()
        email = form.email.data.strip().lower()
        country_code = form.country_code.data.strip() if form.country_code.data else ""
        if country_code == "+1-CA":
            clean_code = "+1"
        else:
            clean_code = country_code

        raw_digits = "".join(ch for ch in form.mobile_number.data.strip() if ch.isdigit())

        # Combine country code and national digits
        if clean_code and not raw_digits.startswith(clean_code.replace("+", "")):
            mobile_number = f"{clean_code} {raw_digits}"
        elif clean_code:
            mobile_number = f"+{raw_digits}"
        else:
            mobile_number = raw_digits

        # Find or create candidate
        candidate = Candidate.query.filter_by(email=email).first()
        if not candidate:
            candidate = Candidate(
                full_name=full_name,
                email=email,
                mobile_number=mobile_number
            )
            db.session.add(candidate)
            db.session.commit()
        else:
            # Update name and mobile if changed
            candidate.full_name = full_name
            candidate.mobile_number = mobile_number
            db.session.commit()

        # Store candidate in secure session
        session["candidate_id"] = candidate.id
        session["candidate_name"] = candidate.full_name
        session["candidate_email"] = candidate.email
        session.permanent = True

        return redirect(url_for("main.device_check"))

    # Return landing with validation errors
    return render_template("index.html", form=form), 400

@main_bp.route("/device-check", methods=["GET"])
def device_check():
    """Display the pre-assessment camera and microphone verification screen."""
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        flash("Please register your details before proceeding to the device check.", "warning")
        return redirect(url_for("main.index"))

    candidate = db.session.get(Candidate, candidate_id)
    if not candidate:
        session.clear()
        return redirect(url_for("main.index"))

    history = get_candidate_previous_history(candidate.id)
    return render_template("device_check.html", candidate=candidate, history=history)
