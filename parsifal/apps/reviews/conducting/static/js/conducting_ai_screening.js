/*
 * Exclude with AI (phase 1 of study selection) and Include with AI (phase 2). Opens the setup window of the phase,
 * starts a run (or continues an unfinished one) and then asks the server to screen the next few studies until the
 * run ends, showing progress as it goes.
 * A run cannot be stopped; when it is interrupted (connection lost, Jev refusing the key or unavailable) the window
 * offers to continue it. "Done" reloads the page so the table shows the rejected studies.
 */
$(function () {
  var $modal = $("#modal-ai-screening");
  var run = null;
  var retries = 0;

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

  $(document).on("click", ".btn-ai-screening", function () {
    run = null;
    var phase = $(this).data("phase") || "exclusion";
    $.get("/reviews/conducting/ai_screening/", {"review-id": reviewId(), "phase": phase}, function (html) {
      $modal.find(".modal-content").html(html);
      updateCount();
      $modal.modal("show");
    });
  });

  $modal.on("change", "#ai-source, #ai-reviewer, input[name=statuses]", updateCount);

  $modal.on("change", ".js-ai-all-statuses", function () {
    $modal.find("input[name=statuses]").prop("checked", this.checked);
    updateCount();
  });

  $modal.on("click", ".js-ai-start", function () {
    var $button = $(this).prop("disabled", true);
    $modal.find(".js-ai-form-error").hide();
    $.ajax({
      url: "/reviews/conducting/ai_screening/start/",
      type: "post",
      data: $("#ai-screening-form").serialize(),
      dataType: "json"
    }).done(function (data) {
      showProgress(data.run);
      step();
    }).fail(function (xhr) {
      $modal.find(".js-ai-form-error").text(errorMessage(xhr)).show();
      $modal.find(".modal-body").scrollTop(0);
      $button.prop("disabled", false);
    });
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
    $modal.find(".js-ai-run-error").hide();
    $modal.find(".js-ai-status").empty().append($("<strong>").text("Screening…"));
    $modal.find(".js-ai-bar").addClass("active progress-bar-striped");
    $modal.find(".ai-screening-progress").show();
    window.addEventListener("beforeunload", warnBeforeLeaving);
    render(state, []);
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
      if (result.outcome === "excluded") {
        $item.append($("<span class='label label-danger'>").text("Rejected · " + result.criteria + " · " + result.p_exclude.toFixed(2)));
      } else if (result.outcome === "passed") {
        $item.append($("<span class='label label-default'>").text("Passed · " + result.p_exclude.toFixed(2)));
      } else if (result.outcome === "included") {
        $item.append($("<span class='label label-success'>").text("Accepted · " + result.p_include.toFixed(2)));
      } else if (result.outcome === "undecided") {
        $item.append($("<span class='label label-default'>").text("Undecided · " + result.p_include.toFixed(2)));
      } else {
        $item.append($("<span class='label label-warning'>").text("Error"));
        $item.attr("title", result.error);
      }
      $item.append(" ").append($("<span>").text(result.title));
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
    var titles = {finished: "Finished.", cancelled: "Discarded: another run was started."};
    var summary = state.phase === "inclusion"
      ? " " + state.included + " accepted, " + state.undecided + " undecided (left unclassified)"
      : " " + state.excluded + " rejected, " + state.passed + " passed (no criterion)";
    if (state.failed) { summary += ", " + state.failed + " errors (those studies keep the reviewer's previous decision)"; }
    $modal.find(".js-ai-status").empty()
      .append($("<strong>").text(titles[state.status] || "Stopped."))
      .append(document.createTextNode(summary + "."));
  }

  $modal.on("click", ".js-ai-done", function () {
    window.location.reload();
  });
});
