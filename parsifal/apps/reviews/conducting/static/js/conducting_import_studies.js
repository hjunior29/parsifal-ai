$(function () {
  $(".btn-import-bibtex").click(function () {
    var container = $(this).closest("td");
    $("input[type=file]", container).click();
  });


  $("input[name='bibtex']").change(function () {
    var form = $(this).closest("form");
    $(form).submit();
  });

  $(".js-clear-source").submit(function () {
    var message =
      "Delete all " + $(this).data("count") + " studies imported from " + $(this).data("source") + "?\n\n" +
      "Their decisions, quality assessments and extracted data are deleted too. This cannot be undone.";
    return window.confirm(message);
  });

  $(".js-import-bibtex-raw-content").click(function () {
    var source_id = $(this).attr("data-source-id");
    $("#bibtex-raw-content-source-id").val(source_id);
  });

  $("#parse-bibtex").on("shown.bs.modal", function () {
    $("#bibtex_raw_content").focus();
  });

  /* A known study (the test set): the form opens on its title. */
  $("#known-study-add").on("shown.bs.collapse", function () {
    $("textarea[name='title']", this).focus();
  });

  /* The date of search of a source: saved as soon as it changes (empty clears it). */
  $(".js-searched-at").change(function () {
    var input = $(this);
    var status = input.siblings(".js-searched-at-status");
    $.ajax({
      url: "/reviews/conducting/import/searched_at/",
      type: "post",
      data: {
        "review-id": $("#review-id").val(),
        "source-id": input.data("source-id"),
        "searched-at": input.val(),
        "csrfmiddlewaretoken": $("input[name='csrfmiddlewaretoken']").first().val()
      },
      success: function () {
        status.removeClass("text-danger").text("Saved.").show().delay(1500).fadeOut();
      },
      error: function (xhr) {
        status.stop(true, true).addClass("text-danger").text($.parsifal.requestError(xhr)).show();
      }
    });
  });
});