/**
 * Server-Authoritative Countdown Timer Module
 */
const ExamTimer = (() => {
  let remainingSeconds = (window.ASSESSMENT_DATA && window.ASSESSMENT_DATA.remainingSeconds) || 900;
  let timerInterval = null;
  let syncInterval = null;
  let isExpired = false;

  const timerBadge = document.getElementById("examTimer");
  const timerDisplay = document.getElementById("timerDisplay");
  const timerIcon = document.getElementById("timerIcon");

  function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    const formattedMins = mins < 10 ? "0" + mins : mins;
    const formattedSecs = secs < 10 ? "0" + secs : secs;
    return `${formattedMins}:${formattedSecs}`;
  }

  function updateVisualState() {
    timerDisplay.textContent = formatTime(remainingSeconds);

    if (remainingSeconds <= 60) {
      // Urgent: 1 minute or less
      timerBadge.className = "timer-badge timer-danger shadow-xs";
      timerIcon.className = "bi bi-exclamation-circle-fill text-danger";
    } else if (remainingSeconds <= 300) {
      // Warning: 5 minutes or less
      timerBadge.className = "timer-badge timer-warning shadow-xs";
      timerIcon.className = "bi bi-exclamation-triangle-fill text-warning";
    } else {
      timerBadge.className = "timer-badge shadow-xs";
      timerIcon.className = "bi bi-clock-history text-primary";
    }
  }

  function handleTimeExpired() {
    if (isExpired) return;
    isExpired = true;
    clearInterval(timerInterval);
    clearInterval(syncInterval);

    timerDisplay.textContent = "00:00";
    timerBadge.className = "timer-badge timer-danger shadow-xs";

    // Auto-submit the assessment
    if (window.AssessmentApp && window.AssessmentApp.submitExam) {
      window.AssessmentApp.submitExam(true);
    } else {
      // Fallback submit
      fetch(`/api/assessment/${window.ASSESSMENT_DATA.attemptId}/submit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').getAttribute("content")
        }
      })
      .then(res => res.json())
      .then(data => {
        if (data.redirect_url) {
          window.location.href = data.redirect_url;
        }
      })
      .catch(() => {
        window.location.reload();
      });
    }
  }

  function tick() {
    if (remainingSeconds <= 0) {
      handleTimeExpired();
    } else {
      remainingSeconds--;
      updateVisualState();
    }
  }

  async function syncWithServer() {
    if (isExpired) return;
    try {
      const resp = await fetch(`/assessment/${window.ASSESSMENT_DATA.attemptId}/status`, {
        headers: {
          "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').getAttribute("content")
        }
      });
      if (resp.ok) {
        const data = await resp.json();
        
        // Integrity strike violation termination
        if (data.status === "aborted") {
          handleTimeExpired();
          return;
        }

        if (data.expired) {
          // If server reports expired, check whether server remaining_seconds is positive
          if (typeof data.remaining_seconds === "number" && data.remaining_seconds > 0) {
            remainingSeconds = data.remaining_seconds;
            updateVisualState();
          } else if (remainingSeconds <= 10) {
            handleTimeExpired();
          } else {
            console.warn("Server reported expired unexpectedly while local timer has " + remainingSeconds + "s remaining. Ignoring transient cold-start anomaly.");
          }
        } else if (data.status === "completed") {
          // Only auto-expire if client clock has actually run down
          if (remainingSeconds <= 5) {
            handleTimeExpired();
          }
        } else if (typeof data.remaining_seconds === "number") {
          // Resync client clock with authoritative server seconds
          // Smooth sync: only adjust if drift is greater than 3 seconds
          if (Math.abs(remainingSeconds - data.remaining_seconds) > 3) {
            remainingSeconds = data.remaining_seconds;
            updateVisualState();
          }
        }
      }
    } catch (e) {
      // Ignore transient network hiccups
    }
  }

  function init() {
    updateVisualState();
    timerInterval = setInterval(tick, 1000);
    // Periodic synchronization with server every 45 seconds
    syncInterval = setInterval(syncWithServer, 45000);
  }

  return {
    init,
    syncWithServer,
    getRemainingSeconds: () => remainingSeconds
  };
})();

document.addEventListener("DOMContentLoaded", () => {
  if (window.ASSESSMENT_DATA) {
    ExamTimer.init();
  }
});
