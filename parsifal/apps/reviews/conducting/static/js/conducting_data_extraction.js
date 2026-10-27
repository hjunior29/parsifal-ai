/* The forms of Data Extraction: each value is saved as soon as it changes. The list comes a page at a time
   (conducting_study_lists.js), so the handlers are bound to its container, which stays. */
$(function () {

  var $list = $(".extraction-container");

  /* "3 of 5 fields" in the study's heading: the fields with a value. */
  function updateProgress(panel) {
    var groups = $(".form-group[data-field-id]", panel);
    var filled = groups.filter(function () {
      var checked = $("input[type=checkbox]", this);
      if (checked.length) {
        return checked.filter(":checked").length > 0;
      }
      return $.trim($("input[type=text], select, textarea", this).val() || "") !== "";
    }).length;
    $(".study-progress", panel).text(filled + " of " + groups.length + " fields");
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
        $("span.error", row).text('');
        $("span.error", row).hide();
        $(row).removeClass("has-error");
        updateProgress(panel);
      },
      error: function (jqXHR, textStatus, errorThrown) {
        $("span.error", row).text(jqXHR.responseText);
        $("span.error", row).show();
        $(row).addClass("has-error");
      }
    });
  }

  $list.on("change", ".data-extraction-panel input[type='text'], .data-extraction-panel select, .data-extraction-panel textarea", function () {
    save_data_extraction_field($(this));
  });

  $list.on("click", ".data-extraction-panel input[type='checkbox']", function () {
    save_data_extraction_field($(this));
  });

  function markAs(link, done) {
    var panel = $(link).closest(".panel");
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
