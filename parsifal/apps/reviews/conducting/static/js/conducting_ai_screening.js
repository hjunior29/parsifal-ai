/*
 * Exclude with AI, Include with AI and Screen with AI (both in one request), in no particular order. Opens the setup
 * window of the action — prefilled with the settings of its last run, or Parsifal's defaults after "Restore
 * defaults" —, starts a run (or continues an unfinished one) and then asks the server to screen the next few studies
 * until the run ends, showing progress as it goes. The request to Jev is a template edited as JSON text, previewed
 * (filled in by the server for the first study in scope) before starting.
 * A run cannot be stopped; when it is interrupted (connection lost, Jev refusing the key or unavailable) the window
 * offers to continue it. "Done" reloads the page so the table shows the rejected studies. While it screens, a clock
 * shows the time spent in this window and, at that pace, about how long is left.
 * A run that would rewrite the reviewer's decisions, or change studies the reviewer classified, says so and starts on
 * a second click. "Run again" in the AI runs window opens this window with the settings of that run (run-id).
 */
$(function () {
  var $modal = $("#modal-ai-screening");
  var run = null;
  var retries = 0;
  var timer = null;
  var startedAt = 0;
  var startProcessed = 0;

  // Seconds as m:ss, or h:mm:ss from an hour on.
  function clock(seconds) {
    seconds = Math.max(0, Math.round(seconds));
    var hours = Math.floor(seconds / 3600);
    var minutes = Math.floor((seconds % 3600) / 60);
    var rest = ("0" + (seconds % 60)).slice(-2);
    return hours ? hours + ":" + ("0" + minutes).slice(-2) + ":" + rest : minutes + ":" + rest;
  }

  function elapsed() { return (Date.now() - startedAt) / 1000; }

  function tick() {
    var seconds = elapsed();
    var text = clock(seconds) + " elapsed";
    var done = run.processed - startProcessed;
    var left = run.total - run.processed;
    if (timer && done > 0 && left > 0) {
      text += " · about " + clock(left * seconds / done) + " left";
    }
    $modal.find(".js-ai-timer").text(text);
  }

  function startTimer() {
    stopTimer();
    startedAt = Date.now();
    startProcessed = run.processed;
    timer = setInterval(tick, 1000);
    tick();
  }

  function stopTimer() {
    if (timer) { clearInterval(timer); }
    timer = null;
  }

  function reviewId() { return $("#review-id").val(); }
  function csrf() { return $modal.find("input[name=csrfmiddlewaretoken]").val(); }

  function errorMessage(xhr) {
    if (xhr.responseJSON && xhr.responseJSON.error) { return xhr.responseJSON.error; }
    return "The server did not answer (" + (xhr.status || "network error") + ").";
  }

  function warnBeforeLeaving(event) {
    event.preventDefault();
    event.returnValue = "";
  }

  // Studies sent = those of the chosen source with one of the checked statuses (counts: source -> status -> n).
  function updateCount() {
    var counts = JSON.parse($("#ai-screening-counts").text() || "{}");
    var bySource = counts[$("#ai-source").val() || ""] || {};
    var reviewer = $("#ai-reviewer").val();
    var $statuses = $modal.find("input[name=statuses]");
    var $checked = $statuses.filter(":checked");
    var total = 0;
    $modal.find(".js-ai-status-count").each(function () {
      $(this).text(bySource[$(this).data("status")] || 0);
    });
    $checked.each(function () { total += bySource[this.value] || 0; });
    $modal.find(".js-ai-all-statuses")
      .prop("checked", $checked.length === $statuses.length)
      .prop("indeterminate", $checked.length > 0 && $checked.length < $statuses.length);
    $modal.find(".js-ai-count").text(reviewer ? total : "—");
    $modal.find(".js-ai-start").prop("disabled", !reviewer || total === 0);
  }

  function openWindow(data) {
    run = null;
    preview = null;
    confirmed = false;
    var $open = $(".modal.in").not($modal);
    $.get("/reviews/conducting/ai_screening/", data, function (html) {
      $modal.find(".modal-content").html(html);
      updateCount();
      // Run again, from the AI runs window: this window takes its place.
      if ($open.length) {
        $open.one("hidden.bs.modal", function () { $modal.modal("show"); }).modal("hide");
      } else {
        $modal.modal("show");
      }
    });
  }

  $(document).on("click", ".btn-ai-screening", function () {
    var data = {"review-id": reviewId(), "phase": $(this).data("phase") || "exclusion"};
    if ($(this).data("run-id")) { data["run-id"] = $(this).data("run-id"); }
    openWindow(data);
  });

  // Every setting back to Parsifal's defaults, in place of the last run's.
  $modal.on("click", ".js-ai-restore-defaults", function () {
    $.get("/reviews/conducting/ai_screening/", {"review-id": reviewId(), "phase": $(this).data("phase"), "defaults": 1}, function (html) {
      $modal.find(".modal-content").html(html);
      updateCount();
    });
  });

  // A run that rewrites the reviewer's decisions, or may change studies they classified, starts on a second click.
  var confirmed = false;

  function resetConfirmation() {
    confirmed = false;
    $modal.find(".js-ai-impact").hide();
    $modal.find(".js-ai-start").text("Start screening");
  }

  $modal.on("change", "#ai-source, #ai-reviewer, input[name=statuses]", function () {
    resetConfirmation();
    updateCount();
  });

  $modal.on("change", ".js-ai-all-statuses", function () {
    $modal.find("input[name=statuses]").prop("checked", this.checked);
    resetConfirmation();
    updateCount();
  });

  // Request to Jev: the template is edited as text; the server fills it in for the first study in scope.
  var preview = null;

  $modal.on("click", ".js-ai-preview", function () {
    var $button = $(this).prop("disabled", true);
    $modal.find(".js-ai-preview-error").hide();
    $.ajax({
      url: "/reviews/conducting/ai_screening/preview/",
      type: "post",
      data: $("#ai-screening-form").serialize(),
      dataType: "json"
    }).done(function (data) {
      preview = data.request;
      $modal.find(".js-ai-preview-title").text(data.article.title);
      $modal.find(".js-ai-preview-json").text(JSON.stringify(data.request, null, 2));
      $modal.find(".js-ai-preview-box").show();
    }).fail(function (xhr) {
      $modal.find(".js-ai-preview-box").hide();
      $modal.find(".js-ai-preview-error").text(errorMessage(xhr)).show();
    }).always(function () {
      $button.prop("disabled", false);
    });
  });

  // The older way, for browsers that refuse the clipboard API (no secure context, no permission).
  function copyBySelecting(text) {
    var $area = $("<textarea>").val(text).css({position: "fixed", top: 0, left: 0, opacity: 0}).appendTo($modal);
    $area[0].select();
    var copied = false;
    try { copied = document.execCommand("copy"); } catch (error) { copied = false; }
    $area.remove();
    return copied ? Promise.resolve() : Promise.reject();
  }

  function copyText(text) {
    if (!navigator.clipboard) { return copyBySelecting(text); }
    return navigator.clipboard.writeText(text).catch(function () { return copyBySelecting(text); });
  }

  // What the playground of Jev takes in its two fields.
  $modal.on("click", ".js-ai-copy", function () {
    var $button = $(this);
    if (!preview) { return; }
    var label = $button.data("label") || $button.text();
    $button.data("label", label);
    copyText(JSON.stringify(preview[$button.data("part")], null, 2)).then(function () {
      $button.text("Copied");
    }, function () {
      $button.text("Copy failed: select it below");
    }).then(function () {
      setTimeout(function () { $button.text(label); }, 2000);
    });
  });

  function formError(xhr, $button) {
    $modal.find(".js-ai-form-error").text(errorMessage(xhr)).show();
    $modal.find(".modal-body").scrollTop(0);
    $button.prop("disabled", false);
  }

  function start($button) {
    $.ajax({
      url: "/reviews/conducting/ai_screening/start/",
      type: "post",
      data: $("#ai-screening-form").serialize(),
      dataType: "json"
    }).done(function (data) {
      showProgress(data.run);
      step();
    }).fail(function (xhr) { formError(xhr, $button); });
  }

  $modal.on("click", ".js-ai-start", function () {
    var $button = $(this).prop("disabled", true);
    $modal.find(".js-ai-form-error").hide();
    if (confirmed) { start($button); return; }
    $.ajax({
      url: "/reviews/conducting/ai_screening/impact/",
      type: "post",
      data: $("#ai-screening-form").serialize(),
      dataType: "json"
    }).done(function (impact) {
      if (!impact.confirm) { start($button); return; }
      confirmed = true;
      $modal.find(".js-ai-impact").text(impact.message).show();
      $button.text("Start anyway").prop("disabled", false);
    }).fail(function (xhr) { formError(xhr, $button); });
  });

  // Continue an unfinished run: from the notice of the setup window, or after an interruption in this window.
  $modal.on("click", ".js-ai-continue", function () {
    if (!run) { run = JSON.parse($("#ai-screening-unfinished").text()); }
    showProgress(run);
    step();
  });

  function showProgress(state) {
    run = state;
    retries = 0;
    $modal.find(".ai-screening-setup, .js-ai-start, .js-ai-close, .js-ai-count-line, .js-ai-retry, .js-ai-done").hide();
    $modal.find(".js-ai-impact").hide();
    $modal.find(".js-ai-run-error").hide();
    $modal.find(".js-ai-status").empty().append($("<strong>").text("Screening…"));
    $modal.find(".js-ai-bar").addClass("active progress-bar-striped");
    $modal.find(".ai-screening-progress").show();
    window.addEventListener("beforeunload", warnBeforeLeaving);
    render(state, []);
    startTimer();
  }

  function render(state, results) {
    run = state;
    var percent = state.total ? Math.round(100 * state.processed / state.total) : 100;
    $modal.find(".js-ai-bar").css("width", percent + "%").text(percent + "%");
    $modal.find(".js-ai-labels").each(function () { $(this).toggle($(this).data("phase") === state.phase); });
    $modal.find(".js-ai-excluded").text(state.excluded);
    $modal.find(".js-ai-passed").text(state.passed);
    $modal.find(".js-ai-included").text(state.included);
    $modal.find(".js-ai-undecided").text(state.undecided);
    $modal.find(".js-ai-failed").text(state.failed);
    $modal.find(".js-ai-processed").text(state.processed);
    $modal.find(".js-ai-total").text(state.total);
    var $log = $modal.find(".js-ai-log");
    $.each(results, function (index, result) {
      var $item = $("<li>");
      // The status the run gave the study, as the study list names it, with Jev's probability.
      var labels = {Rejected: "label-danger", Accepted: "label-success", Unclassified: "label-default"};
      if (result.status) {
        var text = result.status;
        if (result.criteria && result.outcome === "excluded") { text += " · " + result.criteria; }
        var probability = result.outcome === "excluded" || result.p_include === null ? result.p_exclude : result.p_include;
        if (probability !== null) { text += " · " + probability.toFixed(2); }
        $item.append($("<span class='label'>").addClass(labels[result.status]).text(text));
        if (result.kept) {
          $item.attr("title", "Kept " + result.kept + ": classified by someone else; the reviewer's decision is recorded");
        }
      } else {
        $item.append($("<span class='label label-warning'>").text("Error"));
        $item.attr("title", result.error);
      }
      $item.append(" ").append($("<span>").text(result.title));
      if (result.kept) {
        $item.append(" ").append($("<span class='text-muted'>").text("— kept " + result.kept));
      }
      if (result.outcome === "error") {
        $item.append(" ").append($("<span class='text-muted'>").text("— " + result.error));
      }
      $log.prepend($item);
    });
  }

  function step() {
    $.ajax({
      url: "/reviews/conducting/ai_screening/step/",
      type: "post",
      data: {"review-id": reviewId(), "run-id": run.id, "csrfmiddlewaretoken": csrf()},
      dataType: "json"
    }).done(function (data) {
      retries = 0;
      render(data.run, data.results);
      if (data.run.status !== "running") {
        finish(data.run);
      } else if (data.run.error) {
        interrupted(data.run.error);
      } else {
        step();
      }
    }).fail(function (xhr) {
      retries += 1;
      if (retries <= 3) {
        setTimeout(step, 2000 * retries);
      } else {
        interrupted(errorMessage(xhr));
      }
    });
  }

  function settle() {
    stopTimer();
    tick();
    window.removeEventListener("beforeunload", warnBeforeLeaving);
    $modal.find(".js-ai-bar").removeClass("active progress-bar-striped");
    $modal.find(".js-ai-done").show();
  }

  function interrupted(message) {
    settle();
    $modal.find(".js-ai-status").empty()
      .append($("<strong>").text("Interrupted."))
      .append(document.createTextNode(" " + run.processed + " of " + run.total + " screened; the rest waits. Continue now or later."));
    $modal.find(".js-ai-run-error").text(message).show();
    $modal.find(".js-ai-retry").show();
  }

  function finish(state) {
    settle();
    render(state, []);
    var titles = {finished: "Finished in " + clock(elapsed()) + ".", cancelled: "Discarded: another run was started."};
    var summaries = {
      exclusion: " " + state.excluded + " rejected, " + state.passed + " unclassified",
      inclusion: " " + state.included + " accepted, " + state.undecided + " unclassified",
      screen: " " + state.excluded + " rejected, " + state.included + " accepted, " + state.undecided + " unclassified"
    };
    var summary = summaries[state.phase] || summaries.exclusion;
    if (state.failed) { summary += ", " + state.failed + " errors (those studies keep the reviewer's previous decision)"; }
    $modal.find(".js-ai-status").empty()
      .append($("<strong>").text(titles[state.status] || "Stopped."))
      .append(document.createTextNode(summary + "."));
  }

  $modal.on("click", ".js-ai-done", function () {
    window.location.reload();
  });
});
