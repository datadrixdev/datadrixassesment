/**
 * Registration Screen Client-Side Validation, Region Selector & Double-Click Prevention
 */
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("registrationForm");
  const fullName = document.getElementById("fullName");
  const emailAddress = document.getElementById("emailAddress");
  const countryCode = document.getElementById("countryCode");
  const mobileNumber = document.getElementById("mobileNumber");
  const selectedCodePrefix = document.getElementById("selectedCodePrefix");
  const consentCheckbox = document.getElementById("consentCheckbox");
  const startBtn = document.getElementById("startAssessmentBtn");
  const btnText = document.getElementById("btnText");
  const btnIcon = document.getElementById("btnIcon");
  const btnSpinner = document.getElementById("btnSpinner");

  let isSubmitting = false;

  // Validation Patterns
  const namePattern = /^[A-Za-z\s\.\'\-]{2,100}$/;
  const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function validateFullName() {
    const val = fullName.value.trim();
    const isValid = namePattern.test(val);
    toggleValidationClass(fullName, isValid);
    return isValid;
  }

  function validateEmail() {
    const val = emailAddress.value.trim();
    const isValid = emailPattern.test(val);
    toggleValidationClass(emailAddress, isValid);
    return isValid;
  }

  function validateCountryCode() {
    const code = countryCode ? countryCode.value.trim() : "";
    const isValid = code.length > 0;
    if (countryCode) {
      // Do not show the green checkmark ("right symbol") icon on country selector
      countryCode.classList.remove("is-valid");
      if (!isValid && countryCode.value !== "") {
        countryCode.classList.add("is-invalid");
      } else {
        countryCode.classList.remove("is-invalid");
      }
    }
    if (mobileNumber && code) {
      if (code === "+91") {
        mobileNumber.placeholder = "10-digit number (e.g. 9876543210)";
      } else if (code === "+1" || code === "+1-CA") {
        mobileNumber.placeholder = "10-digit number (e.g. 555-123-4567)";
      } else if (code === "+44") {
        mobileNumber.placeholder = "Phone number (e.g. 7911 123456)";
      } else {
        mobileNumber.placeholder = "Phone number";
      }
    }
    return isValid;
  }

  function validateMobile() {
    const val = mobileNumber.value.trim();
    const digits = val.replace(/\D/g, "");
    const isValid = digits.length >= 6 && digits.length <= 15;
    toggleValidationClass(mobileNumber, isValid);
    return isValid;
  }

  function validateConsent() {
    return consentCheckbox.checked;
  }

  function toggleValidationClass(element, isValid) {
    if (element.value.trim().length === 0) {
      element.classList.remove("is-valid", "is-invalid");
    } else if (isValid) {
      element.classList.add("is-valid");
      element.classList.remove("is-invalid");
    } else {
      element.classList.add("is-invalid");
      element.classList.remove("is-valid");
    }
  }

  function checkFormValidity() {
    const isNameValid = namePattern.test(fullName.value.trim());
    const isEmailValid = emailPattern.test(emailAddress.value.trim());
    const isCountryValid = countryCode ? countryCode.value.trim().length > 0 : true;
    const digits = mobileNumber.value.trim().replace(/\D/g, "");
    const isMobileValid = digits.length >= 6 && digits.length <= 15;
    const isConsentValid = consentCheckbox.checked;

    const allValid = isNameValid && isEmailValid && isCountryValid && isMobileValid && isConsentValid;
    startBtn.disabled = !allValid || isSubmitting;
    return allValid;
  }

  // Event Listeners for real-time validation
  fullName.addEventListener("input", () => {
    validateFullName();
    checkFormValidity();
  });

  emailAddress.addEventListener("input", () => {
    validateEmail();
    checkFormValidity();
    clearTimeout(lookupTimer);
    lookupTimer = setTimeout(performCandidateLookup, 800);
  });

  emailAddress.addEventListener("blur", performCandidateLookup);

  let lookupTimer = null;
  function performCandidateLookup() {
    const dynCard = document.getElementById("dynamicPreviousAttemptCard");
    if (!dynCard) return;

    const email = emailAddress.value.trim().toLowerCase();
    if (!email || !emailPattern.test(email)) {
      dynCard.classList.add("d-none");
      return;
    }

    fetch(`/api/candidate/lookup?email=${encodeURIComponent(email)}`)
      .then(res => res.json())
      .then(data => {
        if (!dynCard) return;

        if (data.found) {
          dynCard.classList.remove("d-none");
          const dynDate = document.getElementById("dynPrevDate");
          const dynWelcome = document.getElementById("dynWelcomeName");
          const dynScore = document.getElementById("dynScoreText");
          const dynDisc = document.getElementById("dynDiscountText");
          const dynPinBox = document.getElementById("dynPinContainer");
          const dynPin = document.getElementById("dynPinText");
          const dynCopy = document.getElementById("dynCopyPinBtn");
          const dynCooldown = document.getElementById("dynCooldownNotice");

          if (dynDate) dynDate.textContent = data.completed_at || "";
          if (dynWelcome) dynWelcome.textContent = `Welcome Back, ${data.full_name}!`;
          if (dynScore) dynScore.textContent = `${data.score}/${data.max_score} (${data.percentage}%)`;
          if (dynDisc) dynDisc.textContent = data.discount_percent > 0 ? `${data.discount_percent}% OFF` : "No Discount";

          if (data.pin && data.discount_percent > 0) {
            dynPinBox.classList.remove("d-none");
            dynPinBox.classList.add("d-flex");
            dynPin.textContent = data.pin;
            dynCopy.onclick = () => {
              if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(data.pin);
              }
              alert(`10-Digit Voucher PIN copied: ${data.pin}`);
            };
          } else {
            dynPinBox.classList.add("d-none");
            dynPinBox.classList.remove("d-flex");
          }

          if (dynCooldown) {
            if (data.cooldown_active) {
              dynCooldown.innerHTML = `
                <span class="text-warning fw-semibold"><i class="bi bi-hourglass-split me-1"></i> Retake Cooldown Active:</span>
                <span class="text-slate-300">On behalf of your previous assessment timestamp, you can retake this exam in <strong class="text-white">${data.hours_remaining} hours and ${data.minutes_remaining} minutes</strong>.</span>
              `;
            } else {
              dynCooldown.innerHTML = `
                <span class="text-success fw-semibold"><i class="bi bi-check-circle-fill me-1"></i> Retake Eligible:</span>
                <span class="text-slate-300">Your cooldown window has elapsed. You are eligible to take another assessment attempt.</span>
              `;
            }
          }
        } else {
          dynCard.classList.add("d-none");
        }
      })
      .catch(() => {});
  }

  if (countryCode) {
    countryCode.addEventListener("change", () => {
      validateCountryCode();
      checkFormValidity();
    });
  }

  mobileNumber.addEventListener("input", () => {
    validateMobile();
    checkFormValidity();
  });

  consentCheckbox.addEventListener("change", () => {
    checkFormValidity();
  });

  // Handle Form Submission with Double-Click Guard
  form.addEventListener("submit", (e) => {
    if (!checkFormValidity() || isSubmitting) {
      e.preventDefault();
      return;
    }

    isSubmitting = true;
    startBtn.disabled = true;
    btnText.textContent = "Setting up Session...";
    btnIcon.classList.add("d-none");
    btnSpinner.classList.remove("d-none");
  });

  // Initial check on load
  validateCountryCode();
  checkFormValidity();
});
