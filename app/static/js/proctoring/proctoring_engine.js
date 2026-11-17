/**
 * Real-Time AI Proctoring Engine Coordinator (Mathematical Computer Vision)
 *
 * Integrates:
 *  1. 3D Vector Geometry Head Pose Module (Yaw, Pitch, Roll)
 *  2. Ocular Gaze & Iris Reticle Tracking
 *  3. Liveness & Micro-Motion Eye Aspect Ratio (EAR) Blink Engine
 *  4. Multi-Threat AI Object Detector (Smartphones, Books/Notes, Secondary Screens)
 *  5. Dual-Confirmation Secondary Individual Tracking (IoU verified)
 *  6. OpenCV High-Contrast Canvas Overlays & Multi-Target Synchronizer
 */
const ProctoringEngine = (() => {
  let attemptId = null;
  let csrfToken = null;
  let primaryVideo = null;
  let canvasElements = [];

  // Adaptive sampling configuration (~4 FPS for responsive low-latency proctoring)
  const SAMPLING_INTERVAL_MS = 250;
  let samplingTimer = null;
  let isInferring = false;
  let isRunning = false;

  // Proctoring status
  let visionWarningCount = 0;
  let bannerDismissTimeout = null;

  // Modals & DOM references
  let hudCamDot = null;
  let hudFaceBadge = null;
  let hudHeadBadge = null;
  let hudPhoneBadge = null;
  let hudWarningBadge = null;
  let visionAlertBanner = null;
  let visionBannerText = null;
  let phoneWarningModal = null;
  let headMovementModal = null;
  let multiplePersonsModal = null;
  let faceMissingModal = null;
  let gazeWarningModal = null;
  let prohibitedObjectModal = null;
  let livenessWarningModal = null;

  // Sidebar indicators
  let sidebarCamDot = null;
  let sidebarFaceBadge = null;
  let sidebarHeadBadge = null;
  let sidebarPhoneBadge = null;

  async function initialize(config = {}) {
    attemptId = config.attemptId || (window.ASSESSMENT_DATA ? window.ASSESSMENT_DATA.attemptId : null);
    csrfToken = config.csrfToken || (document.querySelector('meta[name="csrf-token"]') ? document.querySelector('meta[name="csrf-token"]').getAttribute("content") : "");

    // Resolve video elements
    primaryVideo = config.videoElement || document.getElementById("proctorPipVideo") || document.getElementById("sidebarProctorVideo") || document.getElementById("webcamPreview");

    // Collect all active canvas targets on current page
    canvasElements = [];
    const pipCanvas = document.getElementById("proctorPipCanvas");
    const sidebarCanvas = document.getElementById("sidebarProctorCanvas");
    const deviceCheckCanvas = document.getElementById("deviceCheckCanvas");
    if (config.canvasElement) canvasElements.push(config.canvasElement);
    if (pipCanvas && !canvasElements.includes(pipCanvas)) canvasElements.push(pipCanvas);
    if (sidebarCanvas && !canvasElements.includes(sidebarCanvas)) canvasElements.push(sidebarCanvas);
    if (deviceCheckCanvas && !canvasElements.includes(deviceCheckCanvas)) canvasElements.push(deviceCheckCanvas);

    // Cache HUD DOM references
    hudCamDot = document.getElementById("hudCamDot");
    hudFaceBadge = document.getElementById("hudFaceBadge");
    hudHeadBadge = document.getElementById("hudHeadBadge");
    hudPhoneBadge = document.getElementById("hudPhoneBadge");
    hudWarningBadge = document.getElementById("hudWarningBadge");
    visionAlertBanner = document.getElementById("visionAlertBanner");
    visionBannerText = document.getElementById("visionBannerText");

    // Cache Sidebar DOM references
    sidebarCamDot = document.getElementById("sidebarCamDot");
    sidebarFaceBadge = document.getElementById("sidebarFaceBadge");
    sidebarHeadBadge = document.getElementById("sidebarHeadBadge");
    sidebarPhoneBadge = document.getElementById("sidebarPhoneBadge");

    // Initialize Bootstrap Modals
    const phoneModalEl = document.getElementById("phoneWarningModal");
    if (phoneModalEl && window.bootstrap) {
      phoneWarningModal = new bootstrap.Modal(phoneModalEl, { backdrop: "static", keyboard: false });
    }

    const headModalEl = document.getElementById("headMovementModal");
    if (headModalEl && window.bootstrap) {
      headMovementModal = new bootstrap.Modal(headModalEl, { backdrop: "static", keyboard: false });
    }

    const multipleModalEl = document.getElementById("multiplePersonsModal");
    if (multipleModalEl && window.bootstrap) {
      multiplePersonsModal = new bootstrap.Modal(multipleModalEl, { backdrop: "static", keyboard: false });
    }

    const faceMissingEl = document.getElementById("faceMissingModal");
    if (faceMissingEl && window.bootstrap) {
      faceMissingModal = new bootstrap.Modal(faceMissingEl, { backdrop: "static", keyboard: false });
    }

    const gazeModalEl = document.getElementById("gazeWarningModal");
    if (gazeModalEl && window.bootstrap) {
      gazeWarningModal = new bootstrap.Modal(gazeModalEl, { backdrop: "static", keyboard: false });
    }

    const prohibitedModalEl = document.getElementById("prohibitedObjectModal");
    if (prohibitedModalEl && window.bootstrap) {
      prohibitedObjectModal = new bootstrap.Modal(prohibitedModalEl, { backdrop: "static", keyboard: false });
    }

    const livenessModalEl = document.getElementById("livenessWarningModal");
    if (livenessModalEl && window.bootstrap) {
      livenessWarningModal = new bootstrap.Modal(livenessModalEl, { backdrop: "static", keyboard: false });
    }

    // Attach neutral posture recalibration upon any modal dismissal
    [phoneModalEl, headModalEl, multipleModalEl, faceMissingEl, gazeModalEl, prohibitedModalEl, livenessModalEl].forEach(modalEl => {
      if (modalEl) {
        modalEl.addEventListener("hidden.bs.modal", () => {
          if (typeof HeadPoseModule !== "undefined" && HeadPoseModule.calibrateNeutral) {
            HeadPoseModule.calibrateNeutral();
          }
        });
      }
    });

    // Register Callbacks
    HeadPoseModule.setOnWarning(handleProctoringWarning);
    HeadPoseModule.setOnStatusUpdate(updateHeadPoseHUD);

    PhoneDetectorModule.setOnWarning(handleProctoringWarning);
    PhoneDetectorModule.setOnStatusUpdate(updatePhoneHUD);

    // Non-blocking concurrent model initialization
    Promise.all([
      HeadPoseModule.initialize(),
      PhoneDetectorModule.initialize()
    ]).catch(err => console.warn("Background proctoring init warning:", err));

    return { ready: true };
  }

  function start(stream = null) {
    if (isRunning) return;

    // Attach stream to video elements only if not already attached
    const sidebarVideo = document.getElementById("sidebarProctorVideo");
    const pipVideo = document.getElementById("proctorPipVideo");
    const previewVideo = document.getElementById("webcamPreview");
    const activeVid = sidebarVideo || pipVideo || previewVideo;

    if (stream) {
      if (sidebarVideo && sidebarVideo.srcObject !== stream) sidebarVideo.srcObject = stream;
      if (pipVideo && pipVideo.srcObject !== stream) pipVideo.srcObject = stream;
      if (previewVideo && previewVideo.srcObject !== stream) previewVideo.srcObject = stream;
    }

    if (!primaryVideo) {
      primaryVideo = activeVid;
    }

    if (primaryVideo && primaryVideo.paused) {
      primaryVideo.play().catch(() => {});
    }

    isRunning = true;
    updateCamHUD(true);

    if (samplingTimer) {
      clearInterval(samplingTimer);
    }

    // Real-Time Inference Loop (~4 FPS)
    samplingTimer = setInterval(async () => {
      if (!isRunning || isInferring) {
        return;
      }

      // Dynamically resolve current live video element
      const liveVid = document.getElementById("sidebarProctorVideo") ||
                      document.getElementById("proctorPipVideo") ||
                      document.getElementById("webcamPreview") ||
                      primaryVideo;

      if (!liveVid) return;

      if (liveVid.readyState < 2) {
        if (liveVid.paused) {
          liveVid.play().catch(() => {});
        }
        return;
      }

      isInferring = true;
      const now = Date.now();

      try {
        // 1. Process 3D Head Pose, Gaze, and Liveness
        let faceResult = (typeof HeadPoseModule !== "undefined") ?
          await HeadPoseModule.processVideoFrame(liveVid, now) : null;

        // 2. Process Multi-Class Threat Detection (Phones, Books, Extra Persons)
        const phoneResult = (typeof PhoneDetectorModule !== "undefined" && PhoneDetectorModule.isReady()) ?
          await PhoneDetectorModule.processVideoFrame(liveVid, now) : null;

        // Zero-latency fallback only while MediaPipe warms up
        const isMediaPipeActive = (typeof HeadPoseModule !== "undefined" && HeadPoseModule.isReady());
        if (!isMediaPipeActive && (!faceResult || !faceResult.faceDetected) && phoneResult && phoneResult.personBox) {
          const pb = phoneResult.personBox;
          const headW = pb.width * 0.65;
          const headH = pb.height * 0.40;
          const headX = pb.x + (pb.width - headW) / 2;
          const headY = pb.y;

          faceResult = {
            faceDetected: true,
            box: { x: headX, y: headY, width: headW, height: headH },
            color: "#10B981",
            direction: "NORMAL",
            isWarning: false,
            sustainedMs: 0,
            yaw: 0,
            pitch: 0,
            roll: 0,
            gaze: { ratioX: 0.5, ratioY: 0.5, state: "CENTER", isWarning: false, leftIris: null, rightIris: null },
            liveness: { isLive: true, blinkCount: 0, ear: 0.28, staticSuspected: false }
          };
        }

        // 3. Render High-Tech OpenCV-style HUD on all active canvases
        const activeCanvases = [
          document.getElementById("sidebarProctorCanvas"),
          document.getElementById("proctorPipCanvas"),
          document.getElementById("deviceCheckCanvas")
        ].filter(Boolean);

        for (const canvas of activeCanvases) {
          renderCanvasOverlay(liveVid, canvas, faceResult, phoneResult);
        }
      } catch (err) {
        console.warn("Proctoring sampling tick notice:", err);
      } finally {
        isInferring = false;
      }
    }, SAMPLING_INTERVAL_MS);
  }

  function stop() {
    isRunning = false;
    if (samplingTimer) {
      clearInterval(samplingTimer);
      samplingTimer = null;
    }
    const activeCanvases = [
      document.getElementById("sidebarProctorCanvas"),
      document.getElementById("proctorPipCanvas"),
      document.getElementById("deviceCheckCanvas")
    ].filter(Boolean);

    for (const canvas of activeCanvases) {
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    updateCamHUD(false);
  }

  /**
   * Render High-Precision OpenCV Bounding Boxes, Iris Reticles & Telemetry Overlays
   */
  function renderCanvasOverlay(video, canvas, faceResult, phoneResult) {
    const vw = video.videoWidth || 320;
    const vh = video.videoHeight || 240;

    if (canvas.width !== vw || canvas.height !== vh) {
      canvas.width = vw;
      canvas.height = vh;
    }

    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // =========================================================================
    // 1. Candidate Primary Face Bounding Box & Corner Brackets
    // =========================================================================
    if (faceResult && faceResult.faceDetected && faceResult.box) {
      const b = faceResult.box;
      const mirX = canvas.width - (b.x + b.width);
      const mirY = b.y;
      const w = b.width;
      const h = b.height;
      const color = faceResult.color || "#10B981";

      // Main rectangle
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.strokeRect(mirX, mirY, w, h);

      // OpenCV-style corner brackets
      const cornerLen = Math.max(8, Math.min(w, h) * 0.22);
      ctx.lineWidth = 4;
      // Top-Left
      ctx.beginPath();
      ctx.moveTo(mirX, mirY + cornerLen); ctx.lineTo(mirX, mirY); ctx.lineTo(mirX + cornerLen, mirY);
      ctx.stroke();
      // Top-Right
      ctx.beginPath();
      ctx.moveTo(mirX + w - cornerLen, mirY); ctx.lineTo(mirX + w, mirY); ctx.lineTo(mirX + w, mirY + cornerLen);
      ctx.stroke();
      // Bottom-Left
      ctx.beginPath();
      ctx.moveTo(mirX, mirY + h - cornerLen); ctx.lineTo(mirX, mirY + h); ctx.lineTo(mirX + cornerLen, mirY + h);
      ctx.stroke();
      // Bottom-Right
      ctx.beginPath();
      ctx.moveTo(mirX + w - cornerLen, mirY + h); ctx.lineTo(mirX + w, mirY + h); ctx.lineTo(mirX + w, mirY + h - cornerLen);
      ctx.stroke();

      // Label tag above face box
      let tagText = "Verified Candidate";
      if (faceResult.multipleFaces) {
        tagText = `⚠️ MULTIPLE FACES (${faceResult.numFaces})`;
      } else if (phoneResult && phoneResult.multiplePersonsDetected) {
        tagText = `⚠️ MULTIPLE PERSONS IN FRAME`;
      } else if (faceResult.isWarning && faceResult.direction !== "NORMAL") {
        tagText = `WARNING: Head ${faceResult.direction} (>2s)`;
      } else if (faceResult.gaze && faceResult.gaze.isWarning) {
        tagText = `⚠️ Gaze Away Detected`;
      } else if (faceResult.liveness && faceResult.liveness.staticSuspected) {
        tagText = `⚠️ Liveness Stalled`;
      } else if (faceResult.direction !== "NORMAL") {
        const sec = ((faceResult.sustainedMs || 0) / 1000).toFixed(1);
        tagText = `Turned: ${faceResult.direction} (${sec}s)`;
      }

      ctx.font = "bold 11px sans-serif";
      const metrics = ctx.measureText(tagText);
      const tagW = metrics.width + 12;
      const tagH = 18;
      const tagY = Math.max(0, mirY - tagH);

      ctx.fillStyle = color;
      ctx.fillRect(mirX, tagY, tagW, tagH);
      ctx.fillStyle = "#FFFFFF";
      ctx.fillText(tagText, mirX + 6, tagY + 13);

      // =========================================================================
      // 2. Iris Pupil Reticles (High-Tech Conjugate Ocular Gaze Tracking)
      // =========================================================================
      if (faceResult.gaze && faceResult.gaze.leftIris && faceResult.gaze.rightIris) {
        const mirLeftIrisX = canvas.width - faceResult.gaze.leftIris.x;
        const mirLeftIrisY = faceResult.gaze.leftIris.y;
        const mirRightIrisX = canvas.width - faceResult.gaze.rightIris.x;
        const mirRightIrisY = faceResult.gaze.rightIris.y;

        const reticleColor = faceResult.gaze.isWarning ? "#EF4444" : "#06B6D4";
        ctx.strokeStyle = reticleColor;
        ctx.lineWidth = 1.5;

        // Left Pupil Reticle
        ctx.beginPath();
        ctx.arc(mirLeftIrisX, mirLeftIrisY, 4, 0, 2 * Math.PI);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(mirLeftIrisX - 6, mirLeftIrisY); ctx.lineTo(mirLeftIrisX + 6, mirLeftIrisY);
        ctx.moveTo(mirLeftIrisX, mirLeftIrisY - 6); ctx.lineTo(mirLeftIrisX, mirLeftIrisY + 6);
        ctx.stroke();

        // Right Pupil Reticle
        ctx.beginPath();
        ctx.arc(mirRightIrisX, mirRightIrisY, 4, 0, 2 * Math.PI);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(mirRightIrisX - 6, mirRightIrisY); ctx.lineTo(mirRightIrisX + 6, mirRightIrisY);
        ctx.moveTo(mirRightIrisX, mirRightIrisY - 6); ctx.lineTo(mirRightIrisX, mirRightIrisY + 6);
        ctx.stroke();
      }
    }

    // =========================================================================
    // 3. Unauthorized Secondary Faces from MediaPipe
    // =========================================================================
    if (faceResult && faceResult.extraFaces && faceResult.extraFaces.length > 0) {
      for (const ef of faceResult.extraFaces) {
        const efMirX = canvas.width - (ef.x + ef.width);
        const efMirY = ef.y;
        const efW = ef.width;
        const efH = ef.height;

        ctx.strokeStyle = "#EF4444";
        ctx.lineWidth = 3;
        ctx.strokeRect(efMirX, efMirY, efW, efH);

        const efCorner = Math.max(8, Math.min(efW, efH) * 0.22);
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.moveTo(efMirX, efMirY + efCorner); ctx.lineTo(efMirX, efMirY); ctx.lineTo(efMirX + efCorner, efMirY);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(efMirX + efW - efCorner, efMirY); ctx.lineTo(efMirX + efW, efMirY); ctx.lineTo(efMirX + efW, efMirY + efCorner);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(efMirX, efMirY + efH - efCorner); ctx.lineTo(efMirX, efMirY + efH); ctx.lineTo(efMirX + efCorner, efMirY + efH);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(efMirX + efW - efCorner, efMirY + efH); ctx.lineTo(efMirX + efW, efMirY + efH); ctx.lineTo(efMirX + efW, efMirY + efH - efCorner);
        ctx.stroke();

        const efTag = "🚨 UNAUTHORIZED PERSON";
        ctx.font = "bold 11px sans-serif";
        const efMetrics = ctx.measureText(efTag);
        const efTagW = efMetrics.width + 12;
        const efTagY = Math.max(0, efMirY - 18);
        ctx.fillStyle = "#EF4444";
        ctx.fillRect(efMirX, efTagY, efTagW, 18);
        ctx.fillStyle = "#FFFFFF";
        ctx.fillText(efTag, efMirX + 6, efTagY + 13);
      }
    }

    // =========================================================================
    // 4. Secondary Individuals from COCO-SSD (IoU Verified Body Isolation)
    // =========================================================================
    if (phoneResult && phoneResult.extraPersons && phoneResult.extraPersons.length > 0) {
      for (const ep of phoneResult.extraPersons) {
        const epMirX = canvas.width - (ep.x + ep.width);
        const epMirY = ep.y;
        const epW = ep.width;
        const epH = ep.height;

        const overlapsExtraFace = faceResult && faceResult.extraFaces && faceResult.extraFaces.some(ef => {
          const efMirX = canvas.width - (ef.x + ef.width);
          return Math.abs(efMirX - epMirX) < epW * 0.5 && Math.abs(ef.y - epMirY) < epH * 0.5;
        });

        if (!overlapsExtraFace) {
          ctx.strokeStyle = "#EF4444";
          ctx.lineWidth = 3;
          ctx.strokeRect(epMirX, epMirY, epW, epH);

          const epCorner = Math.max(8, Math.min(epW, epH) * 0.22);
          ctx.lineWidth = 4;
          ctx.beginPath();
          ctx.moveTo(epMirX, epMirY + epCorner); ctx.lineTo(epMirX, epMirY); ctx.lineTo(epMirX + epCorner, epMirY);
          ctx.stroke();
          ctx.beginPath();
          ctx.moveTo(epMirX + epW - epCorner, epMirY); ctx.lineTo(epMirX + epW, epMirY); ctx.lineTo(epMirX + epW, epMirY + epCorner);
          ctx.stroke();
          ctx.beginPath();
          ctx.moveTo(epMirX, epMirY + epH - epCorner); ctx.lineTo(epMirX, epMirY + epH); ctx.lineTo(epMirX + epCorner, epMirY + epH);
          ctx.stroke();
          ctx.beginPath();
          ctx.moveTo(epMirX + epW - epCorner, epMirY + epH); ctx.lineTo(epMirX + epW, epMirY + epH); ctx.lineTo(epMirX + epW, epMirY + epH - epCorner);
          ctx.stroke();

          const epTag = "🚨 2ND PERSON DETECTED";
          ctx.font = "bold 11px sans-serif";
          const epMetrics = ctx.measureText(epTag);
          const epTagW = epMetrics.width + 12;
          const epTagY = Math.max(0, epMirY - 18);
          ctx.fillStyle = "#EF4444";
          ctx.fillRect(epMirX, epTagY, epTagW, 18);
          ctx.fillStyle = "#FFFFFF";
          ctx.fillText(epTag, epMirX + 6, epTagY + 13);
        }
      }
    }

    // =========================================================================
    // 5. Mobile Phone Detection Overlays
    // =========================================================================
    if (phoneResult && phoneResult.phoneDetected && phoneResult.phoneBox) {
      const pb = phoneResult.phoneBox;
      const pMirX = canvas.width - (pb.x + pb.width);
      const pMirY = pb.y;
      const pw = pb.width;
      const ph = pb.height;
      const pct = Math.round((phoneResult.phoneConfidence || 0.8) * 100);

      ctx.strokeStyle = "#EF4444";
      ctx.lineWidth = 3;
      ctx.strokeRect(pMirX, pMirY, pw, ph);

      const pCornerLen = Math.max(8, Math.min(pw, ph) * 0.25);
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.moveTo(pMirX, pMirY + pCornerLen); ctx.lineTo(pMirX, pMirY); ctx.lineTo(pMirX + pCornerLen, pMirY);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(pMirX + pw - pCornerLen, pMirY); ctx.lineTo(pMirX + pw, pMirY); ctx.lineTo(pMirX + pw, pMirY + pCornerLen);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(pMirX, pMirY + ph - pCornerLen); ctx.lineTo(pMirX, pMirY + ph); ctx.lineTo(pMirX + pCornerLen, pMirY + ph);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(pMirX + pw - pCornerLen, pMirY + ph); ctx.lineTo(pMirX + pw, pMirY + ph); ctx.lineTo(pMirX + pw, pMirY + ph - pCornerLen);
      ctx.stroke();

      const pTag = `📱 Mobile Device (${pct}%)`;
      ctx.font = "bold 11px sans-serif";
      const pMetrics = ctx.measureText(pTag);
      const pTagW = pMetrics.width + 12;
      const pTagY = Math.max(0, pMirY - 18);

      ctx.fillStyle = "#EF4444";
      ctx.fillRect(pMirX, pTagY, pTagW, 18);
      ctx.fillStyle = "#FFFFFF";
      ctx.fillText(pTag, pMirX + 6, pTagY + 13);
    }

    // =========================================================================
    // 6. Prohibited Academic Materials / External Displays Overlays
    // =========================================================================
    if (phoneResult && phoneResult.objectDetected && phoneResult.objectBox) {
      const ob = phoneResult.objectBox;
      const oMirX = canvas.width - (ob.x + ob.width);
      const oMirY = ob.y;
      const ow = ob.width;
      const oh = ob.height;
      const opct = Math.round((phoneResult.objectConfidence || 0.8) * 100);

      ctx.strokeStyle = "#F59E0B";
      ctx.lineWidth = 3;
      ctx.strokeRect(oMirX, oMirY, ow, oh);

      const oCornerLen = Math.max(8, Math.min(ow, oh) * 0.25);
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.moveTo(oMirX, oMirY + oCornerLen); ctx.lineTo(oMirX, oMirY); ctx.lineTo(oMirX + oCornerLen, oMirY);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(oMirX + ow - oCornerLen, oMirY); ctx.lineTo(oMirX + ow, oMirY); ctx.lineTo(oMirX + ow, oMirY + oCornerLen);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(oMirX, oMirY + oh - oCornerLen); ctx.lineTo(oMirX, oMirY + oh); ctx.lineTo(oMirX + oCornerLen, oMirY + oh);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(oMirX + ow - oCornerLen, oMirY + oh); ctx.lineTo(oMirX + ow, oMirY + oh); ctx.lineTo(oMirX + ow, oMirY + oh - oCornerLen);
      ctx.stroke();

      const oTag = `📚 ${ob.label} (${opct}%)`;
      ctx.font = "bold 11px sans-serif";
      const oMetrics = ctx.measureText(oTag);
      const oTagW = oMetrics.width + 12;
      const oTagY = Math.max(0, oMirY - 18);

      ctx.fillStyle = "#F59E0B";
      ctx.fillRect(oMirX, oTagY, oTagW, 18);
      ctx.fillStyle = "#000000";
      ctx.fillText(oTag, oMirX + 6, oTagY + 13);
    }

    // =========================================================================
    // 7. Real-Time Telemetry Overlay (Attitude & Liveness Dashboard)
    // =========================================================================
    const yawVal = faceResult ? (faceResult.deltaYaw || faceResult.yaw || 0) : 0;
    const pitchVal = faceResult ? (faceResult.deltaPitch || faceResult.pitch || 0) : 0;
    const blinkVal = faceResult && faceResult.liveness ? faceResult.liveness.blinkCount : 0;
    const isStatic = faceResult && faceResult.liveness && faceResult.liveness.staticSuspected;
    const livenessText = isStatic ? "⚠️ Liveness Stalled" : `🟢 Live (${blinkVal} blinks)`;
    const telemText = `Y: ${yawVal > 0 ? "+" : ""}${yawVal}° | P: ${pitchVal > 0 ? "+" : ""}${pitchVal}° | ${livenessText}`;

    ctx.font = "bold 9px monospace";
    const tMetrics = ctx.measureText(telemText);
    const tW = tMetrics.width + 12;
    const tH = 16;
    const tX = canvas.width - tW - 6;
    const tY = 6;

    ctx.fillStyle = "rgba(10, 15, 30, 0.80)";
    ctx.fillRect(tX, tY, tW, tH);
    ctx.fillStyle = isStatic ? "#F59E0B" : "#22D3EE";
    ctx.fillText(telemText, tX + 6, tY + 11);
  }

  /**
   * Handle warning dispatched by HeadPose or PhoneDetector
   */
  async function handleProctoringWarning(warning) {
    // If a modal is already displayed, suppress duplicate warnings
    if (document.querySelector(".modal.show")) {
      return;
    }

    const clientEventId = `${warning.type}-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;

    // 1. Display Candidate-Facing POPUP DIALOG BOXES & Banners on EVERY WARNING
    if (warning.type === "MOBILE_PHONE_DETECTED") {
      showPhoneModal(warning.message);
      showVisionBanner("MOBILE_PHONE", warning.message, "danger");
    } else if (warning.type === "UNAUTHORIZED_OBJECT_DETECTED") {
      showProhibitedObjectModal(warning.message, warning.box ? warning.box.label : "Prohibited Material");
      showVisionBanner("UNAUTHORIZED_OBJECT", warning.message, "danger");
    } else if (warning.type === "MULTIPLE_FACES_DETECTED" || warning.type === "MULTIPLE_PEOPLE_DETECTED") {
      showMultiplePersonsModal(warning.message);
      showVisionBanner("MULTIPLE_PERSONS", warning.message, "danger");
    } else if (warning.type === "HEAD_TURN_LEFT") {
      showHeadMovementModal(warning.message, "LEFT");
      showVisionBanner("HEAD_MOVEMENT", warning.message, "warning");
    } else if (warning.type === "HEAD_TURN_RIGHT") {
      showHeadMovementModal(warning.message, "RIGHT");
      showVisionBanner("HEAD_MOVEMENT", warning.message, "warning");
    } else if (warning.type === "HEAD_TILT_DOWN") {
      showHeadMovementModal(warning.message, "DOWN");
      showVisionBanner("HEAD_MOVEMENT", warning.message, "warning");
    } else if (warning.type === "GAZE_AWAY") {
      showGazeModal(warning.message, warning.direction);
      showVisionBanner("GAZE_AWAY", warning.message, "warning");
    } else if (warning.type === "STATIC_PHOTO_SUSPECTED") {
      showLivenessModal(warning.message);
      showVisionBanner("STATIC_PHOTO", warning.message, "danger");
    } else if (warning.type === "FACE_NOT_DETECTED") {
      showFaceMissingModal(warning.message);
      showVisionBanner("FACE_MISSING", warning.message, "danger");
    } else if (warning.type === "FACE_RESTORED") {
      dismissVisionBanner();
    }

    // 2. Send structured event to Flask backend asynchronously
    sendEventToBackend({
      event_type: warning.type,
      confidence: warning.confidence,
      duration_ms: warning.durationMs,
      client_event_id: clientEventId,
      metadata: { direction: warning.direction || null }
    }).then(result => {
      if (result && result.vision_warning_count !== undefined) {
        visionWarningCount = result.vision_warning_count;
        updateWarningCountHUD(visionWarningCount);
      }
    }).catch(() => {});
  }

  async function sendEventToBackend(payload) {
    if (!attemptId) return null;

    try {
      const resp = await fetch(`/api/assessment/${attemptId}/proctoring-event`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken
        },
        body: JSON.stringify(payload)
      });

      if (!resp.ok) return null;
      return await resp.json();
    } catch (e) {
      console.error("Failed to send proctoring event:", e);
      return null;
    }
  }

  function showVisionBanner(type, message, level = "warning") {
    if (bannerDismissTimeout) {
      clearTimeout(bannerDismissTimeout);
    }

    if (visionAlertBanner && visionBannerText) {
      visionAlertBanner.className = `alert alert-${level} d-flex align-items-center justify-content-between py-2 px-3 mb-3 border border-${level} shadow-sm`;
      visionBannerText.textContent = message;
      visionAlertBanner.classList.remove("d-none");

      bannerDismissTimeout = setTimeout(() => {
        dismissVisionBanner();
      }, 9000);
    }
  }

  function dismissVisionBanner() {
    if (visionAlertBanner) {
      visionAlertBanner.classList.add("d-none");
    }
  }

  function showPhoneModal(message) {
    if (!phoneWarningModal) {
      const phoneModalEl = document.getElementById("phoneWarningModal");
      if (phoneModalEl && window.bootstrap) {
        phoneWarningModal = new bootstrap.Modal(phoneModalEl, { backdrop: "static", keyboard: false });
      }
    }
    if (phoneWarningModal) {
      const modalMsg = document.getElementById("phoneWarningModalText");
      if (modalMsg && message) modalMsg.textContent = message;
      phoneWarningModal.show();
    }
  }

  function showHeadMovementModal(message, direction) {
    if (!headMovementModal) {
      const headModalEl = document.getElementById("headMovementModal");
      if (headModalEl && window.bootstrap) {
        headMovementModal = new bootstrap.Modal(headModalEl, { backdrop: "static", keyboard: false });
      }
    }
    if (headMovementModal) {
      const titleEl = document.getElementById("headMovementModalTitle");
      const msgEl = document.getElementById("headMovementModalText");
      const iconEl = document.getElementById("headMovementIcon");

      if (direction === "LEFT") {
        if (titleEl) titleEl.textContent = "Head Turned Left Detected (>2s)";
        if (iconEl) iconEl.className = "bi bi-arrow-left-circle-fill text-warning";
      } else if (direction === "RIGHT") {
        if (titleEl) titleEl.textContent = "Head Turned Right Detected (>2s)";
        if (iconEl) iconEl.className = "bi bi-arrow-right-circle-fill text-warning";
      } else if (direction === "DOWN") {
        if (titleEl) titleEl.textContent = "Head Tilted Down Detected (>2s)";
        if (iconEl) iconEl.className = "bi bi-arrow-down-circle-fill text-warning";
      } else {
        if (titleEl) titleEl.textContent = "Head Movement Detected (>2s)";
        if (iconEl) iconEl.className = "bi bi-arrow-left-right text-warning";
      }

      if (msgEl && message) {
        msgEl.textContent = message;
      }
      headMovementModal.show();
    }
  }

  function showMultiplePersonsModal(message) {
    if (!multiplePersonsModal) {
      const el = document.getElementById("multiplePersonsModal");
      if (el && window.bootstrap) {
        multiplePersonsModal = new bootstrap.Modal(el, { backdrop: "static", keyboard: false });
      }
    }
    if (multiplePersonsModal) {
      const msgEl = document.getElementById("multiplePersonsModalText");
      if (msgEl && message) msgEl.textContent = message;
      multiplePersonsModal.show();
    }
  }

  function showFaceMissingModal(message) {
    if (!faceMissingModal) {
      const el = document.getElementById("faceMissingModal");
      if (el && window.bootstrap) {
        faceMissingModal = new bootstrap.Modal(el, { backdrop: "static", keyboard: false });
      }
    }
    if (faceMissingModal) {
      const msgEl = document.getElementById("faceMissingModalText");
      if (msgEl && message) msgEl.textContent = message;
      faceMissingModal.show();
    }
  }

  function showGazeModal(message, direction) {
    if (!gazeWarningModal) {
      const el = document.getElementById("gazeWarningModal");
      if (el && window.bootstrap) {
        gazeWarningModal = new bootstrap.Modal(el, { backdrop: "static", keyboard: false });
      }
    }
    if (gazeWarningModal) {
      const titleEl = document.getElementById("gazeWarningModalTitle");
      const msgEl = document.getElementById("gazeWarningModalText");
      if (titleEl && direction) {
        titleEl.textContent = `Eye Gaze Drift Detected (${direction.replace('_', ' ')})`;
      }
      if (msgEl && message) msgEl.textContent = message;
      gazeWarningModal.show();
    }
  }

  function showProhibitedObjectModal(message, label) {
    if (!prohibitedObjectModal) {
      const el = document.getElementById("prohibitedObjectModal");
      if (el && window.bootstrap) {
        prohibitedObjectModal = new bootstrap.Modal(el, { backdrop: "static", keyboard: false });
      }
    }
    if (prohibitedObjectModal) {
      const titleEl = document.getElementById("prohibitedObjectModalTitle");
      const msgEl = document.getElementById("prohibitedObjectModalText");
      if (titleEl && label) {
        titleEl.textContent = `Unauthorized Item: ${label}`;
      }
      if (msgEl && message) msgEl.textContent = message;
      prohibitedObjectModal.show();
    }
  }

  function showLivenessModal(message) {
    if (!livenessWarningModal) {
      const el = document.getElementById("livenessWarningModal");
      if (el && window.bootstrap) {
        livenessWarningModal = new bootstrap.Modal(el, { backdrop: "static", keyboard: false });
      }
    }
    if (livenessWarningModal) {
      const msgEl = document.getElementById("livenessWarningModalText");
      if (msgEl && message) msgEl.textContent = message;
      livenessWarningModal.show();
    }
  }

  // HUD Update Handlers
  function updateCamHUD(isActive) {
    if (hudCamDot) {
      hudCamDot.className = isActive ? "status-dot bg-success" : "status-dot bg-danger";
      hudCamDot.title = isActive ? "Camera Active" : "Camera Disconnected";
    }
    if (sidebarCamDot) {
      sidebarCamDot.className = isActive ? "status-dot bg-success me-2" : "status-dot bg-danger me-2";
    }
  }

  function updateHeadPoseHUD(status) {
    // Header HUD
    if (hudFaceBadge) {
      if (status.multipleFaces) {
        hudFaceBadge.className = "badge bg-danger bg-opacity-25 text-danger border border-danger border-opacity-40";
        hudFaceBadge.innerHTML = `<i class="bi bi-people-fill me-1"></i> Multiple Faces (${status.numFaces})`;
      } else if (status.faceDetected) {
        if (status.liveness && status.liveness.staticSuspected) {
          hudFaceBadge.className = "badge bg-warning bg-opacity-25 text-warning border border-warning border-opacity-40";
          hudFaceBadge.innerHTML = '<i class="bi bi-exclamation-triangle-fill me-1"></i> Liveness Stalled';
        } else {
          hudFaceBadge.className = "badge bg-success bg-opacity-20 text-success border border-success border-opacity-30";
          hudFaceBadge.innerHTML = '<i class="bi bi-person-check-fill me-1"></i> Face Verified';
        }
      } else {
        hudFaceBadge.className = "badge bg-danger bg-opacity-20 text-danger border border-danger border-opacity-30";
        hudFaceBadge.innerHTML = '<i class="bi bi-person-x-fill me-1"></i> No Face';
      }
    }

    if (hudHeadBadge) {
      if (!status.faceDetected) {
        hudHeadBadge.className = "badge bg-dark text-muted border border-secondary";
        hudHeadBadge.textContent = "Orientation: --";
      } else if (status.gaze && status.gaze.isWarning) {
        hudHeadBadge.className = "badge bg-warning bg-opacity-25 text-warning border border-warning border-opacity-40";
        hudHeadBadge.innerHTML = '<i class="bi bi-eye me-1"></i> Gaze Away';
      } else if (status.direction === "NORMAL") {
        hudHeadBadge.className = "badge bg-primary bg-opacity-20 text-cyan border border-info border-opacity-30";
        hudHeadBadge.innerHTML = '<i class="bi bi-compass me-1"></i> Center';
      } else {
        hudHeadBadge.className = "badge bg-warning bg-opacity-25 text-warning border border-warning border-opacity-40";
        hudHeadBadge.innerHTML = `<i class="bi bi-arrow-repeat me-1"></i> ${status.direction}`;
      }
    }

    // Sidebar HUD
    if (sidebarFaceBadge) {
      if (status.multipleFaces) {
        sidebarFaceBadge.className = "badge bg-danger bg-opacity-25 text-danger border border-danger border-opacity-40";
        sidebarFaceBadge.innerHTML = `<i class="bi bi-people-fill me-1"></i> Multiple Faces (${status.numFaces})`;
      } else if (status.faceDetected) {
        sidebarFaceBadge.className = "badge bg-success bg-opacity-20 text-success border border-success border-opacity-30";
        sidebarFaceBadge.innerHTML = '<i class="bi bi-person-check-fill me-1"></i> Face Verified';
      } else {
        sidebarFaceBadge.className = "badge bg-danger bg-opacity-20 text-danger border border-danger border-opacity-30";
        sidebarFaceBadge.innerHTML = '<i class="bi bi-person-x-fill me-1"></i> No Face';
      }
    }

    if (sidebarHeadBadge) {
      if (!status.faceDetected) {
        sidebarHeadBadge.textContent = "Orientation: --";
        sidebarHeadBadge.className = "text-muted small";
      } else if (status.gaze && status.gaze.isWarning) {
        sidebarHeadBadge.textContent = "Gaze: Diverted";
        sidebarHeadBadge.className = "text-warning fw-medium small";
      } else if (status.direction === "NORMAL") {
        sidebarHeadBadge.textContent = "Orientation: Center";
        sidebarHeadBadge.className = "text-cyan fw-medium small";
      } else {
        sidebarHeadBadge.textContent = `Turned: ${status.direction}`;
        sidebarHeadBadge.className = "text-warning fw-medium small";
      }
    }
  }

  function updatePhoneHUD(status) {
    if (hudPhoneBadge) {
      if (!status.isAvailable) {
        hudPhoneBadge.className = "badge bg-dark text-muted border border-secondary";
        hudPhoneBadge.innerHTML = '<i class="bi bi-shield-check me-1"></i> Guard Active';
      } else if (status.phoneDetected) {
        hudPhoneBadge.className = "badge bg-danger bg-opacity-25 text-danger border border-danger border-opacity-40";
        hudPhoneBadge.innerHTML = '<i class="bi bi-phone-vibrate-fill me-1"></i> Phone Alert';
      } else if (status.objectDetected) {
        hudPhoneBadge.className = "badge bg-warning bg-opacity-25 text-warning border border-warning border-opacity-40";
        hudPhoneBadge.innerHTML = '<i class="bi bi-book-half me-1"></i> Prohibited Item';
      } else {
        hudPhoneBadge.className = "badge bg-success bg-opacity-20 text-success border border-success border-opacity-30";
        hudPhoneBadge.innerHTML = '<i class="bi bi-shield-check me-1"></i> AI Guard Active';
      }
    }

    if (sidebarPhoneBadge) {
      if (status.phoneDetected) {
        sidebarPhoneBadge.className = "text-danger fw-bold small";
        sidebarPhoneBadge.innerHTML = '<i class="bi bi-phone-vibrate-fill me-1"></i>Phone Alert';
      } else if (status.objectDetected) {
        sidebarPhoneBadge.className = "text-warning fw-bold small";
        sidebarPhoneBadge.innerHTML = '<i class="bi bi-book-half me-1"></i>Prohibited Item';
      } else {
        sidebarPhoneBadge.className = "text-success fw-medium small";
        sidebarPhoneBadge.innerHTML = '<i class="bi bi-shield-check me-1"></i>AI Guard Active';
      }
    }

    if (sidebarFaceBadge && status.multiplePersonsDetected) {
      sidebarFaceBadge.className = "badge bg-danger bg-opacity-25 text-danger border border-danger border-opacity-40";
      sidebarFaceBadge.innerHTML = `<i class="bi bi-people-fill me-1"></i> Multiple People (${status.personCount})`;
    }
  }

  function updateWarningCountHUD(count) {
    if (hudWarningBadge) {
      hudWarningBadge.textContent = `${count} Warnings`;
      if (count > 0) {
        hudWarningBadge.className = "badge bg-warning bg-opacity-25 text-warning border border-warning border-opacity-40";
      } else {
        hudWarningBadge.className = "badge bg-dark text-secondary border border-secondary-subtle";
      }
    }
  }

  return {
    initialize,
    start,
    stop,
    dismissVisionBanner,
    getWarningCount: () => visionWarningCount,
    renderCanvasOverlay
  };
})();
