/**
 * Datadrix Assessment Security & Interaction Lock
 * Disables copy, cut, paste, text selection, context menu (right click), drag-and-drop,
 * and cheating keyboard shortcuts (Ctrl+C, Ctrl+V, Ctrl+X, Ctrl+A, Ctrl+U, F12, DevTools).
 */
(function () {
  'use strict';

  function showRestrictedToast(message) {
    let toast = document.getElementById('securityLockToast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'securityLockToast';
      toast.className = 'security-lock-toast';
      toast.innerHTML = `
        <div class="d-flex align-items-center gap-3">
          <i class="bi bi-shield-lock-fill text-warning fs-4 flex-shrink-0"></i>
          <div>
            <div class="fw-bold text-white small">Action Restricted</div>
            <div class="text-slate-300 small restricted-msg" style="font-size: 0.8rem;"></div>
          </div>
        </div>
      `;
      document.body.appendChild(toast);
    }

    const msgEl = toast.querySelector('.restricted-msg');
    if (msgEl) {
      msgEl.textContent = message || 'Copy, paste, right-click, and text selection are disabled to preserve exam integrity.';
    }

    toast.classList.add('show');
    clearTimeout(toast._hideTimer);
    toast._hideTimer = setTimeout(() => {
      toast.classList.remove('show');
    }, 2800);
  }

  // 1. Block Copy
  document.addEventListener('copy', (e) => {
    e.preventDefault();
    if (e.clipboardData) {
      e.clipboardData.setData('text/plain', '');
    }
    showRestrictedToast('Copying text or questions is strictly prohibited.');
    if (window.IntegrityMonitor && typeof window.IntegrityMonitor.reportViolation === 'function') {
      window.IntegrityMonitor.reportViolation('clipboard_attempt', { action: 'copy' });
    }
    return false;
  });

  // 2. Block Cut
  document.addEventListener('cut', (e) => {
    e.preventDefault();
    if (e.clipboardData) {
      e.clipboardData.setData('text/plain', '');
    }
    showRestrictedToast('Cutting text is disabled during this session.');
    return false;
  });

  // 3. Block Paste
  document.addEventListener('paste', (e) => {
    e.preventDefault();
    showRestrictedToast('Pasting content is disabled during this session.');
    if (window.IntegrityMonitor && typeof window.IntegrityMonitor.reportViolation === 'function') {
      window.IntegrityMonitor.reportViolation('clipboard_attempt', { action: 'paste' });
    }
    return false;
  });

  // 4. Block Right-Click Context Menu
  document.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    showRestrictedToast('Right-click context menu is disabled.');
    return false;
  });

  // 5. Block Text Selection
  document.addEventListener('selectstart', (e) => {
    const tag = (e.target && e.target.tagName) || '';
    if (tag !== 'INPUT' && tag !== 'TEXTAREA') {
      e.preventDefault();
      return false;
    }
  });

  // 6. Block Drag & Drop
  document.addEventListener('dragstart', (e) => {
    e.preventDefault();
    return false;
  });
  document.addEventListener('drop', (e) => {
    e.preventDefault();
    return false;
  });

  // 7. Block Keyboard Shortcuts
  document.addEventListener('keydown', (e) => {
    const isCtrlOrCmd = e.ctrlKey || e.metaKey;
    const key = (e.key || '').toLowerCase();

    // DevTools: F12, Ctrl+Shift+I, Ctrl+Shift+J, Ctrl+Shift+C
    if (e.key === 'F12' || (isCtrlOrCmd && e.shiftKey && (key === 'i' || key === 'j' || key === 'c'))) {
      e.preventDefault();
      showRestrictedToast('Developer tools access is disabled.');
      return false;
    }

    // Ctrl/Cmd + C, V, X, A, U, S, P
    if (isCtrlOrCmd && ['c', 'v', 'x', 'a', 'u', 's', 'p'].includes(key)) {
      e.preventDefault();
      const actionName = {
        c: 'Copy (Ctrl+C)',
        v: 'Paste (Ctrl+V)',
        x: 'Cut (Ctrl+X)',
        a: 'Select All (Ctrl+A)',
        u: 'View Source (Ctrl+U)',
        s: 'Save Page (Ctrl+S)',
        p: 'Print (Ctrl+P)'
      }[key] || key.toUpperCase();

      showRestrictedToast(`${actionName} is disabled during the assessment.`);
      return false;
    }
  });

  // Expose toast function globally if needed
  window.showSecurityLockToast = showRestrictedToast;
})();
