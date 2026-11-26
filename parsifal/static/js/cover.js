/* Parsifal landing page interactive review-menu tabs & scroll reveal fallback.
 * - Switches between real-style Parsifal phase panels on click (no auto-carousel)
 * - Syncs the review progress bar to the selected phase
 * - IntersectionObserver fallback when CSS animation-timeline: view() is unavailable
 */
(function () {
  "use strict";

  var prefersMotion =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: no-preference)").matches;

  var supportsScrollDriven =
    window.CSS &&
    typeof window.CSS.supports === "function" &&
    window.CSS.supports("(animation-timeline: view()) and (animation-range: entry)");

  if (prefersMotion && !supportsScrollDriven && "IntersectionObserver" in window) {
    document.documentElement.classList.add("js-motion-io");
    var revealEls = document.querySelectorAll(".cover-reveal");
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    revealEls.forEach(function (el) {
      observer.observe(el);
    });
  }

  var workspace = document.querySelector("[data-cover-workspace]");
  if (!workspace) {
    return;
  }

  var tabs = workspace.querySelectorAll("[data-scene-tab]");
  var scenes = workspace.querySelectorAll("[data-scene-panel]");
  var progressBar = workspace.querySelector("[data-progress-bar]");
  var progressValue = workspace.querySelector("[data-progress-value]");
  var progressNext = workspace.querySelector("[data-progress-next]");

  function activateScene(index) {
    tabs.forEach(function (btn, i) {
      var selected = i === index;
      btn.setAttribute("aria-selected", selected ? "true" : "false");
      if (btn.parentElement) {
        btn.parentElement.classList.toggle("active", selected);
      }
    });

    scenes.forEach(function (panel, i) {
      var selected = i === index;
      panel.classList.toggle("is-active", selected);
      panel.hidden = !selected;
    });

    var activeBtn = tabs[index];
    if (!activeBtn) {
      return;
    }

    var pct = activeBtn.getAttribute("data-progress") || "25";
    var nextText = activeBtn.getAttribute("data-next") || "";

    if (progressBar) {
      progressBar.style.width = pct + "%";
      progressBar.setAttribute("aria-valuenow", pct);
      progressBar.classList.toggle("progress-bar-success", pct === "100");
    }
    if (progressValue) {
      progressValue.textContent = pct + "%";
    }
    if (progressNext) {
      progressNext.textContent = nextText;
    }
  }

  tabs.forEach(function (btn, idx) {
    btn.addEventListener("click", function () {
      activateScene(idx);
    });
  });

  activateScene(0);
})();
