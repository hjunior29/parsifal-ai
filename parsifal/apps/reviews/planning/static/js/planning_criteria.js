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
        var next = select_list.children(".criteria-item").filter(function () {
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

  $(".btn-remove-criteria").click(function () {
    var list = $($(this).attr("data-target"));
    var checked = list.find("input[type=checkbox]:checked");
    if (checked.length === 0) {
      return;
    }
    var ids = checked.map(function () { return $(this).val(); }).get();
    $.ajax({
      url: '/reviews/planning/remove_criteria/',
      data: { 'review-id': $('#review-id').val(), 'criteria-ids': ids.join(",") },
      type: 'get',
      cache: false,
      success: function () {
        checked.closest(".criteria-item").remove();
      }
    });
  });
});
