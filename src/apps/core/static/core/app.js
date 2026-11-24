// Progressive enhancements. Every page works without this file.
// Loaded from 'self' only (Content-Security-Policy: script-src 'self'); no inline handlers.
(function () {
  "use strict";

  const ALLOWED = ["image/jpeg", "image/png", "image/webp"];

  function formatSize(bytes) {
    return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(bytes / 1024)) + " KB";
  }

  // Photo picker: drag and drop, preview, early type and size check.
  document.querySelectorAll("[data-dropzone]").forEach(function (zone) {
    const input = zone.querySelector("input[type=file]");
    const preview = zone.querySelector("[data-preview-img]");
    const name = zone.querySelector("[data-preview-name]");
    const size = zone.querySelector("[data-preview-size]");
    const error = document.getElementById(zone.dataset.errorTarget);
    const maxBytes = Number(zone.dataset.maxMb) * 1048576;

    function showError(message) {
      if (!error) return;
      error.textContent = message;
      error.hidden = !message;
      zone.closest(".field").classList.toggle("has-error", Boolean(message));
    }

    function show(file) {
      if (!file) { zone.classList.remove("has-file"); return; }
      if (ALLOWED.indexOf(file.type) === -1) {
        showError("Only JPEG, PNG and WebP photos can be uploaded.");
        input.value = ""; zone.classList.remove("has-file"); return;
      }
      if (file.size > maxBytes) {
        showError("That file is larger than " + zone.dataset.maxMb + " MB. Choose a smaller photo.");
        input.value = ""; zone.classList.remove("has-file"); return;
      }
      showError("");
      name.textContent = file.name;
      size.textContent = formatSize(file.size);
      const reader = new FileReader();  // data: URL, because the CSP does not allow blob: images
      reader.onload = function () { preview.src = reader.result; };
      reader.readAsDataURL(file);
      zone.classList.add("has-file");
    }

    input.addEventListener("change", function () { show(input.files[0]); });
    ["dragenter", "dragover"].forEach(function (type) {
      zone.addEventListener(type, function () { zone.classList.add("is-dragover"); });
    });
    ["dragleave", "drop"].forEach(function (type) {
      zone.addEventListener(type, function () { zone.classList.remove("is-dragover"); });
    });
  });

  // Busy state, so a slow request is never submitted twice.
  function setBusy(form) {
    const button = form.querySelector("button[type=submit]");
    if (!button) return;
    if (button.dataset.busyLabel) button.querySelector("[data-label]").textContent = button.dataset.busyLabel;
    button.setAttribute("aria-busy", "true");
    setTimeout(function () { button.disabled = true; }, 0);  // after the browser has captured the form data
  }

  // Confirmation dialog (<dialog> in core/base.html). Tones: "danger" (default: destructive),
  // "restore" (primary button) and "warn" (a consequence worth a second look, primary button).
  const dialog = document.getElementById("confirm-dialog");
  let pending = null;

  function openDialog(options) {
    if (!dialog || typeof dialog.showModal !== "function") {  // very old browsers: native fallback
      if (window.confirm(options.message)) options.onConfirm();
      return;
    }
    pending = options;
    dialog.querySelector("[data-confirm-title]").textContent = options.title || "Are you sure?";
    dialog.querySelector("[data-confirm-message]").textContent = options.message || "";
    const subject = dialog.querySelector("[data-confirm-subject]");
    subject.textContent = options.subject || "";
    subject.hidden = !options.subject;
    const accept = dialog.querySelector("[data-confirm-accept]");
    accept.querySelector("[data-label]").textContent = options.action || "Confirm";
    dialog.querySelector("[data-cancel-label]").textContent = options.cancelLabel || "Cancel";
    const tone = ["restore", "warn"].indexOf(options.tone) >= 0 ? options.tone : "danger";
    dialog.dataset.tone = tone;
    accept.classList.toggle("button-danger-solid", tone === "danger");
    accept.classList.toggle("button-primary", tone !== "danger");
    dialog.showModal();
    dialog.querySelector("[data-confirm-cancel]").focus();  // the safe choice has focus
  }

  // Every way out of the dialog ends here, so nothing depends on the timing of the close event.
  function finish(confirmed) {
    const options = pending;
    pending = null;
    if (dialog.open) dialog.close();
    if (!options) return;
    if (confirmed) options.onConfirm();
    else if (options.returnFocus) options.returnFocus.focus();  // back to where the user was
  }

  if (dialog) {
    dialog.querySelector("[data-confirm-accept]").addEventListener("click", function () { finish(true); });
    dialog.querySelector("[data-confirm-cancel]").addEventListener("click", function () { finish(false); });
    dialog.addEventListener("cancel", function (event) {  // Escape key
      event.preventDefault();
      finish(false);
    });
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) finish(false);  // click on the backdrop
    });
  }

  // Unsaved changes: forms marked data-unsaved warn before their changes are lost.
  let dirty = false;
  document.querySelectorAll("form[data-unsaved]").forEach(function (form) {
    form.addEventListener("input", function () { dirty = true; });
    form.addEventListener("change", function () { dirty = true; });
  });
  window.addEventListener("beforeunload", function (event) {  // closing the tab, reloading, Back
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
  document.addEventListener("click", function (event) {  // links inside the app: our own dialog
    if (!dirty || event.defaultPrevented || event.button !== 0) return;
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest("a[href]");
    if (!link || link.target === "_blank" || link.getAttribute("href").charAt(0) === "#") return;
    event.preventDefault();
    openDialog({
      tone: "warn",
      title: "Discard your changes?",
      message: "You have changes that aren't saved yet. If you leave this page, they are lost.",
      action: "Discard changes",
      cancelLabel: "Keep editing",
      returnFocus: link,
      onConfirm: function () { dirty = false; window.location.href = link.href; },
    });
  });

  // Conditional confirmations: data-confirm-check="<name>" asks only when the change needs it.
  const checks = {
    // Editing a user: disabling the account or resetting the password signs them out.
    "user-access": function (form) {
      const active = form.querySelector("input[name=is_active]");
      const password = form.querySelector("input[name=password1]");
      const disabling = active && active.defaultChecked && !active.checked;
      const resetting = password && password.value !== "";
      if (!disabling && !resetting) return null;
      const effects = [];
      if (disabling) effects.push("they can no longer sign in and are signed out everywhere");
      if (resetting) effects.push("their current password stops working, so share the new one with them securely");
      return {
        tone: disabling ? "danger" : "warn",
        title: disabling && resetting ? "Disable the account and reset the password?"
          : disabling ? "Disable this account?" : "Reset this user's password?",
        message: "If you save, " + effects.join(", and ") + ".",
        action: disabling ? "Disable account" : "Reset password",
      };
    },
    // Editing a photo: a replacement becomes the photo everyone sees.
    "replace-photo": function (form) {
      const file = form.querySelector("input[type=file][name=photo]");
      if (!file || !file.files || !file.files.length) return null;
      return {
        tone: "warn",
        title: "Replace the photo?",
        message: "Everyone will see the new photo. The current one is kept in the change history as evidence, " +
          "with its checksum, and can still be opened from there.",
        action: "Replace photo",
      };
    },
  };

  document.querySelectorAll("form[data-confirm], form[data-confirm-check], form[data-busy]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      let ask = null;
      if (form.dataset.confirm) {
        ask = {
          tone: form.dataset.confirmTone, title: form.dataset.confirmTitle, message: form.dataset.confirm,
          action: form.dataset.confirmAction,
        };
      } else if (form.dataset.confirmCheck && checks[form.dataset.confirmCheck]) {
        ask = checks[form.dataset.confirmCheck](form);
      }
      if (ask) {
        event.preventDefault();
        ask.subject = form.dataset.confirmSubject || "";
        ask.returnFocus = form.querySelector("button[type=submit]");
        ask.onConfirm = function () {
          dirty = false;
          setBusy(form);
          form.submit();  // submit() skips the submit event, so the dialog is not shown again
        };
        openDialog(ask);
        return;
      }
      dirty = false;
      setBusy(form);
    });
  });

  // Toasts (region and templates in core/base.html). Without this file a server-rendered toast
  // simply stays on the page.
  const toastRegion = document.querySelector(".toast-region");
  const TOAST_MS = 5000;
  const MAX_TOASTS = 3;

  function closeToast(toast) {
    if (toast.dataset.closing) return;
    toast.dataset.closing = "true";
    toast.classList.add("is-leaving");
    // A timer, not animationend: animations are off when the user prefers reduced motion.
    setTimeout(function () { toast.remove(); }, 200);
  }

  function armToast(toast) {
    const dismiss = toast.querySelector("[data-toast-dismiss]");
    dismiss.hidden = false;
    dismiss.addEventListener("click", function () { closeToast(toast); });
    // Pause while the pointer or keyboard focus is on the toast, so it can be read.
    let timer = null;
    function start() { clearTimeout(timer); timer = setTimeout(function () { closeToast(toast); }, TOAST_MS); }
    function stop() { clearTimeout(timer); }
    toast.addEventListener("mouseenter", stop);
    toast.addEventListener("mouseleave", start);
    toast.addEventListener("focusin", stop);
    toast.addEventListener("focusout", start);
    start();
  }

  function showToast(message, tone) {
    const template = document.getElementById(tone === "error" ? "toast-template-error" : "toast-template");
    if (!toastRegion || !template) return;
    const toast = template.content.firstElementChild.cloneNode(true);
    toast.querySelector("[data-toast-message]").textContent = message;
    while (toastRegion.children.length >= MAX_TOASTS) toastRegion.firstElementChild.remove();
    toastRegion.appendChild(toast);
    armToast(toast);
  }

  document.querySelectorAll(".toast-region [data-toast]").forEach(armToast);

  // The notice came in the redirect's query string; drop it so a reload does not repeat it.
  const url = new URL(window.location.href);
  if (url.searchParams.has("notice")) {
    url.searchParams.delete("notice");
    history.replaceState(history.state, "", url.pathname + url.search + url.hash);
  }

  // Copy evidence values (object key, version, checksum).
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.hidden = !navigator.clipboard;
    const what = button.getAttribute("aria-label").replace(/^Copy\s+/, "");  // "object key"
    const copied = what.charAt(0).toUpperCase() + what.slice(1) + " copied to the clipboard.";
    button.addEventListener("click", function () {
      // data-copy="@url" copies this page's address (the host the visitor sees, e.g. CloudFront).
      const value = button.dataset.copy === "@url" ? window.location.origin + window.location.pathname : button.dataset.copy;
      navigator.clipboard.writeText(value).then(function () {
        button.classList.add("copied");
        setTimeout(function () { button.classList.remove("copied"); }, 1500);
        showToast(copied);
      }, function () {
        showToast("Could not copy the " + what + ". Select it and copy it by hand.", "error");
      });
    });
  });

  // Show/hide password. The button stays hidden without JavaScript, where it couldn't work.
  document.querySelectorAll("[data-password-toggle]").forEach(function (button) {
    var input = document.getElementById(button.getAttribute("data-password-toggle"));
    if (!input) { return; }
    button.hidden = false;
    button.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      button.setAttribute("aria-pressed", String(show));
      button.setAttribute("aria-label", show ? "Hide password" : "Show password");
      input.focus();
    });
  });
})();
