$(function () {

  $("#quality-menu li a").click(function () {
    var a = $(this);
    $.ajax({
      url: $(a).attr("href"),
      data: { 'review-id': $('#review-id').val() },
      type: 'get',
      cache: false,
      beforeSend: function () {
        $(".quality-container").loading();
      },
      success: function (data) {
        $(".quality-container").html(data);
      },
      complete: function () {
        $(".quality-container").stopLoading();
        $("#quality-menu li").removeClass("active");
        $(a).closest("li").addClass("active");
      }
    });
    return false;
  });

  /* A click on an answer chooses it; a click on the chosen one clears it, and the question is unanswered again. */
  $(".quality-container").on("click", "td.answer", function () {
    var td = $(this);
    if (td.hasClass("processing")) { return; }
    var clear = td.hasClass("selected-answer");
    var tbl = td.closest(".panel");
    var old_text = td.text();

    $.ajax({
      url: '/reviews/conducting/save_quality_assessment/',
      data: {
        'review-id': $("#review-id").val(),
        'article-id': td.closest("table").attr("article-id"),
        'question-id': td.closest("tr").attr("question-id"),
        'answer-id': clear ? "" : td.attr("answer-id"),
        'csrfmiddlewaretoken': td.closest("table").attr("csrf-token")
      },
      type: 'post',
      cache: false,
      beforeSend: function () {
        td.addClass("processing").text("Processing...");
      },
      success: function (data) {
        $('.score', tbl).text(data);
        td.siblings().removeClass("selected-answer");
        td.toggleClass("selected-answer", !clear);
        $('.study-progress', tbl).text($("td.selected-answer", tbl).length + " of " + $("#questions-count").val() + " answered");
      },
      complete: function () {
        td.removeClass("processing").text(old_text);
      }
    });
  });

});