/* Autosave.
 *
 * There is no save button, so this file is the only thing standing between what
 * he typed and losing it. It therefore does the boring, redundant thing on
 * purpose: a timer, a blur handler, a visibility handler, and a beacon on the
 * way out. Any one of them alone would be enough most of the time.
 *
 * If the editor bundle fails to load for any reason, a plain textarea takes
 * over and every one of those paths still works.
 */
(function () {
  "use strict";

  var AUTOSAVE_MS = 5000;

  var frame = document.getElementById("editor-frame");
  var fallback = document.getElementById("editor-fallback");
  var stateLine = document.getElementById("save-state");
  var initialNode = document.getElementById("initial-markdown");
  if (!frame || !fallback || !stateLine) return;

  var questionId = frame.getAttribute("data-question-id");
  var initial = "";
  try {
    initial = JSON.parse(initialNode.textContent) || "";
  } catch (err) {
    initial = fallback.value || "";
  }

  var toolbar = document.getElementById("editor-toolbar");
  var editor = null;
  var dirty = false;
  var lastSaved = initial;

  /* The toolbar only makes sense with the rich editor. With the plain-textarea
     fallback he is typing markdown directly, so the buttons are hidden rather
     than left there doing nothing. */
  function wireToolbar(instance) {
    if (!toolbar) return;
    toolbar.hidden = false;
    toolbar.addEventListener("click", function (event) {
      var button = event.target.closest("button[data-action]");
      if (!button) return;
      event.preventDefault();
      var action = button.getAttribute("data-action");
      if (typeof instance[action] === "function") {
        instance[action]();
        markDirty();
      }
    });
  }

  function readBody() {
    if (editor) {
      try {
        return editor.getMarkdown();
      } catch (err) {
        // Fall through to the textarea, which always holds something usable.
      }
    }
    return fallback.value;
  }

  function say(message, state) {
    stateLine.textContent = message;
    stateLine.setAttribute("data-state", state || "saved");
  }

  function clockTime(iso) {
    var when = iso ? new Date(iso) : new Date();
    if (isNaN(when.getTime())) when = new Date();
    var hours = when.getHours();
    var suffix = hours < 12 ? "am" : "pm";
    var hour = hours % 12 || 12;
    var minutes = String(when.getMinutes()).padStart(2, "0");
    return hour + ":" + minutes + suffix;
  }

  function markDirty() {
    dirty = true;
  }

  function save(reason) {
    var body = readBody();
    if (!dirty && body === lastSaved) return Promise.resolve();
    dirty = false;

    return fetch("/api/answer/" + encodeURIComponent(questionId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: body, reason: reason || "autosave" }),
    })
      .then(function (response) {
        if (!response.ok) throw new Error("save failed: " + response.status);
        return response.json();
      })
      .then(function (payload) {
        lastSaved = body;
        say("Saved " + clockTime(payload.updated), "saved");
      })
      .catch(function (err) {
        // Never show a false "Saved". If it did not land, say so plainly.
        dirty = true;
        say("Not saved yet — keep this page open and it will keep trying.", "problem");
        if (window.console) console.error("veillee autosave", err);
      });
  }

  /* Last-ditch save when the tab is closing. fetch is cancelled at that point;
     sendBeacon is not. */
  function beacon() {
    var body = readBody();
    if (!dirty && body === lastSaved) return;
    try {
      var blob = new Blob([JSON.stringify({ body: body, reason: "pagehide" })], {
        type: "application/json",
      });
      navigator.sendBeacon("/api/answer/" + encodeURIComponent(questionId), blob);
      lastSaved = body;
    } catch (err) {
      /* Nothing further we can do at this point in the page lifecycle. */
    }
  }

  /* Milkdown renders a role="textbox" contenteditable of its own. It needs an
     accessible name, and the wrapper div cannot legally carry one. */
  function nameTheEditor() {
    var box = frame.querySelector('[contenteditable="true"]');
    if (box) {
      box.setAttribute("aria-label", "Your answer");
      box.setAttribute("aria-multiline", "true");
    }
  }

  function useFallbackEditor(why) {
    frame.hidden = true;
    fallback.hidden = false;
    fallback.value = initial;
    fallback.addEventListener("input", markDirty);
    fallback.addEventListener("blur", function () {
      save("blur");
    });
    if (why && window.console) console.warn("veillee: plain editor in use —", why);
  }

  /* On a question he has not answered yet, put the cursor in the box so he can
     simply start typing. preventScroll keeps the question itself on screen -
     landing in the box is only helpful if he can still read what he is
     answering. Never on a question that already has words in it: that would
     risk him typing into the middle of something he wrote last week. */
  function focusIfBlank() {
    if (lastSaved.trim()) return;
    var box = frame.hidden ? fallback : frame.querySelector('[contenteditable="true"]');
    if (!box) return;
    try {
      box.focus({ preventScroll: true });
    } catch (err) {
      box.focus();
    }
  }

  function start() {
    focusIfBlank();
    window.setInterval(function () {
      save("interval");
    }, AUTOSAVE_MS);

    /* Leaving the editor saves immediately, without waiting for the timer.
       `blur` does not bubble from the contenteditable, and window blur only
       fires when the whole browser loses focus - not when he clicks from the
       text onto the page. `focusout` does bubble, so it catches the case that
       actually happens. */
    frame.addEventListener("focusout", function (event) {
      if (frame.contains(event.relatedTarget)) return; // still inside the editor
      save("blur");
    });

    /* Tab indents a list inside the editor rather than moving on, which would
       otherwise trap a keyboard user in the writing area (WCAG 2.1.2). Escape
       is the documented way out, and the hint below the box says so whenever
       the editor has focus. */
    frame.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      var box = frame.querySelector('[contenteditable="true"]');
      if (box) box.blur();
      var onward = document.querySelector(".button-row a.button, .button-row button");
      if (onward) onward.focus();
      save("escape");
    });

    window.addEventListener("blur", function () {
      save("blur");
    });
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden") beacon();
    });
    window.addEventListener("pagehide", beacon);

    document.querySelectorAll("form").forEach(function (form) {
      // Skipping or moving on must not drop the last few seconds of typing.
      form.addEventListener("submit", function () {
        beacon();
      });
    });
    document.querySelectorAll("a[href]").forEach(function (link) {
      link.addEventListener("click", function () {
        beacon();
      });
    });
  }

  if (window.VeilleeEditor && typeof window.VeilleeEditor.mount === "function") {
    window.VeilleeEditor.mount(frame, initial, markDirty)
      .then(function (instance) {
        editor = instance;
        nameTheEditor();
        wireToolbar(instance);
        start();
      })
      .catch(function (err) {
        useFallbackEditor(err && err.message);
        start();
      });
  } else {
    useFallbackEditor("editor bundle did not load");
    start();
  }

  // Exposed so the browser tests can force a save without waiting on the timer.
  window.veilleeSaveNow = function () {
    dirty = true;
    return save("test");
  };
})();
