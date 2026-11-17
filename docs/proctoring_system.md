# Real-Time AI Proctoring Architecture & System Guide

## 1. Overview & Privacy Principles
The Datadrix Assessment System incorporates real-time, browser-based AI vision proctoring without compromising privacy, responsiveness, or test integrity.

### Core Architecture Principles:
- **Zero Video Transmission**: Candidate webcam streams are processed purely on-device inside the candidate's browser using WebAssembly and WebGL acceleration. No raw video or frame snapshots are streamed to or stored on the backend server.
- **Structured Telemetry Only**: Only low-frequency, high-confidence detection events (`HEAD_TURN_LEFT`, `HEAD_TURN_RIGHT`, `HEAD_TILT_DOWN`, `FACE_NOT_DETECTED`, `FACE_RESTORED`, `MOBILE_PHONE_DETECTED`, `CAMERA_DISCONNECTED`, `PHONE_DETECTION_UNAVAILABLE`) are transmitted via the Fetch API to `/api/assessment/<attempt_id>/proctoring-event`.
- **Dual-Counter Integrity Isolation**:
  - **Navigation Violations (`violation_count`)**: Governed by the strict 2-strike policy for window blurring, full-screen departure, and tab switching. A 2nd violation terminates the assessment.
  - **Vision Warnings (`vision_warning_count`)**: Governed by an educational and advisory policy. Vision anomalies display non-blocking warning banners or modal advisories and increment `vision_warning_count` for reviewer audit without automatically aborting the exam.

---

## 2. Technology Stack
- **Backend**: Python 3.14, Flask, Flask-SQLAlchemy (SQLite database `assessment.db`).
- **Frontend**: Bootstrap 5, Vanilla JavaScript (ES6+ modular components).
- **Vision Engines**:
  - **MediaPipe Face Landmarker** (`@mediapipe/tasks-vision` / FaceMesh): 468-point 3D facial landmark mesh for head-pose estimation (yaw & pitch).
  - **TensorFlow.js** (`@tensorflow/tfjs`): Client-side inference engine loading custom-trained mobile phone detection models (`/static/models/phone_detector/model.json`).

---

## 3. Head-Pose Estimation Methodology

### Scale-Invariant Landmark Triangulation
Rather than relying on perspective-sensitive pixel distances, head pose angles are estimated using normalized ratio deviations between key 3D landmarks:
- **Key Points**:
  - Nose Tip: Landmark 1
  - Left Eye Outer Corner: Landmark 33
  - Right Eye Outer Corner: Landmark 263
  - Forehead: Landmark 10
  - Chin: Landmark 152

### Yaw (Left / Right Rotation):
$$\text{dist}_{L} = \| \mathbf{p}_{\text{nose}} - \mathbf{p}_{\text{left\_eye}} \|$$
$$\text{dist}_{R} = \| \mathbf{p}_{\text{nose}} - \mathbf{p}_{\text{right\_eye}} \|$$
$$\text{ratio} = \frac{\text{dist}_{L} - \text{dist}_{R}}{\text{dist}_{L} + \text{dist}_{R}}$$
$$\text{yaw} = \text{ratio} \times 90^\circ$$

### Pitch (Up / Down Tilt):
$$\text{dist}_{\text{upper}} = \| \mathbf{p}_{\text{forehead}} - \mathbf{p}_{\text{nose}} \|$$
$$\text{dist}_{\text{lower}} = \| \mathbf{p}_{\text{nose}} - \mathbf{p}_{\text{chin}} \|$$
$$\text{pitch} = \left(\frac{\text{dist}_{\text{lower}}}{\text{dist}_{\text{upper}}} - 1.0\right) \times 50^\circ$$

### Temporal Smoothing & Filtering
- **Exponential Moving Average (EMA)** with factor $\alpha = 0.35$:
  $$\theta_t = \alpha \cdot \theta_{\text{raw}} + (1 - \alpha) \cdot \theta_{t-1}$$
- **Neutral Pose Calibration**: Candidates calibrate on `/device-check`, setting baseline offsets $\text{yaw}_0$ and $\text{pitch}_0$. Subsequent checks measure deviation relative to baseline.
- **Sustained Deviation Window**: Warnings trigger only after sustained deviation exceeding thresholds ($\pm 28^\circ$ yaw, $-18^\circ$ pitch) for $\ge 2.5\text{s}$.
- **Warning Cooldown**: 8.0-second cooldown per posture violation type to prevent alert fatigue.

---

## 4. Mobile Phone Detection Engine
- **Inference Cycle**: Sampled every 300ms (~3.3 FPS) with an asynchronous inference lock (`isInferring`) to prevent main thread blocking or frame backlog.
- **Confidence Threshold**: Configurable at $\ge 0.70$.
- **Temporal Persistence**: Requires detection across $\ge 3$ consecutive frames before raising an event.
- **Absence Reset**: State resets after phone has been absent for 5.0 seconds.
- **Warning Cooldown**: 15.0 seconds between sustained phone warning modals.
- **Graceful Fallback**: If the custom model weights are absent or loading fails, `PHONE_DETECTION_UNAVAILABLE` is dispatched once and the UI informs the candidate and proctor transparently without throwing unhandled exceptions.

---

## 5. Top Bar Real-Time Camera HUD

During the test on `/assessment/<attempt_id>`, the frozen top bar provides real-time status:
1. **Cam Indicator**: Green pulsing dot when video feed is actively streaming.
2. **Face Status**: Green badge (`Face OK`) or Red warning (`No Face`).
3. **Pose Status**: Green badge (`Head OK`) or Amber warning (`Turned L/R`, `Looking Down`).
4. **Phone Guard**: Cyan badge (`Phone Guard Active`) or Red warning (`Phone Visible`).
5. **Vision Warnings**: Live count (`Vision Alerts: N`) reflecting `vision_warning_count`.

---

## 6. API Reference

### `POST /api/assessment/<attempt_id>/proctoring-event`

**Headers**:
- `Content-Type: application/json`
- `X-CSRFToken: <token>`

**Payload**:
```json
{
  "event_type": "MOBILE_PHONE_DETECTED",
  "confidence": 0.88,
  "duration_ms": 3200,
  "client_event_id": "phone-1731705600123-abc",
  "metadata": {
    "fps": 3.4,
    "model_version": "1.0.0"
  }
}
```

**Response**:
```json
{
  "success": true,
  "event_type": "MOBILE_PHONE_DETECTED",
  "vision_warning_count": 1,
  "timestamp": "2026-11-15T17:30:00Z"
}
```
