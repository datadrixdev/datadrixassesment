import re
from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, SelectField
from wtforms.validators import DataRequired, Email, Length, ValidationError

# Clean country choices without emoji flags (avoids 'IN', 'US' raw regional indicator text on Windows)
COUNTRY_CHOICES = [
    ("", "Select Country / Region"),
    ("+91", "India (+91)"),
    ("+1", "United States (+1)"),
    ("+1-CA", "Canada (+1)"),
    ("+44", "United Kingdom (+44)"),
    ("+61", "Australia (+61)"),
    ("+971", "UAE (+971)"),
    ("+65", "Singapore (+65)"),
    ("+49", "Germany (+49)"),
    ("+33", "France (+33)"),
    ("+966", "Saudi Arabia (+966)"),
    ("+60", "Malaysia (+60)"),
    ("+81", "Japan (+81)"),
    ("+880", "Bangladesh (+880)"),
    ("+977", "Nepal (+977)"),
    ("+234", "Nigeria (+234)"),
    ("+27", "South Africa (+27)"),
    ("+41", "Switzerland (+41)"),
    ("+31", "Netherlands (+31)"),
    ("+353", "Ireland (+353)"),
    ("+64", "New Zealand (+64)"),
    ("+974", "Qatar (+974)"),
    ("+968", "Oman (+968)"),
    ("+965", "Kuwait (+965)"),
    ("+55", "Brazil (+55)"),
    ("+48", "Poland (+48)"),
    ("+46", "Sweden (+46)"),
    ("+34", "Spain (+34)"),
    ("+39", "Italy (+39)")
]

class CandidateRegistrationForm(FlaskForm):
    """Candidate registration form with strict server-side validation and region selection."""
    
    full_name = StringField(
        "Full Name",
        validators=[
            DataRequired(message="Full name is required."),
            Length(min=2, max=100, message="Full name must be between 2 and 100 characters.")
        ]
    )
    
    email = StringField(
        "Email Address",
        validators=[
            DataRequired(message="Email address is required."),
            Email(message="Please enter a valid email address."),
            Length(max=120, message="Email address cannot exceed 120 characters.")
        ]
    )

    country_code = SelectField(
        "Country / Region",
        choices=COUNTRY_CHOICES,
        validators=[
            DataRequired(message="Please select your country/region code.")
        ]
    )
    
    mobile_number = StringField(
        "Mobile Number",
        validators=[
            DataRequired(message="Mobile number is required."),
            Length(min=6, max=18, message="Mobile number must be between 6 and 18 digits.")
        ]
    )
    
    consent = BooleanField(
        "Assessment Consent",
        validators=[
            DataRequired(message="You must agree to the assessment instructions and privacy notice.")
        ]
    )

    def validate_full_name(self, field):
        cleaned = field.data.strip() if field.data else ""
        if not re.match(r"^[A-Za-z\s\.\'\-]+$", cleaned):
            raise ValidationError("Full name may only contain letters, spaces, hyphens, and periods.")
        if len(cleaned.split()) < 1 or len(cleaned) < 2:
            raise ValidationError("Please provide a valid full name.")

    def validate_country_code(self, field):
        if not field.data or not field.data.strip():
            raise ValidationError("Please select your country / region code.")

    def validate_mobile_number(self, field):
        raw = field.data.strip() if field.data else ""
        digits_only = re.sub(r"\D", "", raw)
        if len(digits_only) < 6 or len(digits_only) > 15:
            raise ValidationError("Mobile number must contain between 6 and 15 digits.")
