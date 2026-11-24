/* The forms of Data Extraction: each value is saved as soon as it changes, and so is its evidence. The list comes a
   page at a time (conducting_study_lists.js), so the handlers are bound to its container, which stays. */
$(function () {

  var $list = $(".extraction-container");

  function hasValue(row) {
    var checked = $("input[type=checkbox]", row);
    if (checked.length) {
      return checked.filter(":checked").length > 0;
    }
    return $.trim($("input[type=text], select, textarea:not(.js-evidence)", row).val() || "") !== "";
  }

  /* A value without evidence is flagged: the study can be marked as done only when each value has one. */
  function flagEvidence(row) {
    var missing = hasValue(row) && $.trim($(".js-evidence", row).val() || "") === "";
    $(row).toggleClass("has-warning", missing);
    $(".js-evidence-warning", row).toggle(missing);
    return missing;
  }

  /* "3 of 5 fields · 1 without evidence" in the study's heading. */
  function updateProgress(panel) {
    var groups = $(".form-group[data-field-id]", panel);
    var filled = groups.filter(function () { return hasValue(this); }).length;
    var missing = groups.filter(function () { return flagEvidence(this); }).length;
    var text = filled + " of " + groups.length + " fields";
    if (missing) {
      text += " · " + missing + " without evidence";
    }
    $(".study-progress", panel).text(text);
  }

  function showError(row, jqXHR) {
    $("span.error", row).text(jqXHR.responseText).show();
    $(row).addClass("has-error");
  }

  function clearError(row) {
    $("span.error", row).text("").hide();
    $(row).removeClass("has-error");
  }

  function save_data_extraction_field(ref) {
    var row = $(ref).closest(".form-group");
    var panel = $(ref).closest(".panel");
    var review_id = $("#review-id").val();
    var article_id = $(ref).closest(".panel-body").attr("data-article-id");
    var field_id = $(row).attr("data-field-id");
    var value = $(ref).val();
    var csrf_token = $("input[name=csrfmiddlewaretoken]").val();
    $.ajax({
      url: '/reviews/conducting/save_data_extraction/',
      data: {
        'review-id': review_id,
        'article-id': article_id,
        'field-id': field_id,
        'value': value,
        'csrfmiddlewaretoken': csrf_token
      },
      type: 'post',
      cache: false,
      success: function (data) {
        clearError(row);
        updateProgress(panel);
      },
      error: function (jqXHR, textStatus, errorThrown) {
        showError(row, jqXHR);
      }
    });
  }

  function saveEvidence(textarea) {
    var row = $(textarea).closest(".form-group");
    var panel = $(textarea).closest(".panel");
    $.ajax({
      url: '/reviews/conducting/save_data_extraction_evidence/',
      data: {
        'review-id': $("#review-id").val(),
        'article-id': $(textarea).closest(".panel-body").attr("data-article-id"),
        'field-id': $(row).attr("data-field-id"),
        'evidence': $(textarea).val(),
        'csrfmiddlewaretoken': $("input[name=csrfmiddlewaretoken]").val()
      },
      type: 'post',
      cache: false,
      success: function () {
        clearError(row);
        updateProgress(panel);
      },
      error: function (jqXHR) {
        showError(row, jqXHR);
      }
    });
  }

  $list.on("change", ".data-extraction-panel input[type='text'], .data-extraction-panel select, .data-extraction-panel textarea:not(.js-evidence)", function () {
    save_data_extraction_field($(this));
  });

  $list.on("change", ".data-extraction-panel .js-evidence", function () {
    saveEvidence(this);
  });

  $list.on("click", ".data-extraction-panel input[type='checkbox']", function () {
    save_data_extraction_field($(this));
  });

  function markAs(link, done) {
    var panel = $(link).closest(".panel");
    var message = $(".js-extraction-message", panel);
    message.hide();
    $.ajax({
      url: '/reviews/conducting/save_data_extraction_status/',
      type: 'post',
      data: {
        'review-id': $("#review-id").val(),
        'csrfmiddlewaretoken': $("input[name=csrfmiddlewaretoken]").val(),
        'article-id': panel.attr("data-article-id"),
        'action': done ? 'mark_as_done' : 'mark_as_undone'
      },
      success: function () {
        var tab = $("#data-extraction-tab").val();
        if (tab === "all") {
          var action_button = $(".js-finished-button", panel);
          $(".glyphicon", action_button).removeClass().addClass(done ? "glyphicon glyphicon-check" : "glyphicon glyphicon-unchecked");
          $(".action-text", action_button).text(done ? "mark as undone" : "mark as done");
          $(action_button).removeClass().addClass(done ? "js-finished-button js-mark-as-not-finished" : "js-finished-button js-mark-as-finished");
        }
        else {
          $(panel).fadeOut(200);  // it leaves this tab
        }
      },
      error: function (jqXHR) {
        // A value without evidence: the panel opens on the message, its fields flagged.
        message.text(jqXHR.responseText || "Could not mark the study as done.").show();
        panel.children(".collapse").collapse("show");
      }
    });
  }

  $list.on("click", ".js-mark-as-finished", function () {
    markAs(this, true);
  });

  $list.on("click", ".js-mark-as-not-finished", function () {
    markAs(this, false);
  });

});
