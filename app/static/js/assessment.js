/**
 * Assessment Navigation, Option Selection (3 Options A, B, C), Autosave, and Final Submission
 */
const AssessmentApp = (() => {
  let attemptId = null;
  let csrfToken = null;
  let questions = [];
  let currentIndex = 0;
  const visitedQuestions = new Set();

  // DOM Elements
  const currentSectionBadge = document.getElementById("currentSectionBadge");
  const questionCounterBadge = document.getElementById("questionCounterBadge");
  const questionText = document.getElementById("questionText");
  const optionsContainer = document.getElementById("optionsContainer");
  const prevBtn = document.getElementById("prevBtn");
  const nextBtn = document.getElementById("nextBtn");
  const openSubmitModalBtn = document.getElementById("openSubmitModalBtn");

  // Summary & Modal Elements
  const totalAnsweredCount = document.getElementById("totalAnsweredCount");
  const secProgReasoning = document.getElementById("secProgReasoning");
  const secProgAptitude = document.getElementById("secProgAptitude");
  const secProgLogical = document.getElementById("secProgLogical");
  const secProgEnglish = document.getElementById("secProgEnglish");

  const submitModalEl = document.getElementById("submitConfirmModal");
  let submitModal = null;
  const modalAnsweredCount = document.getElementById("modalAnsweredCount");
  const modalUnansweredCount = document.getElementById("modalUnansweredCount");
  const unansweredWarningNotice = document.getElementById("unansweredWarningNotice");
  const confirmFinalSubmitBtn = document.getElementById("confirmFinalSubmitBtn");

  function renderCurrentQuestion() {
    const q = questions[currentIndex];
    if (!q) return;

    // Mark current question as visited
    visitedQuestions.add(q.order);

    // Update section and counter badges
    if (currentSectionBadge) currentSectionBadge.textContent = q.section;
    if (questionCounterBadge) questionCounterBadge.textContent = `Question ${q.order} of 20`;
    if (questionText) questionText.textContent = q.question_text;

    // Populate Option Texts (3 Options Only: A, B, C)
    const optA = document.getElementById("textOptA");
    const optB = document.getElementById("textOptB");
    const optC = document.getElementById("textOptC");
    if (optA) optA.textContent = (q.options && q.options.A) || "";
    if (optB) optB.textContent = (q.options && q.options.B) || "";
    if (optC) optC.textContent = (q.options && q.options.C) || "";

    // Set Option Selection State
    const radioInputs = document.querySelectorAll('input[name="assessmentOption"]');
    radioInputs.forEach(input => {
      const isSelected = input.value === q.selected_option;
      input.checked = isSelected;
      const card = input.closest(".option-card");
      if (card) {
        if (isSelected) {
          card.classList.add("selected");
        } else {
          card.classList.remove("selected");
        }
      }
    });

    // Update Previous / Next button states
    if (prevBtn) prevBtn.disabled = currentIndex === 0;
    if (nextBtn) {
      if (currentIndex === questions.length - 1) {
        nextBtn.innerHTML = '<span>Review &amp; Submit</span> <i class="bi bi-card-checklist"></i>';
      } else {
        nextBtn.innerHTML = '<span>Next Question</span> <i class="bi bi-chevron-right"></i>';
      }
    }

    updatePalette();
  }

  function updatePalette() {
    let answeredTotal = 0;

    const sectionCounts = {
      "Reasoning": 0,
      "General Aptitude": 0,
      "Logical Reasoning": 0,
      "English Grammar": 0
    };

    questions.forEach(q => {
      const btn = document.getElementById(`qbtn-${q.order}`);
      if (!btn) return;

      // Reset classes
      btn.className = "q-btn";

      if (questions[currentIndex] && q.order === questions[currentIndex].order) {
        btn.classList.add("current");
      }

      const hasAnswer = q.selected_option !== null && q.selected_option !== undefined && q.selected_option !== "";
      const isVisited = visitedQuestions.has(q.order);

      if (hasAnswer) {
        answeredTotal++;
        if (sectionCounts[q.section] !== undefined) {
          sectionCounts[q.section]++;
        }
        btn.classList.add("answered");
      } else if (isVisited) {
        btn.classList.add("visited-unanswered");
      } else {
        btn.classList.add("not-visited");
      }
    });

    // Update top counts
    if (totalAnsweredCount) totalAnsweredCount.textContent = `${answeredTotal}/20 Answered`;
    if (secProgReasoning) secProgReasoning.textContent = `${sectionCounts["Reasoning"] || 0}/5`;
    if (secProgAptitude) secProgAptitude.textContent = `${sectionCounts["General Aptitude"] || 0}/5`;
    if (secProgLogical) secProgLogical.textContent = `${sectionCounts["Logical Reasoning"] || 0}/5`;
    if (secProgEnglish) secProgEnglish.textContent = `${sectionCounts["English Grammar"] || 0}/5`;
  }

  async function persistAnswer(order, selectedOption) {
    try {
      const payload = {
        question_order: order,
        selected_option: selectedOption,
        is_marked_for_review: false
      };

      const resp = await fetch(`/api/assessment/${attemptId}/answer`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken
        },
        body: JSON.stringify(payload)
      });

      if (!resp.ok) {
        const errData = await resp.json();
        if (errData.expired) {
          submitExam(true);
        }
      }
    } catch (e) {
      console.warn("Async answer save error:", e);
    }
  }

  function saveAnswersToStorage() {
    try {
      if (!attemptId) return;
      const data = questions.map(q => ({
        order: q.order,
        code: q.code || "",
        selected_option: q.selected_option || null
      }));
      localStorage.setItem("assessment_answers_" + attemptId, JSON.stringify(data));
    } catch (e) {}
  }

  function selectOption(optionVal) {
    const q = questions[currentIndex];
    if (!q) return;

    q.selected_option = optionVal;
    saveAnswersToStorage();

    // Update UI immediately
    const radioInputs = document.querySelectorAll('input[name="assessmentOption"]');
    radioInputs.forEach(input => {
      const isSelected = input.value === optionVal;
      input.checked = isSelected;
      const card = input.closest(".option-card");
      if (card) {
        if (isSelected) {
          card.classList.add("selected");
        } else {
          card.classList.remove("selected");
        }
      }
    });

    updatePalette();
    persistAnswer(q.order, optionVal);
  }

  function openSubmitConfirmationModal() {
    let answered = 0;
    questions.forEach(q => {
      if (q.selected_option !== null && q.selected_option !== undefined && q.selected_option !== "") {
        answered++;
      }
    });

    const unanswered = Math.max(0, 20 - answered);
    if (modalAnsweredCount) modalAnsweredCount.textContent = answered;
    if (modalUnansweredCount) modalUnansweredCount.textContent = unanswered;

    if (unansweredWarningNotice) {
      if (unanswered > 0) {
        unansweredWarningNotice.classList.remove("d-none");
      } else {
        unansweredWarningNotice.classList.add("d-none");
      }
    }

    if (submitModal) {
      submitModal.show();
    }
  }

  async function submitExam(isAutoExpired = false) {
    try {
      if (confirmFinalSubmitBtn) {
        confirmFinalSubmitBtn.disabled = true;
        confirmFinalSubmitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Finalizing...';
      }

      const answersPayload = (questions || []).map(q => ({
        order: q.order,
        code: q.code || "",
        selected_option: q.selected_option || null
      }));

      const resp = await fetch(`/api/assessment/${attemptId}/submit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken
        },
        body: JSON.stringify({ answers: answersPayload })
      });

      try {
        localStorage.removeItem("assessment_answers_" + attemptId);
      } catch (e) {}

      const data = await resp.json();
      if (data && data.redirect_url) {
        window.location.href = data.redirect_url;
      } else {
        window.location.href = `/result/${attemptId}`;
      }
    } catch (e) {
      console.error("Submit error:", e);
      window.location.href = `/result/${attemptId}`;
    }
  }

  function setupEventListeners() {
    // Option Card Clicks
    const optionCards = document.querySelectorAll(".option-card");
    optionCards.forEach(card => {
      card.addEventListener("click", () => {
        const optVal = card.dataset.option;
        selectOption(optVal);
      });
    });

    // Previous Button
    if (prevBtn) {
      prevBtn.addEventListener("click", () => {
        if (currentIndex > 0) {
          currentIndex--;
          renderCurrentQuestion();
        }
      });
    }

    // Next Button
    if (nextBtn) {
      nextBtn.addEventListener("click", () => {
        if (currentIndex < questions.length - 1) {
          currentIndex++;
          renderCurrentQuestion();
        } else {
          openSubmitConfirmationModal();
        }
      });
    }

    // Question Palette Buttons Click
    document.querySelectorAll(".q-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const order = parseInt(btn.dataset.order, 10);
        const idx = questions.findIndex(q => q.order === order);
        if (idx !== -1) {
          currentIndex = idx;
          renderCurrentQuestion();
        }
      });
    });

    // Open Submit Modal
    if (openSubmitModalBtn) {
      openSubmitModalBtn.addEventListener("click", openSubmitConfirmationModal);
    }

    // Confirm Submit Button in Modal
    if (confirmFinalSubmitBtn) {
      confirmFinalSubmitBtn.addEventListener("click", () => {
        submitExam(false);
      });
    }
  }

  function init() {
    if (!window.ASSESSMENT_DATA) return;

    attemptId = window.ASSESSMENT_DATA.attemptId;
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    csrfToken = csrfMeta ? csrfMeta.getAttribute("content") : "";
    questions = window.ASSESSMENT_DATA.questions || [];

    // Restore saved answers from localStorage if page reloaded
    try {
      const saved = localStorage.getItem("assessment_answers_" + attemptId);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) {
          parsed.forEach(item => {
            const match = questions.find(q => q.order === item.order);
            if (match && item.selected_option) {
              match.selected_option = item.selected_option;
            }
          });
        }
      }
    } catch (e) {}

    if (submitModalEl && window.bootstrap) {
      submitModal = new bootstrap.Modal(submitModalEl);
    }

    setupEventListeners();
    renderCurrentQuestion();
  }

  return {
    init,
    submitExam
  };
})();

document.addEventListener("DOMContentLoaded", () => {
  AssessmentApp.init();
});
