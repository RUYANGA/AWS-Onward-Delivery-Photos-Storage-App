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

  // Confirmation dialog (<dialog> in core/base.html). data-confirm-tone="restore" gives it the
  // restore icon and a primary button; the default tone is for destructive actions.
  const dialog = document.getElementById("confirm-dialog");
  let pendingForm = null;

  function askToConfirm(form) {
    if (!dialog || typeof dialog.showModal !== "function") {
      return window.confirm(form.dataset.confirm);  // very old browsers: native fallback
    }
    pendingForm = form;
    dialog.querySelector("[data-confirm-title]").textContent = form.dataset.confirmTitle || "Are you sure?";
    dialog.querySelector("[data-confirm-message]").textContent = form.dataset.confirm;
    const subject = dialog.querySelector("[data-confirm-subject]");
    subject.textContent = form.dataset.confirmSubject || "";
    subject.hidden = !form.dataset.confirmSubject;
    const accept = dialog.querySelector("[data-confirm-accept]");
    accept.querySelector("[data-label]").textContent = form.dataset.confirmAction || "Confirm";
    const tone = form.dataset.confirmTone === "restore" ? "restore" : "danger";
    dialog.dataset.tone = tone;
    accept.classList.toggle("button-danger-solid", tone === "danger");
    accept.classList.toggle("button-primary", tone === "restore");
    dialog.showModal();
    dialog.querySelector("[data-confirm-cancel]").focus();  // the safe choice has focus
    return false;
  }

  // Every way out of the dialog ends here, so nothing depends on the timing of the close event.
  function finish(confirmed) {
    const form = pendingForm;
    pendingForm = null;
    if (dialog.open) dialog.close();
    if (!form) return;
    if (confirmed) {
      setBusy(form);
      form.submit();  // submit() skips the submit event, so the dialog is not shown again
    } else {
      const trigger = form.querySelector("button[type=submit]");
      if (trigger) trigger.focus();  // return focus to where the user was
    }
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

  document.querySelectorAll("form[data-confirm], form[data-busy]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (form.dataset.confirm && !askToConfirm(form)) {
        event.preventDefault();
        return;
      }
      setBusy(form);
    });
  });

  // Copy evidence values (object key, version, checksum).
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.hidden = !navigator.clipboard;
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(button.dataset.copy).then(function () {
        const label = button.getAttribute("aria-label");
        button.classList.add("copied");
        button.setAttribute("aria-label", "Copied");
        setTimeout(function () {
          button.classList.remove("copied");
          button.setAttribute("aria-label", label);
        }, 1500);
      });
    });
  });

  // Dismissible notices.
  document.querySelectorAll("[data-dismiss]").forEach(function (button) {
    button.hidden = false;
    button.addEventListener("click", function () { button.closest(".notice").remove(); });
  });
})();
