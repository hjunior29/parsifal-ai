/* The lists of studies of Quality Assessment and Data Extraction.

   They come a page at a time: the search (".js-study-search", as you type), the other controls of the form
   ".js-study-list-controls" ("Show", the order, the tab) and the pager are sent to the form's data-url, which sends
   back that page of ".js-study-list". Each study's panel is closed at first and opens with a click on its heading;
   its "Study" link opens the study's window (details and full text). */
$(function () {

  var request = null;

  function requestError(xhr) {
    var text = xhr.responseText || "";
    if (text && text.indexOf("<") !== 0) {
      return text;
    }
    return "Request failed" + (xhr.status ? " (" + xhr.status + " " + xhr.statusText + ")" : "") + ".";
  }

  /* Loads the list again with ``changes`` (another page or size); ``done`` runs once it is shown. */
  function loadList(changes, done) {
    var form = $(".js-study-list-controls");
    var list = $(".js-study-list");
    var data = {'part': 'list', 'page': list.find(".js-study-list-page").attr("data-page") || 1};
    $.each(form.serializeArray(), function (_, field) { data[field.name] = field.value; });
    $.extend(data, changes || {});
    if (request) { request.abort(); }
    request = $.ajax({
      url: form.attr("data-url"),
      data: data,
      type: 'get',
      cache: false,
      beforeSend: function () { list.addClass("list-reloading"); },
      success: function (html) {
        list.html(html);
        if (done) { done(); }
      },
      error: function (xhr, status) {
        if (status !== "abort") {
          $.parsifal.alert("Could not load the studies", requestError(xhr));
        }
      },
      complete: function (xhr, status) {
        if (status !== "abort") {
          request = null;
          list.removeClass("list-reloading");
        }
      }
    });
  }

  var searchTimer = null;
  $(document).on("input", ".js-study-list-controls .js-study-search", function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () { loadList({'page': 1}); }, 300);
  });

  $(document).on("change", ".js-study-list-controls select, .js-study-list-controls input[type=radio]", function () {
    loadList({'page': 1});
  });

  $(document).on("submit", ".js-study-list-controls", function (event) {
    event.preventDefault();
    clearTimeout(searchTimer);
    loadList({'page': 1});
  });

  $(document).on("click", ".js-study-list .js-page", function (event) {
    event.preventDefault();
    loadList({'page': $(this).attr("data-page")}, function () {
      $('html, body').animate({scrollTop: $(".js-study-list").offset().top - 80}, 200);
    });
  });

  $(document).on("change", ".js-study-list .js-per-page", function () {
    loadList({'per-page': $(this).val(), 'page': 1});
  });

  /* A study's panel opens and closes with a click on its heading (or Enter / space on it), but not from the links
     and fields inside the heading. */
  $(document).on("click", ".js-study-list .js-toggle-study", function (event) {
    if ($(event.target).closest("a, button, input, select, textarea, label").length) {
      return;
    }
    $(this).closest(".panel").children(".collapse").collapse("toggle");
  });

  $(document).on("keydown", ".js-study-list .js-toggle-study", function (event) {
    if ((event.which === 13 || event.which === 32) && event.target === this) {
      event.preventDefault();
      $(this).closest(".panel").children(".collapse").collapse("toggle");
    }
  });

  $(document).on("show.bs.collapse hide.bs.collapse", ".js-study-list .panel > .collapse", function (event) {
    var open = event.type === "show";
    var heading = $(this).siblings(".js-toggle-study");
    heading.attr("aria-expanded", open ? "true" : "false");
    heading.find(".js-toggle-icon")
      .toggleClass("glyphicon-chevron-down", open)
      .toggleClass("glyphicon-chevron-right", !open);
  });

  $(document).on("click", ".js-expand-all", function () {
    $(".js-study-list .panel > .collapse").collapse("show");
  });

  $(document).on("click", ".js-collapse-all", function () {
    $(".js-study-list .panel > .collapse").collapse("hide");
  });

  /* The study's window: its details and its full text, to read while assessing or extracting. */
  var $window = $("#modal-study");

  function loadPdfFrame() {
    var frame = $window.find(".article-pdf-frame");
    if (frame.length && !frame.attr("src") && $window.find("#study-full-text").hasClass("active")) {
      frame.attr("src", frame.data("src"));
    }
  }

  $(document).on("click", ".js-study-list .js-open-study", function (event) {
    event.preventDefault();
    var body = $window.find(".modal-body");
    body.css("max-height", $(window).height() * 0.75);
    $window.modal("show");
    $.ajax({
      url: '/reviews/conducting/study/',
      data: {'review-id': $("#review-id").val(), 'article-id': $(this).attr("data-article-id")},
      type: 'get',
      cache: false,
      beforeSend: function () { body.loading(); },
      success: function (html) {
        body.html(html);
        loadPdfFrame();  // it opens on the full text, when there is one
      },
      error: function (xhr) {
        body.html($("<p class='text-danger'></p>").text(requestError(xhr)));
      },
      complete: function () { body.stopLoading(); }
    });
  });

  $window.on("shown.bs.tab", "a[href='#study-full-text']", loadPdfFrame);

  function postPdf(url, data, title) {
    var study = $window.find("#study-window");
    data.append("csrfmiddlewaretoken", study.find("[name=csrfmiddlewaretoken]").val());
    data.append("review-id", study.attr("data-review-id"));
    data.append("article-id", study.attr("data-article-id"));
    var buttons = $window.find("#article-pdf button");
    $.ajax({
      url: url,
      type: 'post',
      data: data,
      cache: false,
      contentType: false,
      processData: false,
      beforeSend: function () { buttons.prop("disabled", true); },
      success: function (html) {
        $window.find("#article-pdf").replaceWith(html);
        var tab = $window.find("a[href='#study-full-text']");
        tab.find(".glyphicon").remove();
        if ($window.find(".article-pdf-frame").length) {
          tab.append(' <span class="glyphicon glyphicon-file" title="Has a PDF"></span>');
        }
        loadPdfFrame();
      },
      error: function (xhr) {
        $.parsifal.alert(title, requestError(xhr));
      },
      complete: function () { buttons.prop("disabled", false); }
    });
  }

  $window.on("click", ".js-choose-pdf", function () {
    $window.find(".js-pdf-file").val("").click();
  });

  $window.on("change", ".js-pdf-file", function () {
    if (this.files.length) {
      var data = new FormData();
      data.append("pdf", this.files[0]);
      postPdf('/reviews/conducting/article_pdf/upload/', data, "Could not upload the PDF");
    }
  });

  $window.on("click", ".js-remove-pdf", function () {
    if (confirm("Remove the PDF of this study? The file is deleted.")) {
      postPdf('/reviews/conducting/article_pdf/remove/', new FormData(), "Could not remove the PDF");
    }
  });

  $window.on("hidden.bs.modal", function () {
    $window.find(".modal-body").empty();  // the PDF stops loading
  });
});
