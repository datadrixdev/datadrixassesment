/**
 * Mobile Phone Detector Module - Disabled.
 * Phone guard functionality has been deactivated per application policy.
 */
const PhoneDetectorModule = (() => {
  return {
    initialize: async () => false,
    processVideoFrame: async () => null,
    isReady: () => false,
    isAvailable: () => false,
    reset: () => {},
    setOnWarning: () => {},
    setOnStatusUpdate: () => {}
  };
})();

if (typeof window !== "undefined") {
  window.PhoneDetectorModule = PhoneDetectorModule;
}
