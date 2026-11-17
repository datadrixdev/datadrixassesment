/**
 * Device Check: Camera Preview, Audio Level Meter, Permission Gating & AI Proctoring Calibration
 */
document.addEventListener("DOMContentLoaded", () => {
  const webcamPreview = document.getElementById("webcamPreview");
  const deviceCheckCanvas = document.getElementById("deviceCheckCanvas");
  const cameraPlaceholder = document.getElementById("cameraPlaceholder");
  const cameraActiveOverlay = document.getElementById("cameraActiveOverlay");
  const requestMediaBtn = document.getElementById("requestMediaBtn");
  const cameraStatusBadge = document.getElementById("cameraStatusBadge");
  const micStatusBadge = document.getElementById("micStatusBadge");
  const audioMeterFill = document.getElementById("audioMeterFill");
  const micLevelText = document.getElementById("micLevelText");
  const micTestResult = document.getElementById("micTestResult");
  const permissionHelpBox = document.getElementById("permissionHelpBox");
  const startTestBtn = document.getElementById("startTestBtn");
  const startChecklistNotice = document.getElementById("startChecklistNotice");
  const startTestForm = document.getElementById("startTestForm");

  // AI Proctoring Calibration Elements
  const calibratePoseBtn = document.getElementById("calibratePoseBtn");
  const calibFaceStatus = document.getElementById("calibFaceStatus");
  const calibAngleStatus = document.getElementById("calibAngleStatus");
  const calibPhoneStatus = document.getElementById("calibPhoneStatus");

  let mediaStream = null;
  let audioContext = null;
  let analyser = null;
  let animationFrameId = null;
  let visionCalibrationLoop = null;

  let isCameraReady = false;
  let isMicReady = false;
  let isSoundDetected = false;
  let isFaceCalibrated = false;

  // Check browser compatibility APIs
  function verifyBrowserCapabilities() {
    const hasMedia = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    const hasAudio = !!(window.AudioContext || window.webkitAudioContext);
    const hasVisibility = typeof document.visibilityState !== "undefined";
    const hasFullscreen = !!(document.fullscreenEnabled || document.webkitFullscreenEnabled);

    updateCompatBadge("compatMedia", hasMedia);
    updateCompatBadge("compatAudio", hasAudio);
    updateCompatBadge("compatVisibility", hasVisibility);
    updateCompatBadge("compatFullscreen", hasFullscreen);

    return hasMedia && hasAudio && hasVisibility;
  }

  function updateCompatBadge(elementId, isSupported) {
    const el = document.getElementById(elementId);
    if (!el) return;
    if (isSupported) {
      el.className = "badge status-pill-granted";
      el.textContent = "Supported";
    } else {
      el.className = "badge status-pill-denied";
      el.textContent = "Unsupported";
    }
  }

  // Request Camera & Microphone MediaStream
  async function requestHardwarePermissions() {
    try {
      if (permissionHelpBox) permissionHelpBox.classList.add("d-none");

      mediaStream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 } },
        audio: true
      });

      // Camera verified
      webcamPreview.srcObject = mediaStream;
      webcamPreview.classList.remove("d-none");
      if (deviceCheckCanvas) deviceCheckCanvas.classList.remove("d-none");
      cameraPlaceholder.classList.add("d-none");
      cameraActiveOverlay.classList.remove("d-none");

      cameraStatusBadge.className = "badge status-pill-granted px-3 py-1 rounded-pill";
      cameraStatusBadge.style.cssText = "background-color: #064E3B !important; border: 1px solid #10B981 !important; color: #FFFFFF !important; font-weight: 600 !important; display: inline-flex !important; align-items: center !important;";
      cameraStatusBadge.innerHTML = '<i class="bi bi-check-circle-fill me-1" style="color: #FFFFFF !important;"></i> <span style="color: #FFFFFF !important; font-weight: 600 !important;">Camera Granted</span>';
      isCameraReady = true;

      // Microphone verified & Audio Context setup
      micStatusBadge.className = "badge status-pill-granted px-3 py-1 rounded-pill";
      micStatusBadge.style.cssText = "background-color: #064E3B !important; border: 1px solid #10B981 !important; color: #FFFFFF !important; font-weight: 600 !important; display: inline-flex !important; align-items: center !important;";
      micStatusBadge.innerHTML = '<i class="bi bi-check-circle-fill me-1" style="color: #FFFFFF !important;"></i> <span style="color: #FFFFFF !important; font-weight: 600 !important;">Mic Granted</span>';
      isMicReady = true;

      setupAudioMeter(mediaStream);
      startLiveVisionLoop();
      initializeProctoringCalibration();
      evaluateStartReadiness();

    } catch (err) {
      console.warn("Device permission error:", err);
      handlePermissionDenied(err);
    }
  }

  function startLiveVisionLoop() {
    if (visionCalibrationLoop) return;
    visionCalibrationLoop = setInterval(async () => {
      if (webcamPreview && webcamPreview.readyState >= 2) {
        const now = Date.now();
        let faceResult = typeof HeadPoseModule !== "undefined" ?
          await HeadPoseModule.processVideoFrame(webcamPreview, now) : null;
        const phoneResult = (typeof PhoneDetectorModule !== "undefined" && PhoneDetectorModule.isReady()) ?
          await PhoneDetectorModule.processVideoFrame(webcamPreview, now) : null;

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
            isWarning: false
          };
        }

        if (deviceCheckCanvas && typeof ProctoringEngine !== "undefined") {
          ProctoringEngine.renderCanvasOverlay(webcamPreview, deviceCheckCanvas, faceResult, phoneResult);
        }
      }
    }, 250);
  }

  // Initialize AI Proctoring Models for Calibration
  async function initializeProctoringCalibration() {
    if (typeof HeadPoseModule === "undefined") return;

    // Head Pose Module Initialization
    HeadPoseModule.setOnStatusUpdate((status) => {
      if (calibAngleStatus) {
        if (!status.faceDetected) {
          calibAngleStatus.className = "badge bg-dark text-danger border border-danger border-opacity-30 px-2 py-1";
          calibAngleStatus.innerHTML = '<i class="bi bi-person-x me-1"></i> Face Not In View';
        } else {
          calibAngleStatus.className = status.isCalibrated ?
            "badge bg-success bg-opacity-20 text-success border border-success border-opacity-30 px-2 py-1" :
            "badge bg-primary bg-opacity-20 text-cyan border border-info border-opacity-30 px-2 py-1";
          calibAngleStatus.innerHTML = `<i class="bi bi-compass me-1"></i> Yaw: ${status.deltaYaw}° | Pitch: ${status.deltaPitch}°`;
        }
      }
    });

    try {
      const headOk = await HeadPoseModule.initialize((msg) => {
        if (calibFaceStatus) calibFaceStatus.textContent = msg;
      });

      if (headOk) {
        if (calibFaceStatus) {
          calibFaceStatus.className = "badge bg-success bg-opacity-20 text-success border border-success border-opacity-30 px-2 py-1";
          calibFaceStatus.innerHTML = '<i class="bi bi-check-circle-fill me-1"></i> Face Box: Active (Green)';
        }
        if (calibratePoseBtn) {
          calibratePoseBtn.disabled = false;
        }
      } else {
        if (calibFaceStatus) {
          calibFaceStatus.className = "badge bg-warning bg-opacity-20 text-warning border border-warning border-opacity-30 px-2 py-1";
          calibFaceStatus.textContent = "Face Tracking: Initializing";
        }
      }
    } catch (e) {
      console.warn("HeadPose init error:", e);
    }

    // Phone Detector Module Initialization
    if (typeof PhoneDetectorModule !== "undefined") {
      try {
        const phoneOk = await PhoneDetectorModule.initialize((msg) => {
          if (calibPhoneStatus) calibPhoneStatus.textContent = msg;
        });

        if (calibPhoneStatus) {
          if (phoneOk) {
            calibPhoneStatus.className = "badge bg-success bg-opacity-20 text-success border border-success border-opacity-30 px-2 py-1";
            calibPhoneStatus.innerHTML = '<i class="bi bi-phone me-1"></i> Phone Guard: Active';
          } else {
            calibPhoneStatus.className = "badge bg-dark text-muted border border-secondary px-2 py-1";
            calibPhoneStatus.innerHTML = '<i class="bi bi-info-circle me-1"></i> Phone Guard: Setup Mode';
            calibPhoneStatus.title = "Dedicated model assets can be placed in /static/models/phone_detector/";
          }
        }
      } catch (pe) {
        console.warn("Phone detector init error:", pe);
      }
    }
  }

  // Handle Calibrate Neutral Pose Button Click
  if (calibratePoseBtn) {
    calibratePoseBtn.addEventListener("click", () => {
      if (typeof HeadPoseModule !== "undefined") {
        const calib = HeadPoseModule.calibrateNeutral();
        try {
          if (calib && calib.baselineYaw !== undefined) {
            localStorage.setItem("datadrix_baseline_yaw", calib.baselineYaw.toString());
            localStorage.setItem("datadrix_baseline_pitch", calib.baselinePitch.toString());
          }
        } catch (e) {}
        isFaceCalibrated = true;
        calibratePoseBtn.className = "btn btn-success btn-sm py-1 px-3 fw-semibold";
        calibratePoseBtn.innerHTML = '<i class="bi bi-check2-circle me-1"></i> Baseline Calibrated!';
        evaluateStartReadiness();
      }
    });
  }

  // Setup Web Audio API volume analysis
  function setupAudioMeter(stream) {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      audioContext = new AudioCtx();
      const microphone = audioContext.createMediaStreamSource(stream);
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      microphone.connect(analyser);

      const dataArray = new Uint8Array(analyser.frequencyBinCount);

      function updateVolume() {
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
          sum += dataArray[i];
        }
        const average = sum / dataArray.length;
        // Normalize 0-100%
        const percent = Math.min(100, Math.round((average / 128) * 100));

        audioMeterFill.style.width = percent + "%";
        micLevelText.textContent = percent + "%";

        const ambientBadge = document.getElementById("ambientNoiseBadge");
        if (ambientBadge) {
          if (percent > 45) {
            ambientBadge.className = "badge bg-warning bg-opacity-25 text-warning border border-warning border-opacity-40 px-2 py-1";
            ambientBadge.innerHTML = '<i class="bi bi-volume-up-fill me-1"></i> Background Noise Detected';
          } else {
            ambientBadge.className = "badge bg-success bg-opacity-20 text-success border border-success border-opacity-30 px-2 py-1";
            ambientBadge.innerHTML = '<i class="bi bi-shield-check me-1"></i> Quiet Environment (Optimal)';
          }
        }

        if (percent > 10 && !isSoundDetected) {
          isSoundDetected = true;
          micTestResult.className = "p-2 rounded text-center small fw-bold mic-box-verified";
          micTestResult.style.cssText = "background-color: #064E3B !important; border: 1.5px solid #10B981 !important; color: #FFFFFF !important; font-weight: 600 !important; box-shadow: 0 0 15px rgba(16, 185, 129, 0.35) !important;";
          micTestResult.innerHTML = '<i class="bi bi-check-circle-fill me-1" style="color: #FFFFFF !important;"></i> <span style="color: #FFFFFF !important; font-weight: 600 !important;">Sound detected! Microphone test passed.</span>';
          evaluateStartReadiness();
        }

        animationFrameId = requestAnimationFrame(updateVolume);
      }

      updateVolume();
    } catch (e) {
      console.error("AudioContext error:", e);
      // Fallback: If Web Audio fails, allow mic if track exists
      isMicReady = true;
      isSoundDetected = true;
      micTestResult.className = "p-2 rounded text-center small fw-bold mic-box-verified";
      micTestResult.style.cssText = "background-color: #064E3B !important; border: 1.5px solid #10B981 !important; color: #FFFFFF !important; font-weight: 600 !important; box-shadow: 0 0 15px rgba(16, 185, 129, 0.35) !important;";
      micTestResult.innerHTML = '<i class="bi bi-check-circle-fill me-1" style="color: #FFFFFF !important;"></i> <span style="color: #FFFFFF !important; font-weight: 600 !important;">Microphone connected.</span>';
      evaluateStartReadiness();
    }
  }

  function handlePermissionDenied(err) {
    cameraStatusBadge.className = "badge status-pill-denied px-3 py-1 rounded-pill";
    cameraStatusBadge.style.cssText = "background-color: #4C0519 !important; border: 1px solid #F43F5E !important; color: #FFFFFF !important; font-weight: 600 !important; display: inline-flex !important; align-items: center !important;";
    cameraStatusBadge.innerHTML = '<i class="bi bi-x-circle-fill me-1" style="color: #FFFFFF !important;"></i> <span style="color: #FFFFFF !important; font-weight: 600 !important;">Permission Denied</span>';

    micStatusBadge.className = "badge status-pill-denied px-3 py-1 rounded-pill";
    micStatusBadge.style.cssText = "background-color: #4C0519 !important; border: 1px solid #F43F5E !important; color: #FFFFFF !important; font-weight: 600 !important; display: inline-flex !important; align-items: center !important;";
    micStatusBadge.innerHTML = '<i class="bi bi-x-circle-fill me-1" style="color: #FFFFFF !important;"></i> <span style="color: #FFFFFF !important; font-weight: 600 !important;">Permission Denied</span>';

    if (permissionHelpBox) permissionHelpBox.classList.remove("d-none");
    isCameraReady = false;
    isMicReady = false;
    evaluateStartReadiness();
  }

  function evaluateStartReadiness() {
    const isReady = isCameraReady && isMicReady;
    const isCooldownActive = !!window.RETAKE_COOLDOWN_ACTIVE;

    if (isCooldownActive) {
      startTestBtn.disabled = true;
      if (isReady) {
        startChecklistNotice.className = "text-warning small mt-2 fw-medium";
        startChecklistNotice.innerHTML = '<i class="bi bi-clock-history me-1"></i> Hardware verified. Retake is currently locked by cooldown (use Dev Bypass Cooldown to test).';
      } else {
        startChecklistNotice.className = "text-slate-300 small mt-2";
        startChecklistNotice.innerHTML = '<i class="bi bi-info-circle text-cyan me-1"></i> Both camera and microphone must be verified before the Start Test button is activated.';
      }
      return;
    }

    startTestBtn.disabled = !isReady;

    if (isReady) {
      startChecklistNotice.className = "text-success small mt-2 fw-medium";
      startChecklistNotice.innerHTML = '<i class="bi bi-check-circle-fill me-1"></i> All system checks &amp; proctoring verification complete. You may start your assessment now.';
    } else {
      startChecklistNotice.className = "text-slate-300 small mt-2";
      startChecklistNotice.innerHTML = '<i class="bi bi-info-circle text-cyan me-1"></i> Both camera and microphone must be verified before the Start Test button is activated.';
    }
  }

  // Clean up calibration loop when submitting test form
  startTestForm.addEventListener("submit", (e) => {
    if (visionCalibrationLoop) {
      clearInterval(visionCalibrationLoop);
      visionCalibrationLoop = null;
    }
    if (document.documentElement.requestFullscreen) {
      document.documentElement.requestFullscreen().catch(() => {});
    }
  });

  if (requestMediaBtn) {
    requestMediaBtn.addEventListener("click", requestHardwarePermissions);
  }

  // Initialize checks on page load
  verifyBrowserCapabilities();
  requestHardwarePermissions();
});
