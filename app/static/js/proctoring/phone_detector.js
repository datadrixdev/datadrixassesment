/**
 * Multi-Class AI Threat & Object Detector Module (TensorFlow.js COCO-SSD)
 *
 * Capabilities:
 *  1. Mobile Phone & Smart Device Detection ('cell phone', 'phone', 'remote')
 *  2. Prohibited Academic Material Detection ('book', notes, cheat sheets)
 *  3. Secondary Screen / Laptop Detection ('tv', 'laptop' outside typing zone)
 *  4. Secondary Person Body Isolation with IoU (Intersection over Union) verification
 *  5. Temporal smoothing, multi-frame debounce, and cooldown deduplication
 */
const PhoneDetectorModule = (() => {
  let cocoModel = null;
  let isModelLoaded = false;
  let isModelAvailable = false;
  let isInitializing = false;

  // Detection thresholds
  const CONFIDENCE_THRESHOLD_PHONE = 0.68;
  const CONFIDENCE_THRESHOLD_OBJECT = 0.72;
  const CONFIDENCE_THRESHOLD_PERSON = 0.65;
  const REQUIRED_CONSECUTIVE_FRAMES = 6;
  const WARNING_COOLDOWN_MS = 18000;
  const MULTIPLE_PERSONS_SUSTAINED_MS = 2500;

  // Phone tracking state
  let consecutivePhoneCount = 0;
  let firstPhoneTimestamp = 0;
  let lastPhoneWarningTimestamp = 0;

  // Prohibited objects (books, external screens) tracking state
  let consecutiveObjectCount = 0;
  let firstObjectTimestamp = 0;
  let lastObjectWarningTimestamp = 0;
  let currentDetectedObjectClass = null;

  // Multi-person tracking state
  let multiplePersonFirstTimestamp = 0;
  let lastMultiplePersonWarningTimestamp = 0;

  // Callbacks
  let onWarningCallback = null;
  let onStatusUpdateCallback = null;

  async function initialize(onProgress = null) {
    if (isModelLoaded) return true;
    if (isInitializing) return false;
    isInitializing = true;

    try {
      if (onProgress) onProgress("Initializing TensorFlow runtime...");

      if (typeof window.tf === "undefined") {
        await loadScript("https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.20.0/dist/tf.min.js");
      }
      await window.tf.ready();

      if (typeof window.cocoSsd === "undefined") {
        if (onProgress) onProgress("Loading COCO-SSD detection engine...");
        await loadScript("https://cdn.jsdelivr.net/npm/@tensorflow-models/coco-ssd@2.2.3/dist/coco-ssd.min.js");
      }

      if (onProgress) onProgress("Loading AI Threat & Object detection model...");
      cocoModel = await window.cocoSsd.load({ base: "lite_mobilenet_v2" });

      isModelLoaded = true;
      isModelAvailable = true;
      isInitializing = false;
      if (onProgress) onProgress("AI Threat & Object Detector Active.");
      return true;
    } catch (err) {
      console.warn("AI Object Detector initialization error:", err);
      isModelLoaded = false;
      isModelAvailable = false;
      isInitializing = false;
      if (onProgress) onProgress("AI Threat Detector unavailable.");
      return false;
    }
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  /**
   * Helper: Calculate Intersection over Union (IoU) between two bounding boxes [x, y, w, h]
   */
  function computeIoU(b1, b2) {
    const xA = Math.max(b1.x, b2.x);
    const yA = Math.max(b1.y, b2.y);
    const xB = Math.min(b1.x + b1.width, b2.x + b2.width);
    const yB = Math.min(b1.y + b1.height, b2.y + b2.height);

    const interArea = Math.max(0, xB - xA) * Math.max(0, yB - yA);
    const b1Area = b1.width * b1.height;
    const b2Area = b2.width * b2.height;
    const unionArea = b1Area + b2Area - interArea;

    return unionArea > 0 ? interArea / unionArea : 0;
  }

  /**
   * Samples a webcam frame and runs inference across threats (phones, materials, extra persons)
   */
  async function processVideoFrame(videoElement, timestampMs = Date.now()) {
    if (!videoElement || videoElement.readyState < 2) {
      return null;
    }

    if (!isModelAvailable || !cocoModel) {
      if (!isInitializing) {
        initialize().catch(() => {});
      }
      return null;
    }

    const now = timestampMs;
    const vh = videoElement.videoHeight || 480;

    try {
      const predictions = await cocoModel.detect(videoElement);

      // =========================================================================
      // 1. Mobile Phone Detection
      // =========================================================================
      const phoneHits = predictions.filter(p =>
        (p.class === "cell phone" || p.class === "mobile phone" || p.class === "phone" || p.class === "remote") &&
        p.score >= CONFIDENCE_THRESHOLD_PHONE
      );

      let phoneDetected = false;
      let phoneBox = null;
      let bestPhoneScore = 0.0;

      if (phoneHits.length > 0) {
        consecutivePhoneCount++;
        phoneDetected = true;
        phoneHits.sort((a, b) => b.score - a.score);
        const topHit = phoneHits[0];
        bestPhoneScore = topHit.score;

        phoneBox = {
          x: Math.round(topHit.bbox[0]),
          y: Math.round(topHit.bbox[1]),
          width: Math.round(topHit.bbox[2]),
          height: Math.round(topHit.bbox[3]),
          label: topHit.class
        };

        if (consecutivePhoneCount >= REQUIRED_CONSECUTIVE_FRAMES) {
          if (firstPhoneTimestamp === 0) firstPhoneTimestamp = now;

          if (now - lastPhoneWarningTimestamp >= WARNING_COOLDOWN_MS) {
            lastPhoneWarningTimestamp = now;
            if (onWarningCallback) {
              onWarningCallback({
                type: "MOBILE_PHONE_DETECTED",
                confidence: Math.min(1.0, Number(bestPhoneScore.toFixed(2))),
                durationMs: now - firstPhoneTimestamp,
                box: phoneBox,
                message: "Mobile Phone Detected: A mobile phone or electronic device appears to be visible in your camera view. Please remove it from the testing environment."
              });
            }
          }
        }
      } else {
        consecutivePhoneCount = 0;
        firstPhoneTimestamp = 0;
      }

      // =========================================================================
      // 2. Prohibited Academic Items / External Displays Detection
      //    (Books, Physical Notes, Secondary Monitors/Laptops outside typing zone)
      // =========================================================================
      const objectHits = predictions.filter(p => {
        if (p.score < CONFIDENCE_THRESHOLD_OBJECT) return false;

        // Books / physical notebooks / papers
        if (p.class === "book") return true;

        // Television / external monitor screens
        if (p.class === "tv") return true;

        // Secondary laptop: Only flag if situated in upper frame (not candidate's own keyboard area)
        if (p.class === "laptop") {
          const topY = p.bbox[1];
          // User's own typing laptop sits in lower portion of frame (topY >= 35% of height)
          return topY < (vh * 0.35);
        }

        return false;
      });

      let objectDetected = false;
      let objectBox = null;
      let objectLabel = null;
      let bestObjectScore = 0.0;

      if (objectHits.length > 0 && !phoneDetected) {
        consecutiveObjectCount++;
        objectDetected = true;
        objectHits.sort((a, b) => b.score - a.score);
        const topObj = objectHits[0];
        bestObjectScore = topObj.score;
        currentDetectedObjectClass = topObj.class;

        objectLabel = topObj.class === "book" ? "Unauthorized Book / Notes" :
                     (topObj.class === "tv" ? "Secondary Monitor / Screen" : "Secondary Laptop");

        objectBox = {
          x: Math.round(topObj.bbox[0]),
          y: Math.round(topObj.bbox[1]),
          width: Math.round(topObj.bbox[2]),
          height: Math.round(topObj.bbox[3]),
          label: objectLabel
        };

        if (consecutiveObjectCount >= REQUIRED_CONSECUTIVE_FRAMES) {
          if (firstObjectTimestamp === 0) firstObjectTimestamp = now;

          if (now - lastObjectWarningTimestamp >= WARNING_COOLDOWN_MS) {
            lastObjectWarningTimestamp = now;
            if (onWarningCallback) {
              onWarningCallback({
                type: "UNAUTHORIZED_OBJECT_DETECTED",
                confidence: Math.min(1.0, Number(bestObjectScore.toFixed(2))),
                durationMs: now - firstObjectTimestamp,
                box: objectBox,
                message: `Unauthorized Item Detected: An unauthorized item (${objectLabel.toLowerCase()}) was detected in your camera view. Please remove all non-permitted materials.`
              });
            }
          }
        }
      } else {
        consecutiveObjectCount = 0;
        firstObjectTimestamp = 0;
        currentDetectedObjectClass = null;
      }

      // =========================================================================
      // 3. Person & Secondary Individual Detection (IoU Verified)
      // =========================================================================
      const personHits = predictions.filter(p => p.class === "person" && p.score >= CONFIDENCE_THRESHOLD_PERSON);

      let personBox = null;
      let extraPersons = [];
      let multiplePersonsDetected = false;

      if (personHits.length > 0) {
        // Sort by area descending: candidate is foreground (largest person box)
        personHits.sort((a, b) => (b.bbox[2] * b.bbox[3]) - (a.bbox[2] * a.bbox[3]));
        const candidatePerson = personHits[0];
        personBox = {
          x: Math.round(candidatePerson.bbox[0]),
          y: Math.round(candidatePerson.bbox[1]),
          width: Math.round(candidatePerson.bbox[2]),
          height: Math.round(candidatePerson.bbox[3])
        };

        // Examine remaining persons with IoU to eliminate overlaps/clothing artifacts
        if (personHits.length > 1) {
          const verifiedExtraPersons = [];

          for (let i = 1; i < personHits.length; i++) {
            const ep = personHits[i];
            const epBox = {
              x: Math.round(ep.bbox[0]),
              y: Math.round(ep.bbox[1]),
              width: Math.round(ep.bbox[2]),
              height: Math.round(ep.bbox[3])
            };

            const iou = computeIoU(personBox, epBox);
            // If IoU < 0.45, it is a distinctly separate human body in view!
            if (iou < 0.45) {
              verifiedExtraPersons.push({
                ...epBox,
                score: ep.score,
                iou: iou
              });
            }
          }

          if (verifiedExtraPersons.length > 0) {
            multiplePersonsDetected = true;
            extraPersons = verifiedExtraPersons;

            if (multiplePersonFirstTimestamp === 0) {
              multiplePersonFirstTimestamp = now;
            }
            const sustainedPersonMs = now - multiplePersonFirstTimestamp;

            if (sustainedPersonMs >= MULTIPLE_PERSONS_SUSTAINED_MS) {
              const cooldownMs = now - lastMultiplePersonWarningTimestamp;
              if (cooldownMs >= WARNING_COOLDOWN_MS) {
                lastMultiplePersonWarningTimestamp = now;

                if (onWarningCallback) {
                  onWarningCallback({
                    type: "MULTIPLE_PEOPLE_DETECTED",
                    confidence: Math.min(1.0, Number(verifiedExtraPersons[0].score.toFixed(2))),
                    durationMs: sustainedPersonMs,
                    count: 1 + verifiedExtraPersons.length,
                    message: `Another person was detected in your camera view (${1 + verifiedExtraPersons.length} people detected). The assessment must be taken alone in a private room without unauthorized assistance.`
                  });
                }
              }
            }
          } else {
            multiplePersonFirstTimestamp = 0;
          }
        } else {
          multiplePersonFirstTimestamp = 0;
        }
      } else {
        multiplePersonFirstTimestamp = 0;
      }

      const statusObj = {
        isAvailable: true,
        phoneDetected: phoneDetected,
        phoneConfidence: bestPhoneScore,
        phoneBox: phoneBox,
        objectDetected: objectDetected,
        objectBox: objectBox,
        objectLabel: objectLabel,
        objectConfidence: bestObjectScore,
        personBox: personBox,
        multiplePersonsDetected: multiplePersonsDetected,
        extraPersons: extraPersons,
        personCount: 1 + extraPersons.length
      };

      if (onStatusUpdateCallback) {
        onStatusUpdateCallback(statusObj);
      }

      return statusObj;

    } catch (e) {
      console.warn("Threat detector inference warning:", e);
      return null;
    }
  }

  function setOnWarning(cb) {
    onWarningCallback = cb;
  }

  function setOnStatusUpdate(cb) {
    onStatusUpdateCallback = cb;
  }

  function isReady() {
    return isModelAvailable && isModelLoaded;
  }

  return {
    initialize,
    processVideoFrame,
    setOnWarning,
    setOnStatusUpdate,
    isReady
  };
})();
