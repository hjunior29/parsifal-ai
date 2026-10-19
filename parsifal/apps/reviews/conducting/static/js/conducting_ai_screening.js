/*
 * Exclude with AI (phase 1 of study selection). Opens the setup window, starts a run and then asks the server to
 * screen the next few studies until the run ends, showing progress as it goes. "Done" reloads the page so the
 * table shows the rejected studies.
 */
$(function () {
  var $modal = $("#modal-ai-screening");
  var run = null;
  var stopping = false;
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

  function updateCount() {
    var counts = JSON.parse($("#ai-screening-counts").text() || "{}");
    var scope = counts[$("#ai-source").val() || ""] || {all: 0, "new": 0};
    var total = $modal.find("input[name=rescreen]").is(":checked") ? scope.all : scope["new"];
    $modal.find(".js-ai-count").text(total);
    $modal.find(".js-ai-start").prop("disabled", total === 0);
  }

  $(document).on("click", ".btn-ai-screening", function () {
    run = null;
    stopping = false;
    $.get("/reviews/conducting/ai_screening/", {"review-id": reviewId()}, function (html) {
      $modal.find(".modal-content").html(html);
      updateCount();
      $modal.modal("show");
    });
  });

  $modal.on("change", "#ai-source, input[name=rescreen]", updateCount);

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

  function showProgress(state) {
    run = state;
    $modal.find(".ai-screening-setup, .js-ai-start, .js-ai-close, .js-ai-count-line").hide();
    $modal.find(".ai-screening-progress, .js-ai-stop").show();
    window.addEventListener("beforeunload", warnBeforeLeaving);
    render(state, []);
  }

  function render(state, results) {
    run = state;
    var percent = state.total ? Math.round(100 * state.processed / state.total) : 100;
    $modal.find(".js-ai-bar").css("width", percent + "%").text(percent + "%");
    $modal.find(".js-ai-excluded").text(state.excluded);
    $modal.find(".js-ai-passed").text(state.passed);
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
    if (stopping) { cancel(); return; }
    $.ajax({
      url: "/reviews/conducting/ai_screening/step/",
      type: "post",
      data: {"review-id": reviewId(), "run-id": run.id, "csrfmiddlewaretoken": csrf()},
      dataType: "json"
    }).done(function (data) {
      retries = 0;
      render(data.run, data.results);
      if (data.run.status === "running") { step(); } else { finish(data.run); }
    }).fail(function (xhr) {
      retries += 1;
      if (retries <= 3) {
        setTimeout(step, 2000 * retries);
      } else {
        finish($.extend({}, run, {status: "failed", error: errorMessage(xhr)}));
      }
    });
  }

  function cancel() {
    $.ajax({
      url: "/reviews/conducting/ai_screening/cancel/",
      type: "post",
      data: {"review-id": reviewId(), "run-id": run.id, "csrfmiddlewaretoken": csrf()},
      dataType: "json"
    }).done(function (data) { finish(data.run); })
      .fail(function () { finish($.extend({}, run, {status: "cancelled"})); });
  }

  $modal.on("click", ".js-ai-stop", function () {
    stopping = true;
    $(this).prop("disabled", true).text("Stopping…");
  });

  function finish(state) {
    window.removeEventListener("beforeunload", warnBeforeLeaving);
    render(state, []);
    var titles = {finished: "Finished.", cancelled: "Stopped.", failed: "Stopped because of an error."};
    var summary = " " + state.excluded + " rejected, " + state.passed + " passed to the next phase";
    if (state.failed) { summary += ", " + state.failed + " errors (they stay unclassified and are sent again next time)"; }
    $modal.find(".js-ai-status").empty()
      .append($("<strong>").text(titles[state.status] || "Stopped."))
      .append(document.createTextNode(summary + "."));
    $modal.find(".js-ai-bar").removeClass("active progress-bar-striped");
    if (state.error) { $modal.find(".js-ai-run-error").text(state.error).show(); }
    $modal.find(".js-ai-stop").hide();
    $modal.find(".js-ai-done").show();
  }

  $modal.on("click", ".js-ai-done", function () {
    window.location.reload();
  });
});
