/*
 * The AI runs window: the review's Exclude, Include and Retain with AI runs, a run's details, and undoing a run (what
 * it would do first, then a confirmed click). "Run again" opens the setup window of the run's phase with its settings
 * (conducting_ai_screening.js). Once a run is undone, the studies table is loaded again when the window closes.
 */
$(function () {
  var $modal = $("#modal-ai-runs");
  var undone = false;

  function reviewId() { return $("#review-id").val(); }

  function failed(xhr) {
    $.parsifal.alert("AI runs", xhr.responseText || "The server did not answer (" + (xhr.status || "network error") + ").");
  }

  function load(url, data) {
    return $.ajax({url: url, data: $.extend({"review-id": reviewId()}, data), type: "get", cache: false})
      .done(function (html) { $modal.find(".modal-content").html(html); })
      .fail(failed);
  }

  function list() { return load("/reviews/conducting/ai_runs/"); }

  $("#btn-ai-runs").click(function () {
    list().done(function () { $modal.modal("show"); });
  });

  $modal.on("click", ".js-ai-runs-back", list);

  $modal.on("click", ".js-ai-run-details", function () {
    load("/reviews/conducting/ai_runs/run/", {"run-id": $(this).data("run-id")});
  });

  $modal.on("change", ".js-ai-run-outcome", function () {
    var outcome = $(this).val();
    $modal.find(".ai-run-results tbody tr").each(function () {
      $(this).toggle(!outcome || $(this).data("outcome") === outcome);
    });
  });

  $modal.on("click", ".js-ai-run-undo", function () {
    load("/reviews/conducting/ai_runs/undo/", {"run-id": $(this).data("run-id")});
  });

  $modal.on("change", ".js-ai-undo-confirm", function () {
    $modal.find(".js-ai-undo-apply").prop("disabled", !this.checked);
  });

  $modal.on("click", ".js-ai-undo-apply", function () {
    var $button = $(this).prop("disabled", true);
    $.ajax({
      url: "/reviews/conducting/ai_runs/undo/",
      type: "post",
      data: {
        "review-id": reviewId(),
        "run-id": $button.data("run-id"),
        "csrfmiddlewaretoken": $modal.find("input[name=csrfmiddlewaretoken]").val()
      }
    }).done(function (html) {
      undone = true;
      $modal.find(".modal-content").html(html);
    }).fail(function (xhr) {
      failed(xhr);
      $button.prop("disabled", false);
    });
  });

  $modal.on("hidden.bs.modal", function () {
    if (undone) {
      undone = false;
      $(document).trigger("studies-changed");  // the study list again, on the same page and filters
    }
  });
});
