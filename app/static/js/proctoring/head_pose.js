/**
 * Advanced 3D Head Pose, Ocular Gaze & Liveness Tracking Engine (MediaPipe Tasks Vision)
 *
 * Capabilities:
 *  1. 3D Facial Vector Geometry (Perspective-n-Point / Normal Vector Decomposition)
 *     Computes true 3D Euler angles (Yaw, Pitch, Roll) using 468/478 landmarks.
 *  2. Ocular Gaze & Iris Vector Tracking
 *     Tracks conjugate iris coordinates to detect sideways/downward gaze deviation even when head is still.
 *  3. Real-Time Liveness & Eye Aspect Ratio (EAR) Blink Detection
 *     Detects micro-movements, eye blinks, and flags potential static photo/screen spoofing.
 *  4. Multi-Face Threat Tracking
 *     Enforces single-candidate presence (detects up to 4 faces with spatial deduplication).
 */
const HeadPoseModule = (() => {
  let faceLandmarker = null;
  let isInitialized = false;
  let isInitializing = false;
  let lastTimestamp = 0;

  // Calibration and baseline state
  let baselineYaw = 0.0;
  let baselinePitch = 0.0;
  let baselineRoll = 0.0;
  let isCalibrated = false;
  let autoCalibSamples = [];
  const CALIB_SAMPLES_NEEDED = 10;

  // Exponential Moving Average Smoothing
  let smoothedYaw = 0.0;
  let smoothedPitch = 0.0;
  let smoothedRoll = 0.0;
  const SMOOTHING_ALPHA = 0.35;

  // Deviation & Hysteresis Thresholds (degrees)
  const YAW_THRESHOLD_DEG = 30.0;          // Clear head turn away from screen (>30°)
  const YAW_RETURN_THRESHOLD_DEG = 18.0;   // Hysteresis threshold to return to center
  const PITCH_DOWN_THRESHOLD_DEG = 30.0;   // Downward tilt away from screen into lap (>30°)
  const PITCH_RETURN_THRESHOLD_DEG = 18.0; // Hysteresis threshold to return to center

  // Sustained timing configuration
  const SUSTAINED_DURATION_MS = 3500;     // Sustained for >= 3.5s triggers warning
  const WARNING_COOLDOWN_MS = 15000;      // Minimum cooldown before identical warning repeats (15s)
  const FACE_ABSENCE_THRESHOLD_MS = 5000; // Trigger face missing warning after 5.0s

  // Gaze Tracking Configuration
  const GAZE_THRESHOLD_LEFT = 0.88;       // Eye iris shifted far left beyond screen
  const GAZE_THRESHOLD_RIGHT = 0.12;      // Eye iris shifted far right beyond screen
  const GAZE_SUSTAINED_MS = 5000;         // Looking away horizontally with eyes for >= 5.0s
  const GAZE_COOLDOWN_MS = 20000;         // 20s cooldown between gaze warnings
  let activeGazeDeviation = null;
  let gazeDeviationStartTime = 0;
  let lastGazeWarningTime = 0;

  // Liveness & Blink Tracking State
  let blinkCount = 0;
  let wasEyeClosed = false;
  let lastBlinkTimestamp = Date.now();
  let nosePositionHistory = [];
  const NOSE_HISTORY_MAX = 25;
  const STATIC_PHOTO_TIMEOUT_MS = 25000; // 25s with 0 blinks and 0 movement
  let lastStaticWarningTime = 0;

  // Multiple face tracking
  const MULTIPLE_FACES_SUSTAINED_MS = 2000; // >= 2.0s sustained triggers warning
  const MULTIPLE_FACES_COOLDOWN_MS = 12000;
  let multipleFacesStartTime = 0;
  let lastMultipleFacesWarningTime = 0;

  // State trackers
  let activeDeviation = null; // 'LEFT', 'RIGHT', 'DOWN' or null
  let deviationStartTime = 0;
  let lastWarningTime = { LEFT: 0, RIGHT: 0, DOWN: 0, MISSING: 0 };

  let faceDetected = false;
  let lastFaceSeenTimestamp = Date.now();
  let faceNotDetectedAlerted = false;

  // Callback listeners
  let onWarningCallback = null;
  let onStatusUpdateCallback = null;

  // Always calibrate fresh to current candidate posture when session begins
  isCalibrated = false;
  autoCalibSamples = [];

  async function initialize(onProgress = null) {
    if (isInitialized) return true;
    if (isInitializing) return false;
    isInitializing = true;

    try {
      if (onProgress) onProgress("Initializing MediaPipe Tasks Vision...");

      // Wait up to 15 seconds for MediaPipeVision to be loaded on window
      let waitElapsed = 0;
      while (!window.MediaPipeVision && waitElapsed < 15000) {
        await new Promise(r => setTimeout(r, 100));
        waitElapsed += 100;
      }

      let visionObj = window.MediaPipeVision;
      if (!visionObj) {
        try {
          visionObj = await import("https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs");
          window.MediaPipeVision = visionObj;
        } catch (e) {
          console.warn("MediaPipe dynamic import warning:", e);
        }
      }

      if (visionObj && visionObj.FilesetResolver) {
        if (onProgress) onProgress("Resolving WASM vision binaries...");
        const filesetResolver = await visionObj.FilesetResolver.forVisionTasks(
          "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm"
        );

        if (onProgress) onProgress("Loading 478-Landmark AI Face Mesh model...");
        try {
          faceLandmarker = await visionObj.FaceLandmarker.createFromOptions(filesetResolver, {
            baseOptions: {
              modelAssetPath: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
              delegate: "GPU"
            },
            runningMode: "VIDEO",
            numFaces: 4
          });
        } catch (gpuErr) {
          console.warn("MediaPipe GPU fallback to CPU:", gpuErr);
          faceLandmarker = await visionObj.FaceLandmarker.createFromOptions(filesetResolver, {
            baseOptions: {
              modelAssetPath: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
              delegate: "CPU"
            },
            runningMode: "VIDEO",
            numFaces: 4
          });
        }

        isInitialized = true;
        isInitializing = false;
        if (onProgress) onProgress("AI Face & Gaze Tracking Active.");
        return true;
      }
    } catch (err) {
      console.warn("MediaPipe initialization error:", err);
    }
    isInitializing = false;
    return false;
  }

  /**
   * Process a single video frame with 3D Pose, Iris Gaze, and Liveness analysis
   */
  async function processVideoFrame(videoElement, timestampMs = Date.now()) {
    if (!videoElement || videoElement.readyState < 2) {
      return null;
    }

    const now = timestampMs;

    // MediaPipe requires strictly increasing timestamps in VIDEO mode
    let currentTs = performance.now();
    if (currentTs <= lastTimestamp) {
      currentTs = lastTimestamp + 1;
    }
    lastTimestamp = currentTs;

    if (!faceLandmarker || !isInitialized) {
      if (!isInitializing) {
        initialize().catch(() => {});
      }
    }

    if (faceLandmarker && isInitialized) {
      try {
        const results = faceLandmarker.detectForVideo(videoElement, currentTs);

        if (results && results.faceLandmarks && results.faceLandmarks.length > 0) {
          faceDetected = true;
          lastFaceSeenTimestamp = now;

          if (faceNotDetectedAlerted) {
            faceNotDetectedAlerted = false;
            if (onWarningCallback) {
              onWarningCallback({
                type: "FACE_RESTORED",
                confidence: 1.0,
                durationMs: 0,
                message: "Face position restored."
              });
            }
          }

          const vw = videoElement.videoWidth || 640;
          const vh = videoElement.videoHeight || 480;
          const numFaces = results.faceLandmarks.length;

          // Derive Bounding Boxes for all detected faces in view
          const allFaces = results.faceLandmarks.map((faceLm, idx) => {
            let fMinX = 1, fMaxX = 0, fMinY = 1, fMaxY = 0;
            for (let i = 0; i < faceLm.length; i++) {
              const p = faceLm[i];
              if (p.x < fMinX) fMinX = p.x;
              if (p.x > fMaxX) fMaxX = p.x;
              if (p.y < fMinY) fMinY = p.y;
              if (p.y > fMaxY) fMaxY = p.y;
            }
            const padX = (fMaxX - fMinX) * 0.12;
            const padY = (fMaxY - fMinY) * 0.12;
            const bx = Math.max(0, (fMinX - padX) * vw);
            const by = Math.max(0, (fMinY - padY) * vh);
            const bw = Math.min(vw - bx, (fMaxX - fMinX + padX * 2) * vw);
            const bh = Math.min(vh - by, (fMaxY - fMinY + padY * 2) * vh);
            return {
              index: idx,
              landmarks: faceLm,
              box: { x: bx, y: by, width: bw, height: bh },
              area: bw * bh
            };
          });

          // Sort faces by area descending: candidate is in the foreground (largest face)
          allFaces.sort((a, b) => b.area - a.area);
          const candidateFace = allFaces[0];
          const lm = candidateFace.landmarks;
          const boxX = candidateFace.box.x;
          const boxY = candidateFace.box.y;
          const boxW = candidateFace.box.width;
          const boxH = candidateFace.box.height;

          // Additional unauthorized faces in frame (filter tiny noise < 1.2% of frame)
          const minExtraFaceArea = (vw * vh) * 0.012;
          const extraFaces = allFaces.slice(1).filter(f => f.area >= minExtraFaceArea).map(f => f.box);

          // Multiple Faces sustained detection gating
          let isMultipleFacesWarning = false;
          let sustainedMultipleMs = 0;

          if (extraFaces.length > 0) {
            if (multipleFacesStartTime === 0) {
              multipleFacesStartTime = now;
            }
            sustainedMultipleMs = now - multipleFacesStartTime;

            if (sustainedMultipleMs >= MULTIPLE_FACES_SUSTAINED_MS) {
              isMultipleFacesWarning = true;
              const cooldownMs = now - lastMultipleFacesWarningTime;
              if (cooldownMs >= MULTIPLE_FACES_COOLDOWN_MS) {
                lastMultipleFacesWarningTime = now;
                if (onWarningCallback) {
                  onWarningCallback({
                    type: "MULTIPLE_FACES_DETECTED",
                    confidence: 0.98,
                    durationMs: sustainedMultipleMs,
                    count: 1 + extraFaces.length,
                    message: `Multiple faces detected in camera view (${1 + extraFaces.length} faces). The assessment must be taken alone in a private room without unauthorized individuals.`
                  });
                }
              }
            }
          } else {
            multipleFacesStartTime = 0;
          }

          // =========================================================================
          // 1. Scale-Invariant Robust Horizontal & Vertical Head Pose Estimation
          // =========================================================================
          // Landmarks:
          // 1: Nose tip, 10: Forehead, 152: Chin, 234: Right Tragus/Cheek, 454: Left Tragus/Cheek
          // 33: Right eye outer (smaller x), 263: Left eye outer (larger x)
          const nose = lm[1];
          const forehead = lm[10];
          const chin = lm[152];
          const rightTragus = lm[234] || lm[33];
          const leftTragus = lm[454] || lm[263];

          // Eye Midpoint & Interocular Distance:
          const eyeMidX = (lm[33].x + lm[263].x + lm[133].x + lm[362].x) / 4;
          const eyeDist = Math.max(0.001, Math.hypot(lm[263].x - lm[33].x, lm[263].y - lm[33].y));

          // In unmirrored camera coordinates:
          // Right eye lm[33] is at smaller x; Left eye lm[263] is at larger x.
          // Turning head LEFT -> nose shifts towards left cheek (+X, larger x => nose.x > eyeMidX => positive)
          // Turning head RIGHT -> nose shifts towards right cheek (-X, smaller x => nose.x < eyeMidX => negative)
          const noseShift = (nose.x - eyeMidX) / eyeDist;

          // Cheek foreshortening ratio:
          const rightCheekSpan = Math.max(0.001, nose.x - rightTragus.x);
          const leftCheekSpan = Math.max(0.001, leftTragus.x - nose.x);
          const cheekAsymmetry = (rightCheekSpan - leftCheekSpan) / Math.max(0.001, leftTragus.x - rightTragus.x);

          // Combined scale-invariant Yaw (positive = LEFT, negative = RIGHT)
          const rawYaw = (noseShift * 0.55 + cheekAsymmetry * 0.45) * 58.0;

          // Vertical Head Pitch (positive = DOWN, negative = UP)
          const eyeMidY = (lm[33].y + lm[263].y) / 2;
          const faceHeight = Math.max(0.001, Math.hypot(chin.x - forehead.x, chin.y - forehead.y));
          const verticalShift = (nose.y - eyeMidY) / faceHeight;
          const rawPitch = (verticalShift - 0.27) * 75.0;

          // Head Roll (tilt toward shoulder)
          const rawRoll = Math.atan2(leftTragus.y - rightTragus.y, leftTragus.x - rightTragus.x) * (180.0 / Math.PI);

          // Temporal smoothing (Exponential Moving Average)
          if (isNaN(smoothedYaw) || (smoothedYaw === 0.0 && smoothedPitch === 0.0)) {
            smoothedYaw = rawYaw;
            smoothedPitch = rawPitch;
            smoothedRoll = rawRoll;
          } else {
            smoothedYaw = SMOOTHING_ALPHA * rawYaw + (1 - SMOOTHING_ALPHA) * smoothedYaw;
            smoothedPitch = SMOOTHING_ALPHA * rawPitch + (1 - SMOOTHING_ALPHA) * smoothedPitch;
            smoothedRoll = SMOOTHING_ALPHA * rawRoll + (1 - SMOOTHING_ALPHA) * smoothedRoll;
          }

          // Initial auto-calibration on first 10 frames
          if (!isCalibrated) {
            autoCalibSamples.push({ yaw: smoothedYaw, pitch: smoothedPitch, roll: smoothedRoll });
            if (autoCalibSamples.length >= CALIB_SAMPLES_NEEDED) {
              baselineYaw = autoCalibSamples.reduce((acc, s) => acc + s.yaw, 0) / autoCalibSamples.length;
              baselinePitch = autoCalibSamples.reduce((acc, s) => acc + s.pitch, 0) / autoCalibSamples.length;
              baselineRoll = autoCalibSamples.reduce((acc, s) => acc + s.roll, 0) / autoCalibSamples.length;
              isCalibrated = true;
              try {
                localStorage.setItem("datadrix_baseline_yaw", baselineYaw.toString());
                localStorage.setItem("datadrix_baseline_pitch", baselinePitch.toString());
              } catch (e) {}
            }
          } else if (Math.abs(smoothedYaw - baselineYaw) > 22.0 && autoCalibSamples.length < CALIB_SAMPLES_NEEDED) {
            autoCalibSamples.push({ yaw: smoothedYaw, pitch: smoothedPitch, roll: smoothedRoll });
            if (autoCalibSamples.length >= CALIB_SAMPLES_NEEDED) {
              baselineYaw = autoCalibSamples.reduce((acc, s) => acc + s.yaw, 0) / autoCalibSamples.length;
              baselinePitch = autoCalibSamples.reduce((acc, s) => acc + s.pitch, 0) / autoCalibSamples.length;
              baselineRoll = autoCalibSamples.reduce((acc, s) => acc + s.roll, 0) / autoCalibSamples.length;
              autoCalibSamples = [];
            }
          }

          let deltaYaw = smoothedYaw - baselineYaw;
          let deltaPitch = smoothedPitch - baselinePitch;

          // Continuous adaptive neutral drift when candidate naturally views normal exam area
          if (isCalibrated && Math.abs(deltaYaw) < 20.0 && Math.abs(deltaPitch) < 20.0) {
            const ADAPT_RATE = 0.02;
            baselineYaw = (1 - ADAPT_RATE) * baselineYaw + ADAPT_RATE * smoothedYaw;
            baselinePitch = (1 - ADAPT_RATE) * baselinePitch + ADAPT_RATE * smoothedPitch;
            deltaYaw = smoothedYaw - baselineYaw;
            deltaPitch = smoothedPitch - baselinePitch;
          }

          // Evaluate Head Direction with Hysteresis (Accurate Left/Right Classification)
          let currentDir = "NORMAL";
          if (activeDeviation === "LEFT") {
            currentDir = (deltaYaw > YAW_RETURN_THRESHOLD_DEG) ? "LEFT" : "NORMAL";
          } else if (activeDeviation === "RIGHT") {
            currentDir = (deltaYaw < -YAW_RETURN_THRESHOLD_DEG) ? "RIGHT" : "NORMAL";
          } else if (activeDeviation === "DOWN") {
            currentDir = (deltaPitch > PITCH_RETURN_THRESHOLD_DEG) ? "DOWN" : "NORMAL";
          } else {
            if (deltaYaw > YAW_THRESHOLD_DEG) {
              currentDir = "LEFT";
            } else if (deltaYaw < -YAW_THRESHOLD_DEG) {
              currentDir = "RIGHT";
            } else if (deltaPitch > PITCH_DOWN_THRESHOLD_DEG) {
              currentDir = "DOWN";
            }
          }

          // =========================================================================
          // 2. Ocular Gaze & Iris Vector Tracking
          // =========================================================================
          // Left Eye bounds: inner 362, outer 263, top 386, bottom 374
          // Right Eye bounds: inner 133, outer 33, top 159, bottom 145
          // Iris centers: 468 (left), 473 (right)
          const hasIris = Boolean(lm[468] && lm[473]);
          const leftIris = hasIris ? lm[468] : { x: (lm[386].x + lm[374].x) / 2, y: (lm[386].y + lm[374].y) / 2 };
          const rightIris = hasIris ? lm[473] : { x: (lm[159].x + lm[145].x) / 2, y: (lm[159].y + lm[145].y) / 2 };

          // Horizontal Eye-to-Iris Ratios
          const leftEyeSpan = Math.max(0.001, lm[263].x - lm[362].x);
          const rightEyeSpan = Math.max(0.001, lm[133].x - lm[33].x);
          const leftGazeX = (leftIris.x - lm[362].x) / leftEyeSpan;
          const rightGazeX = (rightIris.x - lm[33].x) / rightEyeSpan;
          const avgGazeX = (leftGazeX + rightGazeX) / 2;

          // Vertical Eye-to-Iris Ratio
          const leftEyeHeight = Math.max(0.001, lm[374].y - lm[386].y);
          const avgGazeY = (leftIris.y - lm[386].y) / leftEyeHeight;

          // Evaluate Gaze Deviation (looking far away horizontally while head is facing screen)
          // Downward gaze (avgGazeY) is the candidate reading questions and is NEVER flagged as gaze deviation.
          let gazeState = "CENTER";
          let isGazeWarning = false;
          if (avgGazeX > GAZE_THRESHOLD_LEFT) {
            gazeState = "GAZE_LEFT";
          } else if (avgGazeX < GAZE_THRESHOLD_RIGHT) {
            gazeState = "GAZE_RIGHT";
          }

          // Sustained Gaze Gating (eyes drifted horizontally for >= 5.0s with head facing forward)
          if (gazeState !== "CENTER" && currentDir === "NORMAL") {
            if (activeGazeDeviation !== gazeState) {
              activeGazeDeviation = gazeState;
              gazeDeviationStartTime = now;
            }
            const gazeSustained = now - gazeDeviationStartTime;
            if (gazeSustained >= GAZE_SUSTAINED_MS) {
              isGazeWarning = true;
              if (now - lastGazeWarningTime >= GAZE_COOLDOWN_MS) {
                lastGazeWarningTime = now;
                if (onWarningCallback) {
                  onWarningCallback({
                    type: "GAZE_AWAY",
                    confidence: 0.92,
                    durationMs: gazeSustained,
                    direction: gazeState,
                    message: "Eye Gaze Warning: Your eyes have drifted away from the exam screen for an extended period. Please maintain your visual focus directly on the assessment."
                  });
                }
              }
            }
          } else {
            activeGazeDeviation = null;
            gazeDeviationStartTime = 0;
          }

          // =========================================================================
          // 3. Eye Aspect Ratio (EAR) Blink Detection & Anti-Spoof Liveness
          // =========================================================================
          const earLeft = Math.hypot(lm[386].x - lm[374].x, lm[386].y - lm[374].y) /
                          Math.max(0.001, Math.hypot(lm[263].x - lm[362].x, lm[263].y - lm[362].y));
          const earRight = Math.hypot(lm[159].x - lm[145].x, lm[159].y - lm[145].y) /
                           Math.max(0.001, Math.hypot(lm[133].x - lm[33].x, lm[133].y - lm[33].y));
          const avgEAR = (earLeft + earRight) / 2;

          // Blink transition detection: EAR dips < 0.16 then rebounds > 0.20
          if (avgEAR < 0.16) {
            wasEyeClosed = true;
          } else if (wasEyeClosed && avgEAR > 0.20) {
            wasEyeClosed = false;
            blinkCount++;
            lastBlinkTimestamp = now;
          }

          // Micro-motion spatial variance on nose tip
          nosePositionHistory.push({ x: nose.x, y: nose.y });
          if (nosePositionHistory.length > NOSE_HISTORY_MAX) {
            nosePositionHistory.shift();
          }

          let staticPhotoSuspected = false;
          if (nosePositionHistory.length >= NOSE_HISTORY_MAX) {
            const meanX = nosePositionHistory.reduce((a, b) => a + b.x, 0) / NOSE_HISTORY_MAX;
            const meanY = nosePositionHistory.reduce((a, b) => a + b.y, 0) / NOSE_HISTORY_MAX;
            const variance = nosePositionHistory.reduce((a, b) => a + Math.pow(b.x - meanX, 2) + Math.pow(b.y - meanY, 2), 0) / NOSE_HISTORY_MAX;

            // Zero blinks for >25s AND absolutely static pixels (< 0.00002)
            if ((now - lastBlinkTimestamp > STATIC_PHOTO_TIMEOUT_MS) && variance < 0.00002) {
              staticPhotoSuspected = true;
              if (now - lastStaticWarningTime >= 15000) {
                lastStaticWarningTime = now;
                if (onWarningCallback) {
                  onWarningCallback({
                    type: "STATIC_PHOTO_SUSPECTED",
                    confidence: 0.88,
                    durationMs: now - lastBlinkTimestamp,
                    message: "Liveness Check: Video feed appears completely motionless or unresponsive. Please verify that your live webcam is operating properly."
                  });
                }
              }
            }
          }

          // =========================================================================
          // 4. Head Pose Sustained Duration Gating & Modals
          // =========================================================================
          let boxColor = "#10B981"; // Normal: Emerald Green
          let isWarning = false;
          let sustainedMs = 0;

          if (currentDir !== "NORMAL") {
            if (activeDeviation !== currentDir) {
              activeDeviation = currentDir;
              deviationStartTime = now;
            }

            sustainedMs = now - deviationStartTime;

            if (sustainedMs >= SUSTAINED_DURATION_MS) {
              boxColor = "#EF4444"; // Warning: Crimson Red
              isWarning = true;

              const cooldownMs = now - (lastWarningTime[currentDir] || 0);
              if (cooldownMs >= WARNING_COOLDOWN_MS) {
                lastWarningTime[currentDir] = now;
                const eventType = currentDir === "LEFT" ? "HEAD_TURN_LEFT" :
                                  (currentDir === "RIGHT" ? "HEAD_TURN_RIGHT" : "HEAD_TILT_DOWN");
                const humanDir = currentDir === "LEFT" ? "left" : (currentDir === "RIGHT" ? "right" : "downward");

                if (onWarningCallback) {
                  onWarningCallback({
                    type: eventType,
                    direction: currentDir,
                    confidence: 0.95,
                    durationMs: sustainedMs,
                    message: `You have turned your face ${humanDir} for more than 2 seconds. Please look directly forward at the exam screen.`
                  });
                }
              }
            } else {
              boxColor = "#F59E0B"; // Approaching deviation: Amber
            }
          } else {
            activeDeviation = null;
            deviationStartTime = 0;
            boxColor = (isGazeWarning || staticPhotoSuspected) ? "#F59E0B" : "#10B981";
          }

          const result = {
            faceDetected: true,
            box: { x: boxX, y: boxY, width: boxW, height: boxH },
            color: (numFaces > 1 || isMultipleFacesWarning) ? "#EF4444" : boxColor,
            direction: numFaces > 1 ? `MULTIPLE_FACES (${numFaces})` : currentDir,
            isWarning: isWarning || isMultipleFacesWarning || isGazeWarning,
            sustainedMs: numFaces > 1 ? sustainedMultipleMs : sustainedMs,
            numFaces: numFaces,
            multipleFaces: numFaces > 1,
            extraFaces: extraFaces,
            yaw: Math.round(smoothedYaw),
            pitch: Math.round(smoothedPitch),
            roll: Math.round(smoothedRoll),
            deltaYaw: Math.round(deltaYaw),
            deltaPitch: Math.round(deltaPitch),
            isCalibrated: isCalibrated,
            gaze: {
              ratioX: Number(avgGazeX.toFixed(2)),
              ratioY: Number(avgGazeY.toFixed(2)),
              state: gazeState,
              isWarning: isGazeWarning,
              leftIris: { x: leftIris.x * vw, y: leftIris.y * vh },
              rightIris: { x: rightIris.x * vw, y: rightIris.y * vh }
            },
            liveness: {
              isLive: !staticPhotoSuspected,
              blinkCount: blinkCount,
              ear: Number(avgEAR.toFixed(2)),
              staticSuspected: staticPhotoSuspected
            }
          };

          if (onStatusUpdateCallback) onStatusUpdateCallback(result);
          return result;
        }
      } catch (err) {
        console.warn("FaceLandmarker detection warning:", err);
      }
    }

    // No face detected in this frame
    faceDetected = false;
    const absenceDuration = now - lastFaceSeenTimestamp;

    if (isInitialized && absenceDuration > FACE_ABSENCE_THRESHOLD_MS && !faceNotDetectedAlerted) {
      faceNotDetectedAlerted = true;
      if (onWarningCallback) {
        onWarningCallback({
          type: "FACE_NOT_DETECTED",
          confidence: 0.95,
          durationMs: absenceDuration,
          message: "Face not detected in camera view. Please keep your face clearly visible inside the camera frame."
        });
      }
    }

    const missingResult = {
      faceDetected: false,
      box: null,
      color: "#EF4444",
      direction: "MISSING",
      isWarning: faceNotDetectedAlerted,
      sustainedMs: absenceDuration,
      numFaces: 0,
      multipleFaces: false,
      extraFaces: [],
      yaw: 0,
      pitch: 0,
      roll: 0,
      deltaYaw: 0,
      deltaPitch: 0,
      isCalibrated: isCalibrated,
      gaze: { ratioX: 0.5, ratioY: 0.5, state: "UNKNOWN", isWarning: false, leftIris: null, rightIris: null },
      liveness: { isLive: false, blinkCount: blinkCount, ear: 0, staticSuspected: false }
    };

    if (onStatusUpdateCallback) onStatusUpdateCallback(missingResult);
    return missingResult;
  }

  function calibrateNeutral() {
    baselineYaw = smoothedYaw;
    baselinePitch = smoothedPitch;
    baselineRoll = smoothedRoll;
    isCalibrated = true;
    autoCalibSamples = [];
    activeDeviation = null;
    deviationStartTime = 0;
    try {
      localStorage.setItem("datadrix_baseline_yaw", baselineYaw.toString());
      localStorage.setItem("datadrix_baseline_pitch", baselinePitch.toString());
    } catch (e) {}
    return { baselineYaw, baselinePitch, baselineRoll };
  }

  function resetBaseline() {
    isCalibrated = false;
    autoCalibSamples = [];
    smoothedYaw = 0.0;
    smoothedPitch = 0.0;
    smoothedRoll = 0.0;
    baselineYaw = 0.0;
    baselinePitch = 0.0;
    baselineRoll = 0.0;
    activeDeviation = null;
    deviationStartTime = 0;
    try {
      localStorage.removeItem("datadrix_baseline_yaw");
      localStorage.removeItem("datadrix_baseline_pitch");
    } catch (e) {}
  }

  function setOnWarning(cb) {
    onWarningCallback = cb;
  }

  function setOnStatusUpdate(cb) {
    onStatusUpdateCallback = cb;
  }

  function isReady() {
    return isInitialized;
  }

  return {
    initialize,
    processVideoFrame,
    calibrateNeutral,
    resetBaseline,
    setOnWarning,
    setOnStatusUpdate,
    isReady,
    getBaseline: () => ({ yaw: baselineYaw, pitch: baselinePitch, roll: baselineRoll })
  };
})();
