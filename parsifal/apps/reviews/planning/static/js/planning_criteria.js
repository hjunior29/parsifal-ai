/* The selection criteria of the Protocol: two lists, inclusion and exclusion, each criterion with its code (IC1,
   EC2…), which its place in its list gives it. A criterion is added, edited in its row, removed, or moved up or down
   (the codes follow, renumberCodes). */
$(function () {

  function csrf() {
    return $("input[name=csrfmiddlewaretoken]").first().val();
  }

  function post(url, data) {
    return $.ajax({
      url: url,
      type: "post",
      cache: false,
      data: $.extend({"review-id": $("#review-id").val(), "csrfmiddlewaretoken": csrf()}, data)
    });
  }

  /* The row where a criterion is written: a new one (``row`` empty) or one being edited. */
  function formRow(text) {
    return $(
      '<tr class="criteria-form-row">' +
        '<td colspan="3"><input type="text" class="form-control" maxlength="200"></td>' +
        '<td class="protocol-actions">' +
          '<button type="button" class="btn btn-sm btn-success js-save-criteria"><span class="glyphicon glyphicon-ok"></span> save</button> ' +
          '<button type="button" class="btn btn-sm btn-default js-cancel-criteria">cancel</button>' +
          '<span class="help-block text-danger js-criteria-error" style="display: none;"></span>' +
        '</td>' +
      '</tr>'
    ).find("input").val(text || "").end();
  }

  function saveOrder(tbody) {
    renumberCodes(tbody);
    var ids = $(tbody).children("tr[data-criteria-id]").map(function () {
      return $(this).attr("data-criteria-id");
    }).get();
    if (ids.length) {
      post("/reviews/planning/save_criteria_order/", {"ids": ids.join(",")});
    }
  }

  $(".js-add-criteria").click(function () {
    var type = $(this).attr("data-criteria-type");
    var tbody = $(".js-criteria-list[data-criteria-type=" + type + "] tbody");
    var row = formRow("").attr("data-new", "1");
    tbody.append(row);
    row.find("input").focus();
  });

  $(".js-criteria-list").on("click", ".js-edit-criteria", function () {
    var row = $(this).closest("tr");
    var form = formRow($.trim(row.find(".js-criteria-text").text())).data("original", row);
    form.attr("data-editing", row.attr("data-criteria-id"));
    row.replaceWith(form);
    form.find("input").focus();
  });

  $(".js-criteria-list").on("click", ".js-cancel-criteria", function () {
    var form = $(this).closest("tr");
    if (form.data("original")) {
      form.replaceWith(form.data("original"));
    } else {
      form.remove();
    }
  });

  function save(form) {
    var tbody = form.closest("tbody");
    var type = form.closest(".js-criteria-list").attr("data-criteria-type");
    var text = $.trim(form.find("input").val());
    if (!text) { return; }
    var editing = form.attr("data-editing");
    var request = editing
      ? post("/reviews/planning/save_criteria/", {"criteria-id": editing, "criteria": text})
      : post("/reviews/planning/add_criteria/", {"criteria-type": type, "criteria": text});
    request.done(function (html) {
      form.replaceWith(html);
      renumberCodes(tbody);
    }).fail(function (xhr) {
      form.find(".js-criteria-error").text(xhr.responseText || "Could not save.").show();
    });
  }

  $(".js-criteria-list").on("click", ".js-save-criteria", function () {
    save($(this).closest("tr"));
  });

  $(".js-criteria-list").on("keydown", ".criteria-form-row input", function (event) {
    if (event.keyCode === 13) {
      event.preventDefault();
      save($(this).closest("tr"));
    } else if (event.keyCode === 27) {
      $(this).closest("tr").find(".js-cancel-criteria").click();
    }
  });

  $(".js-criteria-list").on("click", ".js-remove-criteria", function () {
    var row = $(this).closest("tr");
    var tbody = row.closest("tbody");
    var code = row.find(".js-code").text();
    if (!confirm("Remove the criterion " + code + "? The studies that have it keep their status, without it.")) {
      return;
    }
    post("/reviews/planning/remove_criteria/", {"criteria-ids": row.attr("data-criteria-id")}).done(function () {
      row.remove();
      renumberCodes(tbody);
    });
  });

  $(".js-criteria-list").on("click", ".js-criteria-up, .js-criteria-down", function () {
    var row = $(this).closest("tr");
    var up = $(this).hasClass("js-criteria-up");
    var other = up ? row.prevAll("tr[data-criteria-id]").first() : row.nextAll("tr[data-criteria-id]").first();
    if (!other.length) { return; }
    if (up) { row.insertBefore(other); } else { row.insertAfter(other); }
    saveOrder(row.closest("tbody"));
  });

  // Whether a study must meet all the inclusion criteria or at least one.
  $("#inclusion-rule").change(function () {
    var $status = $(".js-inclusion-rule-status").text("Saving…");
    post("/reviews/planning/save_inclusion_rule/", {"inclusion-rule": $(this).val()})
      .done(function () { $status.text("Saved."); })
      .fail(function (xhr) { $status.text(xhr.responseText || "Could not save."); });
  });
});
