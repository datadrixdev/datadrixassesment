# Custom Mobile Phone Detection Model Setup Guide

This guide describes how to configure, train, and deploy custom TensorFlow.js models specifically trained to detect mobile phones in candidate webcam streams for the Datadrix Online Assessment Platform.

---

## 1. Why a Custom Dedicated Model?

Standard general-purpose object detection models (such as basic COCO-SSD) are trained on 80 broad common objects and do not provide dedicated fine-grained feature detection for handheld smartphones, especially in low-light, edge-of-frame, or partially occluded webcam conditions.

The Datadrix AI Proctoring system requires a **dedicated mobile phone detector** that:
- Runs in-browser using WebGL / WASM via TensorFlow.js.
- Classifies objects with label `mobile_phone`.
- Operates at **3–5 frames per second** with inference times below 80ms on standard client laptops.
- Enforces a default confidence threshold of **0.70**.
- Uses multi-frame temporal persistence (requiring 3+ consecutive detection frames) to suppress false positives.

---

## 2. Model Directory Structure

The platform automatically searches for custom model assets at:
```
app/static/models/phone_detector/
├── model.json    # Model topology, input signature, and weights manifest
└── weights.bin   # Quantized float32 binary tensor weights
```

---

## 3. Training a Custom Mobile Phone Model

### Step A: Dataset Preparation
Collect or utilize public mobile phone detection datasets:
- **Roboflow Mobile Phone Dataset** (over 4,000 annotated images of phones held in hand, on desks, and in varied lighting).
- **Kaggle Mobile Phone in Hand Dataset**.
- Annotate images with the single target bounding box class: `mobile_phone`.

### Step B: Model Training (TensorFlow / Keras or YOLOv8/SSD MobileNet)
Train a lightweight backbone (such as **MobileNetV2** or **SSD MobileNet V2 FPNLite 320x320**):

```python
import tensorflow as tf

# Example training pipeline with MobileNetV2 backbone
base_model = tf.keras.applications.MobileNetV2(
    input_shape=(224, 224, 3),
    include_top=False,
    weights='imagenet'
)
# Freeze base layers and train custom detection head for 'mobile_phone'
```

### Step C: Exporting to TensorFlow.js
Convert your saved model to the web-ready format using the official `tensorflowjs_converter`:

```bash
pip install tensorflowjs

tensorflowjs_converter \
    --input_format=tf_saved_model \
    --output_format=tfjs_graph_model \
    --signature_name=serving_default \
    --saved_model_tags=serve \
    /path/to/saved_model \
    app/static/models/phone_detector/
```

---

## 4. Model Verification & In-Browser Loading

The JavaScript detector in [app/static/js/proctoring/phone_detector.js](file:///c:/Users/Dell/Desktop/datadrix%20test/app/static/js/proctoring/phone_detector.js) will automatically:
1. Attempt to fetch `/static/models/phone_detector/model.json`.
2. Load the model graph into memory using `tf.loadGraphModel` or `tf.loadLayersModel`.
3. If the model loads successfully, the HUD will display:
   🟢 **Phone Guard: Active**
4. If the model is not found, damaged, or unsupported by the candidate's browser WebGL backend, it will gracefully transition to:
   ⚪ **Phone Guard: Unavailable (Setup Required)**
   and notify the backend via `PHONE_DETECTION_UNAVAILABLE`.
   **It will never trigger a false-positive cheating accusation due to a model loading issue.**

---

## 5. Detection Pipeline & False-Positive Mitigation

- **Sampling Rate**: Sampled at 300ms intervals (approx 3.3 FPS).
- **Confidence Filter**: Detections with confidence `< 0.70` are discarded.
- **Persistence Gate**: Must be detected in at least 3 consecutive sampled frames (~1 second of continuous visibility).
- **Deduplication Cooldown**: Once alerted, no duplicate warnings are fired while the phone remains continuously in view.
- **Absence Reset**: After the phone has been completely removed for at least 5 seconds, the state resets so any subsequent re-appearance will trigger a new warning.
