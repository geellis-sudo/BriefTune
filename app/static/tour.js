/* BriefTune guided tour overlay.
 *
 * Plays the walkthrough video and moves a spotlight over the matching part of
 * the page, driven by app/static/tour_keyframes.json (timestamps extracted
 * from the final rendered VO — see that file's "video" block for provenance).
 *
 * Wiring: the #tour-trigger button (hero ghost CTA) starts the tour. The
 * script tag that loads this file carries data-video and data-keyframes URLs
 * so the template controls the asset paths via url_for.
 *
 * No dependencies. Nothing here runs until the trigger is clicked.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var VIDEO_URL = script ? script.getAttribute("data-video") : null;
  var KEYFRAMES_URL = script ? script.getAttribute("data-keyframes") : null;

  var trigger = document.getElementById("tour-trigger");
  if (!trigger || !VIDEO_URL || !KEYFRAMES_URL) {
    return;
  }

  var state = {
    open: false,
    keyframes: [],
    activeId: null,
    activeTargetEl: null,
    rafId: null,
    els: null,
  };

  function buildDom() {
    var overlay = document.createElement("div");
    overlay.className = "tour-overlay";
    overlay.innerHTML =
      '<div class="tour-spotlight" aria-hidden="true"></div>' +
      '<div class="tour-video-shell tour-video-shell--centered">' +
      '  <div class="tour-video-bar">' +
      '    <span class="tour-beat-label">BriefTune walkthrough</span>' +
      '    <button type="button" class="tour-close" aria-label="Close tour">&times;</button>' +
      "  </div>" +
      '  <video class="tour-video" playsinline preload="auto"></video>' +
      '  <div class="tour-controls">' +
      '    <button type="button" class="tour-playpause" aria-label="Pause">&#10074;&#10074;</button>' +
      '    <input type="range" class="tour-scrubber" min="0" max="100" step="0.1" value="0" aria-label="Video position">' +
      '    <span class="tour-time">0:00</span>' +
      "  </div>" +
      "</div>";
    document.body.appendChild(overlay);

    var video = overlay.querySelector(".tour-video");
    video.src = VIDEO_URL;

    return {
      overlay: overlay,
      spotlight: overlay.querySelector(".tour-spotlight"),
      shell: overlay.querySelector(".tour-video-shell"),
      label: overlay.querySelector(".tour-beat-label"),
      close: overlay.querySelector(".tour-close"),
      video: video,
      playpause: overlay.querySelector(".tour-playpause"),
      scrubber: overlay.querySelector(".tour-scrubber"),
      time: overlay.querySelector(".tour-time"),
    };
  }

  function formatTime(seconds) {
    var s = Math.max(0, Math.floor(seconds));
    return Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2);
  }

  function findKeyframe(t) {
    for (var i = 0; i < state.keyframes.length; i++) {
      var kf = state.keyframes[i];
      if (t >= kf.start && t < kf.end) {
        return kf;
      }
    }
    return null;
  }

  function currentTarget(kf, t) {
    if (!kf) return null;
    var selector = kf.target;
    if (kf.sub_cues) {
      for (var i = 0; i < kf.sub_cues.length; i++) {
        var cue = kf.sub_cues[i];
        if (cue.target && t >= cue.at) {
          selector = cue.target;
        }
      }
    }
    return selector ? document.querySelector(selector) : null;
  }

  function positionSpotlight() {
    var el = state.activeTargetEl;
    var els = state.els;
    if (!el || !els) return;
    var rect = el.getBoundingClientRect();
    var pad = 10;
    els.spotlight.style.top = rect.top - pad + "px";
    els.spotlight.style.left = rect.left - pad + "px";
    els.spotlight.style.width = rect.width + pad * 2 + "px";
    els.spotlight.style.height = rect.height + pad * 2 + "px";
  }

  function tick() {
    if (!state.open) return;
    var els = state.els;
    var t = els.video.currentTime;
    var kf = findKeyframe(t);
    var targetEl = currentTarget(kf, t);

    var beatChanged = (kf ? kf.id : null) !== state.activeId;
    if (beatChanged) {
      state.activeId = kf ? kf.id : null;
      els.label.textContent = kf && kf.label ? kf.label : "BriefTune walkthrough";
    }

    if (targetEl !== state.activeTargetEl) {
      state.activeTargetEl = targetEl;
      if (targetEl) {
        els.overlay.classList.add("tour-overlay--spotlit");
        els.shell.classList.remove("tour-video-shell--centered");
        if (typeof targetEl.scrollIntoView === "function") {
          targetEl.scrollIntoView({ behavior: "smooth", block: "center" });
        }
        // If the target lives inside a collapsed <details>, open it.
        var details = targetEl.closest ? targetEl.closest("details") : null;
        if (details && !details.open) details.open = true;
        if (targetEl.tagName === "DETAILS" && !targetEl.open) targetEl.open = true;
      } else {
        els.overlay.classList.remove("tour-overlay--spotlit");
        els.shell.classList.add("tour-video-shell--centered");
      }
    }

    if (state.activeTargetEl) positionSpotlight();

    // Keep the scrubber and clock in sync (skip while the user is dragging).
    if (!state.scrubbing && els.video.duration) {
      els.scrubber.value = (t / els.video.duration) * 100;
      els.time.textContent = formatTime(t);
    }

    state.rafId = window.requestAnimationFrame(tick);
  }

  function openTour() {
    if (state.open) return;
    if (!state.els) {
      state.els = buildDom();
      state.els.close.addEventListener("click", closeTour);
      state.els.video.addEventListener("ended", function () {
        window.setTimeout(function () {
          if (state.open) closeTour();
        }, 1500);
      });
      state.els.video.addEventListener("click", function () {
        var v = state.els.video;
        if (v.paused) v.play();
        else v.pause();
      });

      state.els.playpause.addEventListener("click", function () {
        var v = state.els.video;
        if (v.paused) v.play();
        else v.pause();
      });
      state.els.video.addEventListener("play", function () {
        state.els.playpause.innerHTML = "&#10074;&#10074;";
        state.els.playpause.setAttribute("aria-label", "Pause");
      });
      state.els.video.addEventListener("pause", function () {
        state.els.playpause.innerHTML = "&#9654;";
        state.els.playpause.setAttribute("aria-label", "Play");
      });

      state.els.scrubber.addEventListener("input", function () {
        state.scrubbing = true;
        var v = state.els.video;
        if (v.duration) {
          var t = (state.els.scrubber.value / 100) * v.duration;
          v.currentTime = t;
          state.els.time.textContent = formatTime(t);
        }
      });
      state.els.scrubber.addEventListener("change", function () {
        state.scrubbing = false;
      });
    }
    state.open = true;
    document.body.classList.add("tour-active");
    state.els.overlay.classList.add("tour-overlay--visible");
    state.els.video.currentTime = 0;
    state.els.video.play();
    state.rafId = window.requestAnimationFrame(tick);
  }

  function closeTour() {
    if (!state.open) return;
    state.open = false;
    state.activeId = null;
    state.activeTargetEl = null;
    if (state.rafId) window.cancelAnimationFrame(state.rafId);
    state.els.video.pause();
    state.els.overlay.classList.remove("tour-overlay--visible", "tour-overlay--spotlit");
    state.els.shell.classList.add("tour-video-shell--centered");
    document.body.classList.remove("tour-active");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && state.open) closeTour();
  });

  trigger.addEventListener("click", function () {
    if (state.keyframes.length) {
      openTour();
      return;
    }
    fetch(KEYFRAMES_URL)
      .then(function (response) { return response.json(); })
      .then(function (data) {
        state.keyframes = data.keyframes || [];
        openTour();
      })
      .catch(function () {
        // Keyframes missing/unparseable: still show the video, centered.
        state.keyframes = [];
        openTour();
      });
  });
})();
