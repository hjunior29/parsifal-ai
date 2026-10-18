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
});