/**
 * Assessment Integrity & Real-Time AI Computer Vision Proctoring Monitor
 * 1. Implements two-strike policy for navigation events (tab switching, window blur, fullscreen exit).
 * 2. Implements real-time AI vision proctoring loop directly on the active test screen:
 *    - MediaPipe Face Landmarker for scale-invariant head-pose estimation (left/right/down).
 *    - TensorFlow.js & COCO-SSD for browser-based mobile phone detection.
 *    - Renders OpenCV-style bounding boxes on canvas:
 *      * Green = Normal, Center (Face OK)
 *      * Amber = Turned < 2s
 *      * Red = Sustained Deviation > 2-3s -> Modal Warning Popup
 *      * Red = Mobile Phone Detected -> Modal Warning Popup
 *    - Real-time HUD status badges & sidebar cards.
 *    - Event telemetry transmitted to /api/assessment/<attempt_id>/proctoring-event.
 */
const IntegrityMonitor = (() => {
  let attemptId = null;
  let csrfToken = null;
  let lastViolationTimestamp = 0;
  const DEBOUNCE_MS = 2000;

  // Modals & Navigation Warning Elements
  const warningModalEl = document.getElementById("integrityWarningModal");
  let warningModal = null;
  const dismissWarningBtn = document.getElementById("dismissWarningBtn");

  const deviceAlertBanner = document.getElementById("deviceAlertBanner");
  const reconnectDeviceBtn = document.getElementById("reconnectDeviceBtn");
  const headerCamStatus = document.getElementById("headerCamStatus");
  const headerMicStatus = document.getElementById("headerMicStatus");

  // Vision Proctoring Modals & Banners
  let phoneWarningModal = null;
  let headMovementModal = null;
  let visionBannerDismissTimer = null;
  let visionWarningCount = 0;

  let localStream = null;
  let visionLoopTimer = null;

  // ---------------------------------------------------------------------------
  // 1. Navigation & Screen-Switching Integrity (Two-Strike System)
  // ---------------------------------------------------------------------------
  async function reportViolation(eventType, metadata = {}) {
    const now = Date.now();
    if (now - lastViolationTimestamp < DEBOUNCE_MS) {
      return;
    }
    lastViolationTimestamp = now;

    try {
      const resp = await fetch(`/api/assessment/${attemptId}/violation`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken
        },
        body: JSON.stringify({
          eventType: eventType,
          metadata: Object.assign({}, metadata, { client_time: new Date().toISOString() })
        })
      });

      if (!resp.ok) return;
      const data = await resp.json();

      if (data.action === "warning") {
        showStrikeOneWarning();
      } else if (data.action === "aborted") {
        if (data.redirect_url) {
          window.location.href = data.redirect_url;
        } else {
          window.location.href = `/aborted/${attemptId}`;
        }
      }
    } catch (e) {
      console.error("Integrity report error:", e);
    }
  }

  function showStrikeOneWarning() {
    if (warningModal) {
      warningModal.show();
    }
  }

  function setupScreenSwitchDetection() {
    const isEmbedded = (window.self !== window.top) || (window.location.search.indexOf("embed=1") !== -1);

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        reportViolation("tab_switch", { details: "Page visibility hidden" });
      }
    });

    if (!isEmbedded) {
      window.addEventListener("blur", () => {
        reportViolation("window_blur", { details: "Window blur detected" });
      });

      document.addEventListener("fullscreenchange", () => {
        if (!document.fullscreenElement) {
          reportViolation("fullscreen_exit", { details: "Exited fullscreen mode" });
        }
      });
    }

    window.addEventListener("beforeunload", (e) => {
      e.preventDefault();
      e.returnValue = "Leaving this page may invalidate your assessment.";
    });
  }

  // ---------------------------------------------------------------------------
  // 2. Real-Time AI Proctoring Computer Vision Loop
  // ---------------------------------------------------------------------------
  async function setupProctoringStream() {
    try {
      try {
        localStream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 } },
          audio: true
        });
      } catch (audioErr) {
        console.warn("Microphone access failed or busy; falling back to video-only stream:", audioErr);
        localStream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 } }
        });
      }

      const sidebarVideo = document.getElementById("sidebarProctorVideo");
      const sidebarCanvas = document.getElementById("sidebarProctorCanvas");
      const pipVideo = document.getElementById("proctorPipVideo");
      const primaryVideo = sidebarVideo || pipVideo;

      if (primaryVideo) {
        primaryVideo.muted = true;
        primaryVideo.setAttribute("muted", "");
        primaryVideo.setAttribute("playsinline", "");
        if (primaryVideo.srcObject !== localStream) {
          primaryVideo.srcObject = localStream;
        }
        try {
          await primaryVideo.play();
        } catch (e) {
          console.warn("Camera play notice:", e);
        }
      }

      // Resume video playback on user click/interaction if autoplay delayed it
      const ensureVideoPlaying = () => {
        if (primaryVideo && (primaryVideo.paused || primaryVideo.readyState < 2)) {
          primaryVideo.play().catch(() => {});
        }
      };
      document.addEventListener("click", ensureVideoPlaying, { once: true });
      document.addEventListener("keydown", ensureVideoPlaying, { once: true });

      // Monitor stream tracks
      localStream.getTracks().forEach(track => {
        track.addEventListener("ended", () => {
          handleDeviceDisconnected(track.kind);
        });
      });

      if (headerCamStatus) headerCamStatus.className = "device-indicator active";
      if (headerMicStatus) headerMicStatus.className = "device-indicator active";
      if (deviceAlertBanner) deviceAlertBanner.classList.add("d-none");

      // Initialize Models & Start Direct Vision Loop
      startDirectAssessmentVisionLoop(primaryVideo, sidebarCanvas);

    } catch (err) {
      console.warn("Proctoring stream error:", err);
      handleDeviceDisconnected("camera/microphone");
    }
  }

  function startDirectAssessmentVisionLoop(videoEl, canvasEl) {
    if (visionLoopTimer) {
      clearInterval(visionLoopTimer);
      visionLoopTimer = null;
    }

    // Bind warning and status listeners
    if (typeof HeadPoseModule !== "undefined") {
      if (HeadPoseModule.resetBaseline) {
        HeadPoseModule.resetBaseline();
      }
      HeadPoseModule.setOnWarning(handleVisionWarning);
      HeadPoseModule.setOnStatusUpdate(updateVisionHUD);
      HeadPoseModule.initialize();

      // Establish neutral baseline 2.0s after camera starts so it aligns to candidate's sitting position
      setTimeout(() => {
        if (typeof HeadPoseModule !== "undefined" && HeadPoseModule.isReady()) {
          HeadPoseModule.calibrateNeutral();
        }
      }, 2000);
    }

    if (typeof PhoneDetectorModule !== "undefined") {
      PhoneDetectorModule.setOnWarning(handleVisionWarning);
      PhoneDetectorModule.setOnStatusUpdate(updatePhoneHUD);
      PhoneDetectorModule.initialize();
    }

    // Direct high-performance sampling loop (~5 FPS)
    visionLoopTimer = setInterval(async () => {
      if (!videoEl || videoEl.readyState < 2) {
        if (videoEl && videoEl.paused) {
          videoEl.play().catch(() => {});
        }
        return;
      }

      const now = Date.now();

      try {
        // 1. Process Head Pose Estimation
        let faceResult = typeof HeadPoseModule !== "undefined" ?
          await HeadPoseModule.processVideoFrame(videoEl, now) : null;

        // 2. Process Mobile Phone Detection
        const phoneResult = (typeof PhoneDetectorModule !== "undefined" && PhoneDetectorModule.isReady()) ?
          await PhoneDetectorModule.processVideoFrame(videoEl, now) : null;

        // 3. Fallback box ONLY while MediaPipe is warming up
        const isMediaPipeActive = (typeof HeadPoseModule !== "undefined" && HeadPoseModule.isReady());
        if (!isMediaPipeActive && (!faceResult || !faceResult.faceDetected) && phoneResult && phoneResult.personBox) {
          const pb = phoneResult.personBox;
          const headW = pb.width * 0.65;
          const headH = pb.height * 0.40;
          faceResult = {
            faceDetected: true,
            box: { x: pb.x + (pb.width - headW) / 2, y: pb.y, width: headW, height: headH },
            color: "#10B981",
            direction: "NORMAL",
            isWarning: false,
            sustainedMs: 0
          };
        }

        // 4. Render OpenCV bounding boxes directly onto canvas
        if (canvasEl && typeof ProctoringEngine !== "undefined") {
          ProctoringEngine.renderCanvasOverlay(videoEl, canvasEl, faceResult, phoneResult);
        }
      } catch (err) {
        console.warn("Vision loop tick notice:", err);
      }
    }, 200);
  }

  // ---------------------------------------------------------------------------
  // 3. Vision Warning Handlers, Modals, Banners & Backend Logging
  // ---------------------------------------------------------------------------
  let multiplePersonsModal = null;

  function handleVisionWarning(warning) {
    // If a modal is already displayed to the candidate, suppress duplicate alerts
    if (document.querySelector(".modal.show")) {
      return;
    }

    console.warn("Vision violation triggered:", warning);

    // 1. Immediately display candidate-facing popup warning modal
    if (warning.type === "MOBILE_PHONE_DETECTED") {
      showPhoneWarningModal(warning.message);
      showVisionBanner(warning.message, "danger");
    } else if (warning.type === "MULTIPLE_FACES_DETECTED" || warning.type === "MULTIPLE_PEOPLE_DETECTED") {
      showMultiplePersonsModal(warning.message);
      showVisionBanner(warning.message, "danger");
    } else if (warning.type === "HEAD_TURN_LEFT" || warning.type === "HEAD_TURN_RIGHT" || warning.type === "HEAD_TILT_DOWN") {
      showHeadMovementWarningModal(warning.message, warning.direction);
      showVisionBanner(warning.message, "warning");
    } else if (warning.type === "GAZE_AWAY") {
      showVisionBanner(warning.message, "warning");
    } else if (warning.type === "UNAUTHORIZED_OBJECT_DETECTED") {
      showVisionBanner(warning.message, "warning");
    } else if (warning.type === "FACE_NOT_DETECTED") {
      showVisionBanner(warning.message, "danger");
    } else if (warning.type === "FACE_RESTORED") {
      dismissVisionBanner();
    }

    // 2. Transmit structured proctoring event to Flask backend
    sendProctoringEventToBackend(warning);
  }

  function showMultiplePersonsModal(message) {
    if (!multiplePersonsModal) {
      const el = document.getElementById("multiplePersonsModal");
      if (el && window.bootstrap) {
        multiplePersonsModal = new bootstrap.Modal(el, { backdrop: "static", keyboard: false });
      }
    }
    if (multiplePersonsModal) {
      const textEl = document.getElementById("multiplePersonsModalText");
      if (textEl && message) textEl.textContent = message;
      multiplePersonsModal.show();
    }
  }

  function showPhoneWarningModal(message) {
    if (!phoneWarningModal) {
      const el = document.getElementById("phoneWarningModal");
      if (el && window.bootstrap) {
        phoneWarningModal = new bootstrap.Modal(el, { backdrop: "static", keyboard: false });
      }
    }
    if (phoneWarningModal) {
      const textEl = document.getElementById("phoneWarningModalText");
      if (textEl && message) textEl.textContent = message;
      phoneWarningModal.show();
    }
  }

  function showHeadMovementWarningModal(message, direction) {
    if (!headMovementModal) {
      const el = document.getElementById("headMovementModal");
      if (el && window.bootstrap) {
        headMovementModal = new bootstrap.Modal(el, { backdrop: "static", keyboard: false });
      }
    }
    if (headMovementModal) {
      const titleEl = document.getElementById("headMovementModalTitle");
      const textEl = document.getElementById("headMovementModalText");
      if (titleEl && direction) {
        titleEl.textContent = `Head Turned ${direction} Detected (>2s)`;
      }
      if (textEl && message) {
        textEl.textContent = message;
      }
      headMovementModal.show();
    }
  }

  function showVisionBanner(message, level = "warning") {
    if (visionBannerDismissTimer) {
      clearTimeout(visionBannerDismissTimer);
    }
    const banner = document.getElementById("visionAlertBanner");
    const textEl = document.getElementById("visionBannerText");
    if (banner && textEl) {
      banner.className = `alert alert-${level} d-flex align-items-center justify-content-between py-2 px-3 mb-3 border border-${level} shadow-sm`;
      textEl.textContent = message;
      banner.classList.remove("d-none");

      visionBannerDismissTimer = setTimeout(() => {
        dismissVisionBanner();
      }, 9000);
    }
  }

  function dismissVisionBanner() {
    const banner = document.getElementById("visionAlertBanner");
    if (banner) {
      banner.classList.add("d-none");
    }
  }

  async function sendProctoringEventToBackend(warning) {
    if (!attemptId) return;
    const clientEventId = `${warning.type}-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;

    try {
      const resp = await fetch(`/api/assessment/${attemptId}/proctoring-event`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken
        },
        body: JSON.stringify({
          event_type: warning.type,
          confidence: warning.confidence || 0.95,
          duration_ms: warning.durationMs || 2000,
          client_event_id: clientEventId,
          metadata: { direction: warning.direction || null }
        })
      });

      if (!resp.ok) return;
      const data = await resp.json();

      if (data && data.vision_warning_count !== undefined) {
        visionWarningCount = data.vision_warning_count;
        updateWarningCountHUD(visionWarningCount);
      }
    } catch (e) {
      console.warn("Proctoring event backend sync notice:", e);
    }
  }

  // ---------------------------------------------------------------------------
  // 4. Real-Time HUD & Status Badge Updates
  // ---------------------------------------------------------------------------
  function updateVisionHUD(status) {
    const hudFaceBadge = document.getElementById("hudFaceBadge");
    const hudHeadBadge = document.getElementById("hudHeadBadge");
    const sidebarFaceBadge = document.getElementById("sidebarFaceBadge");
    const sidebarHeadBadge = document.getElementById("sidebarHeadBadge");

    // Face detection badge
    if (hudFaceBadge) {
      if (status.multipleFaces) {
        hudFaceBadge.className = "badge bg-danger bg-opacity-25 text-danger border border-danger border-opacity-40";
        hudFaceBadge.innerHTML = `<i class="bi bi-people-fill me-1"></i> Multiple Faces (${status.numFaces})`;
      } else if (status.faceDetected) {
        hudFaceBadge.className = "badge bg-success bg-opacity-20 text-success border border-success border-opacity-30";
        hudFaceBadge.innerHTML = '<i class="bi bi-person-check-fill me-1"></i> Face OK';
      } else {
        hudFaceBadge.className = "badge bg-danger bg-opacity-20 text-danger border border-danger border-opacity-30";
        hudFaceBadge.innerHTML = '<i class="bi bi-person-x-fill me-1"></i> No Face';
      }
    }

    if (sidebarFaceBadge) {
      if (status.multipleFaces) {
        sidebarFaceBadge.className = "badge bg-danger bg-opacity-25 text-danger border border-danger border-opacity-40";
        sidebarFaceBadge.innerHTML = `<i class="bi bi-people-fill me-1"></i> Multiple Faces (${status.numFaces})`;
      } else if (status.faceDetected) {
        sidebarFaceBadge.className = "badge bg-success bg-opacity-20 text-success border border-success border-opacity-30";
        sidebarFaceBadge.innerHTML = '<i class="bi bi-person-check-fill me-1"></i> Face OK';
      } else {
        sidebarFaceBadge.className = "badge bg-danger bg-opacity-20 text-danger border border-danger border-opacity-30";
        sidebarFaceBadge.innerHTML = '<i class="bi bi-person-x-fill me-1"></i> No Face';
      }
    }

    // Head orientation badge
    if (hudHeadBadge) {
      if (!status.faceDetected) {
        hudHeadBadge.className = "badge bg-dark text-muted border border-secondary";
        hudHeadBadge.textContent = "Head: --";
      } else if (status.direction === "NORMAL") {
        hudHeadBadge.className = "badge bg-primary bg-opacity-20 text-cyan border border-info border-opacity-30";
        hudHeadBadge.innerHTML = '<i class="bi bi-compass me-1"></i> Center';
      } else {
        const cls = status.isWarning ?
          "badge bg-danger bg-opacity-25 text-danger border border-danger border-opacity-40" :
          "badge bg-warning bg-opacity-25 text-warning border border-warning border-opacity-40";
        hudHeadBadge.className = cls;
        hudHeadBadge.innerHTML = `<i class="bi bi-arrow-repeat me-1"></i> ${status.direction}`;
      }
    }

    if (sidebarHeadBadge) {
      if (!status.faceDetected) {
        sidebarHeadBadge.textContent = "Orientation: --";
        sidebarHeadBadge.className = "text-muted small";
      } else if (status.direction === "NORMAL") {
        sidebarHeadBadge.textContent = "Orientation: Center";
        sidebarHeadBadge.className = "text-cyan fw-medium small";
      } else {
        const cls = status.isWarning ? "text-danger fw-bold small" : "text-warning fw-medium small";
        sidebarHeadBadge.textContent = `Turned: ${status.direction}`;
        sidebarHeadBadge.className = cls;
      }
    }
  }

  function updatePhoneHUD(status) {
    const hudPhoneBadge = document.getElementById("hudPhoneBadge");
    const sidebarPhoneBadge = document.getElementById("sidebarPhoneBadge");

    if (hudPhoneBadge) {
      if (!status.isAvailable) {
        hudPhoneBadge.className = "badge bg-dark text-muted border border-secondary";
        hudPhoneBadge.innerHTML = '<i class="bi bi-phone me-1"></i> Phone Guard';
      } else if (status.phoneDetected) {
        hudPhoneBadge.className = "badge bg-danger bg-opacity-25 text-danger border border-danger border-opacity-40";
        hudPhoneBadge.innerHTML = '<i class="bi bi-phone-vibrate-fill me-1"></i> Phone Alert';
      } else {
        hudPhoneBadge.className = "badge bg-success bg-opacity-20 text-success border border-success border-opacity-30";
        hudPhoneBadge.innerHTML = '<i class="bi bi-phone me-1"></i> Phone Guard';
      }
    }

    if (sidebarPhoneBadge) {
      if (status.phoneDetected) {
        sidebarPhoneBadge.className = "text-danger fw-bold small";
        sidebarPhoneBadge.innerHTML = '<i class="bi bi-phone-vibrate-fill me-1"></i>Phone Alert';
      } else {
        sidebarPhoneBadge.className = "text-success fw-medium small";
        sidebarPhoneBadge.innerHTML = '<i class="bi bi-phone me-1"></i>Phone Guard';
      }
    }

    if (sidebarFaceBadge && status.multiplePersonsDetected) {
      sidebarFaceBadge.className = "badge bg-danger bg-opacity-25 text-danger border border-danger border-opacity-40";
      sidebarFaceBadge.innerHTML = `<i class="bi bi-people-fill me-1"></i> Multiple People (${status.personCount})`;
    }
  }

  function updateWarningCountHUD(count) {
    const hudWarningBadge = document.getElementById("hudWarningBadge");
    if (hudWarningBadge) {
      hudWarningBadge.textContent = `${count} Warnings`;
      if (count > 0) {
        hudWarningBadge.className = "badge bg-warning bg-opacity-25 text-warning border border-warning border-opacity-40";
      } else {
        hudWarningBadge.className = "badge bg-dark text-secondary border border-secondary-subtle";
      }
    }
  }

  function handleDeviceDisconnected(deviceType) {
    if (visionLoopTimer) {
      clearInterval(visionLoopTimer);
      visionLoopTimer = null;
    }
    if (deviceAlertBanner) {
      deviceAlertBanner.classList.remove("d-none");
    }
    if (headerCamStatus) headerCamStatus.className = "device-indicator danger";
    if (headerMicStatus) headerMicStatus.className = "device-indicator danger";

    reportViolation("device_disconnected", { device: deviceType });
  }

  function init() {
    if (!window.ASSESSMENT_DATA) return;
    attemptId = window.ASSESSMENT_DATA.attemptId;
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    csrfToken = csrfMeta ? csrfMeta.getAttribute("content") : "";

    // Fresh attempt session neutral baseline initialization:
    // Discard any stale baseline from old tests or different postures so assessment auto-calibrates to current posture
    if (attemptId && !sessionStorage.getItem("datadrix_assessment_calib_" + attemptId)) {
      sessionStorage.setItem("datadrix_assessment_calib_" + attemptId, "1");
      try {
        localStorage.removeItem("datadrix_baseline_yaw");
        localStorage.removeItem("datadrix_baseline_pitch");
      } catch (e) {}
    }

    if (warningModalEl && window.bootstrap) {
      warningModal = new bootstrap.Modal(warningModalEl, {
        backdrop: "static",
        keyboard: false
      });
    }

    if (dismissWarningBtn && warningModal) {
      dismissWarningBtn.addEventListener("click", () => {
        warningModal.hide();
      });
    }

    // Dismiss head movement modal and re-center neutral baseline immediately
    const dismissHeadMovementBtn = document.getElementById("dismissHeadMovementBtn");
    if (dismissHeadMovementBtn) {
      dismissHeadMovementBtn.addEventListener("click", () => {
        if (typeof HeadPoseModule !== "undefined") {
          HeadPoseModule.calibrateNeutral();
        }
        if (headMovementModal) {
          headMovementModal.hide();
        }
        dismissVisionBanner();
      });
    }

    // Dismiss multiple persons modal
    const dismissMultiplePersonsBtn = document.getElementById("dismissMultiplePersonsBtn");
    if (dismissMultiplePersonsBtn) {
      dismissMultiplePersonsBtn.addEventListener("click", () => {
        if (multiplePersonsModal) {
          multiplePersonsModal.hide();
        }
        dismissVisionBanner();
      });
    }

    // Manual re-center button in Live Proctor Feed header
    const recenterPoseBtn = document.getElementById("recenterPoseBtn");
    if (recenterPoseBtn) {
      recenterPoseBtn.addEventListener("click", () => {
        if (typeof HeadPoseModule !== "undefined") {
          HeadPoseModule.calibrateNeutral();
          const origHtml = recenterPoseBtn.innerHTML;
          recenterPoseBtn.innerHTML = '<i class="bi bi-check2 text-success me-1"></i> Centered';
          setTimeout(() => {
            recenterPoseBtn.innerHTML = origHtml;
          }, 1500);
        }
      });
    }

    if (reconnectDeviceBtn) {
      reconnectDeviceBtn.addEventListener("click", () => {
        setupProctoringStream();
      });
    }

    setupScreenSwitchDetection();
    setupProctoringStream();
  }

  return {
    init,
    reportViolation
  };
})();

document.addEventListener("DOMContentLoaded", () => {
  IntegrityMonitor.init();
});
