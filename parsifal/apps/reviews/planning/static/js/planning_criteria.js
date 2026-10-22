$(function () {
  function addCriteria(criteria, type, input, select_list) {
    var review_id = $('#review-id').val();
    $.ajax({
      url: '/reviews/planning/add_criteria/',
      data: { 
        'criteria': criteria, 
        'review-id': review_id,
        'criteria-type': type
      },
      type: 'get',
      cache: false,
      success: function (data) {
        // Keep the list in the server's order (by description).
        var item = $(data);
        var description = String(item.data("description"));
        var next = select_list.children(".criteria-option").filter(function () {
          return String($(this).data("description")).localeCompare(description) > 0;
        }).first();
        if (next.length) { item.insertBefore(next); } else { select_list.append(item); }
        input.val("");
        input.focus();
      }
    });
  }

  $("input#input-inclusion").keyup(function (event) {
    if (event.keyCode == 13) {
      var criteria = $(this).val();
      if (criteria != ""){
        addCriteria(criteria, 'I', $("input#input-inclusion"), $("#inclusion-criteria"));
      }
    }
  });

  $("input#input-exclusion").keyup(function (event) {
    if (event.keyCode == 13) {
      var criteria = $(this).val();
      if (criteria != ""){
        addCriteria(criteria, 'E', $("input#input-exclusion"), $("#exclusion-criteria"));
      }
    }
  });

  // Selection behaves like a native multiple <select>: click picks one, Cmd/Ctrl+click toggles, Shift+click
  // selects a range.
  var anchor = null;
  $(".criteria-listbox").on("click", ".criteria-option", function (event) {
    var option = $(this);
    var options = option.parent().children(".criteria-option");
    if (event.shiftKey && anchor && anchor.parent().is(option.parent())) {
      var from = options.index(anchor), to = options.index(option);
      options.attr("aria-selected", "false");
      options.slice(Math.min(from, to), Math.max(from, to) + 1).attr("aria-selected", "true");
    } else if (event.metaKey || event.ctrlKey) {
      option.attr("aria-selected", option.attr("aria-selected") === "true" ? "false" : "true");
      anchor = option;
    } else {
      options.attr("aria-selected", "false");
      option.attr("aria-selected", "true");
      anchor = option;
    }
  });

  $(".btn-remove-criteria").click(function () {
    var selected = $($(this).attr("data-target")).children('.criteria-option[aria-selected="true"]');
    if (selected.length === 0) {
      return;
    }
    var ids = selected.map(function () { return $(this).data("id"); }).get();
    $.ajax({
      url: '/reviews/planning/remove_criteria/',
      data: { 'review-id': $('#review-id').val(), 'criteria-ids': ids.join(",") },
      type: 'get',
      cache: false,
      success: function () {
        selected.remove();
      }
    });
  });

  // Whether a study must meet all the inclusion criteria or at least one.
  $("#inclusion-rule").change(function () {
    var $status = $(".js-inclusion-rule-status").text("Saving…");
    $.ajax({
      url: "/reviews/planning/save_inclusion_rule/",
      type: "post",
      data: {
        "review-id": $("#review-id").val(),
        "inclusion-rule": $(this).val(),
        "csrfmiddlewaretoken": $("input[name=csrfmiddlewaretoken]").first().val()
      },
      success: function () { $status.text("Saved."); },
      error: function (xhr) { $status.text(xhr.responseText || "Could not save."); }
    });
  });
});
