function isScrolledIntoView(elem) {
    const docViewTop = $(window).scrollTop();
    const docViewBottom = docViewTop + $(window).height();

    const elemTop = $(elem).offset().top;
    const elemBottom = elemTop + $(elem).height();

    return ((elemBottom <= docViewBottom) && (elemTop >= docViewTop));
}

$(function () {

  $(".source-tab-content").on("click", ".btn-add-manual", function () {
    var container = $("#modal-add-article .modal-body");
    var review_id = $("#review-id").val();
    var div = $(this).closest(".source-buttons");
    var source_id = $("input[name=source-id]", div).val();
    $.ajax({
      url: '/reviews/conducting/new_article/',
      data: {'review-id': review_id, 'source-id': source_id},
      type: 'get',
      cache: false,
      beforeSend: function () {
        $(container).loading();
      },
      success: function (data) {
        $(container).html(data);
      },
      complete: function () {
        $(container).stopLoading();
      }
    });
    $("#modal-add-article").modal('show');
  });

  /* The study list of the open tab comes a page at a time: what "Show", the search and the star ask for, in the order
     of the heading clicked, is sent to the server, which sends back that page of the list and its pager. */
  function listState(changes) {
    var content = $(".source-tab-content");
    var list = content.find(".js-article-list");
    return $.extend({
      'review-id': $("#review-id").val(),
      'source-id': list.attr("data-source-id"),
      'status': content.find("input[name=filter]:checked").val() || "ALL",
      'q': $.trim(content.find(".js-article-search").val() || ""),
      'starred': content.find(".js-starred-filter").hasClass("active") ? "1" : "",
      'order': list.attr("data-order") || "",
      'page': list.attr("data-page") || 1,
      'part': 'list'
    }, changes || {});
  }

  var listRequest = null;

  /* Loads the list again with ``changes`` (another page, size, order or filter); ``done`` runs once it is shown. */
  function loadList(changes, done) {
    var container = $(".source-tab-content .source-articles");
    if (listRequest) { listRequest.abort(); }
    listRequest = $.ajax({
      url: '/reviews/conducting/source_articles/',
      data: listState(changes),
      type: 'get',
      cache: false,
      beforeSend: function () { container.addClass("list-reloading"); },
      success: function (data) {
        container.html(data);
        updateSelectedArticlesCount();
        if (done) { done(); }
      },
      error: function (xhr, status) {
        if (status !== "abort") {
          $.parsifal.alert("Could not load the studies", requestError(xhr));
        }
      },
      complete: function (xhr, status) {
        if (status !== "abort") {
          listRequest = null;
          container.removeClass("list-reloading");
        }
      }
    });
  }

  $(document).on("studies-changed", function () { loadList(); });  // e.g. an AI run undone

  $(".source-tab-content").on("click", ".js-article-list th[data-order]", function () {
    var key = $(this).attr("data-order");
    var order = $(this).closest(".js-article-list").attr("data-order");
    loadList({'order': order === key ? "-" + key : key, 'page': 1});
  });

  $(".source-tab-content").on("click", ".js-page", function (event) {
    event.preventDefault();
    loadList({'page': $(this).attr("data-page")}, function () {
      $('html, body').animate({scrollTop: $(".source-tab-content").offset().top}, 200);
    });
  });

  $(".source-tab-content").on("change", ".js-per-page", function () {
    loadList({'per-page': $(this).val(), 'page': 1});
  });

  $("#source-tab a").click(function () {
    var source_id = $(this).attr("source-id");
    $("ul#source-tab li").removeClass("active");
    $(this).closest("li").addClass("active");

    $.ajax({
      url: '/reviews/conducting/source_articles/',
      data: { 'review-id': $("#review-id").val(), 'source-id': source_id },
      type: 'get',
      cache: false,
      beforeSend: function () {
        $(".source-tab-content").spinner();
      },
      success: function (data) {
        $(".source-tab-content").html(data);
        updateSelectedArticlesCount();
      },
      complete: function () {
        $(".source-tab-content").spinner();
      }
    });

    return false;
  });

  /* Loads the active row's article, or ``articleId`` (an article that may not be in this tab). */
  $.fn.loadActiveArticle = function (articleId) {
    var article_id = articleId || $(".source-articles tbody tr.active").attr("oid");
    var review_id = $("#review-id").val();
    var container = $(this);

    // Where the study is in the whole list (every page), when this page has it.
    var list = $(".source-tab-content .js-article-list");
    var rows = $(".source-articles tbody tr").not(".no-data");
    var index = rows.index(rows.filter("[oid=" + article_id + "]"));
    $("#modal-article span.current-article").text(index >= 0 ? parseInt(list.attr("data-start"), 10) + index : "–");
    $("#modal-article span.total-articles").text(list.attr("data-count") || rows.length);

    $.ajax({
      url: '/reviews/conducting/article_details/',
      data: {'review-id': review_id, 'article-id': article_id},
      type: 'get',
      cache: false,
      beforeSend: function () {
        $(container).spinner();
        $("#modal-article .article-modal-star").empty();
      },
      success: function (data) {
        $(container).html(data);
        var star = $("#modal-article #article-star-source");
        $("#modal-article .article-modal-star").html(star.html());
        star.remove();
      },
      complete: function () {
        $(container).spinner();
      }
    });
  };

  /* Opens an article in the details window. Its row, when this tab has it, becomes the active one, so that
     Previous/Next go on from there. */
  function openArticle(articleId) {
    $(".source-articles tbody tr").removeClass("active");
    $(".source-articles tbody tr[oid=" + articleId + "]").addClass("active");
    $("#modal-article .modal-body").css("height", $(window).height() * 0.7);
    $("#modal-article .modal-body").loadActiveArticle(articleId);
    $("#modal-article").modal('show');
  }

  $(".source-tab-content").on("click", "tbody tr", function () {
    if (!$(this).hasClass("no-data")) {
      openArticle($(this).attr("oid"));
    }
  });


  /* Reviewers tab inside the article modal: the tab pane is rendered hidden after the form and moved into the
     tab content, so that posting the decision form does not interfere with the article form. */
  $("#modal-article").on("click", "a[href='#tab-reviewers']", function () {
    var source = $("#modal-article #tab-reviewers-source");
    if ($("#modal-article #tab-reviewers").length === 0 && source.length) {
      $("#modal-article .tab-content").append('<div role="tabpanel" class="tab-pane" id="tab-reviewers"></div>');
      $("#modal-article #tab-reviewers").html(source.html());
      source.remove();
    }
  });

  $("#modal-article").on("click", ".btn-record-decision", function () {
    var btn = $(this);
    $.ajax({
      url: '/reviews/conducting/record_decision/',
      type: 'post',
      cache: false,
      data: $("#modal-article #decision-form :input").serialize(),
      beforeSend: function () { btn.prop("disabled", true); },
      success: function (data) {
        $("#modal-article #tab-reviewers").html(data);
      },
      error: function (xhr) {
        $.parsifal.alert("Could not record the decision", requestError(xhr));
      },
      complete: function () { btn.prop("disabled", false); }
    });
  });

  /* The star of a study: one mark per study in the review, shared by every member, and not a status. It is
     toggled from the study list's column or from the study window's title; both are kept in step. */
  function toggleStar(event) {
    event.preventDefault();
    event.stopPropagation();  // a click on the star does not open the study
    var star = $(this);
    var articleId = star.attr("data-article-id");
    $.ajax({
      url: '/reviews/conducting/article_star/',
      type: 'post',
      cache: false,
      data: {
        'review-id': $("#review-id").val(),
        'article-id': articleId,
        'starred': star.hasClass("starred") ? "0" : "1",
        'csrfmiddlewaretoken': $(".source-tab-content table").attr("csrf-token") ||
          $("#article-details [name=csrfmiddlewaretoken]").val()
      },
      success: function (html) {
        var updated = $($.parseHTML($.trim(html))).filter(".js-star");
        $(".js-star[data-article-id=" + articleId + "]").each(function () {
          $(this).replaceWith(updated.clone());
        });
        var row = $(".source-articles tbody tr[oid=" + articleId + "]");
        var wasStarred = star.hasClass("starred");
        row.attr("article-starred", updated.hasClass("starred") ? "1" : "0");
        if (wasStarred !== updated.hasClass("starred")) {
          var count = $(".source-tab-content .starred-count");
          count.text(Math.max(0, parseInt(count.text(), 10) + (wasStarred ? -1 : 1)));
        }
        if (wasStarred && $(".source-tab-content .js-starred-filter").hasClass("active")) {
          loadList();  // only the starred ones are shown: this one leaves the list
        }
      },
      error: function (xhr) {
        $.parsifal.alert("Could not change the star", requestError(xhr));
      }
    });
  }

  $(".source-tab-content").on("click", ".js-star", toggleStar);
  $("#modal-article").on("click", ".js-star", toggleStar);

  $(".source-tab-content").on("click", ".js-starred-filter", function () {
    var button = $(this).toggleClass("active");
    button.attr("aria-pressed", button.hasClass("active") ? "true" : "false");
    loadList({'page': 1});
  });

  /* Full text tab: the PDF is fetched only when the tab is opened, not with every article of Previous/Next. */
  function loadPdfFrame() {
    var frame = $("#modal-article .article-pdf-frame");
    if (frame.length && !frame.attr("src") && $("#modal-article #tab-full-text").hasClass("active")) {
      frame.attr("src", frame.data("src"));
    }
  }

  $("#modal-article").on("shown.bs.tab", "a[href='#tab-full-text']", loadPdfFrame);

  function postPdf(url, data, title) {
    data.append("csrfmiddlewaretoken", $("#article-details [name=csrfmiddlewaretoken]").val());
    data.append("review-id", $("#modal-article #review-id").val());
    data.append("article-id", $("#modal-article #article-id").val());
    var buttons = $("#modal-article #article-pdf button");
    $.ajax({
      url: url,
      type: 'post',
      data: data,
      cache: false,
      contentType: false,
      processData: false,
      beforeSend: function () { buttons.prop("disabled", true); },
      success: function (html) {
        $("#modal-article #article-pdf").replaceWith(html);
        var tab = $("#modal-article a[href='#tab-full-text']");
        tab.find(".glyphicon").remove();
        if ($("#modal-article .article-pdf-frame").length) {
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

  $("#modal-article").on("click", ".js-choose-pdf", function () {
    $("#modal-article .js-pdf-file").val("").click();
  });

  $("#modal-article").on("change", ".js-pdf-file", function () {
    if (this.files.length) {
      var data = new FormData();
      data.append("pdf", this.files[0]);
      postPdf('/reviews/conducting/article_pdf/upload/', data, "Could not upload the PDF");
    }
  });

  $("#modal-article").on("click", ".js-remove-pdf", function () {
    if (confirm("Remove the PDF of this study? The file is deleted.")) {
      postPdf('/reviews/conducting/article_pdf/remove/', new FormData(), "Could not remove the PDF");
    }
  });

  var agreementConsolidated = false;

  /* Short, readable text for a failed AJAX call: plain-text responses (our 400s) are shown as they are, HTML
     error pages are reduced to the status line. */
  function requestError(xhr) {
    var text = xhr.responseText || "";
    if (text && text.indexOf("<") !== 0) {
      return text;
    }
    return "Request failed" + (xhr.status ? " (" + xhr.status + " " + xhr.statusText + ")" : "") + ".";
  }

  /* The agreement panel for a stage and the two reviewers compared (left out: the first two). */
  function loadAgreement(stage, userA, userB) {
    $.ajax({
      url: '/reviews/conducting/agreement/',
      data: {'review-id': $("#review-id").val(), 'stage': stage || '', 'user-a': userA || '', 'user-b': userB || ''},
      type: 'get',
      cache: false,
      beforeSend: function () {
        $("#modal-agreement .modal-body").css("max-height", $(window).height() * 0.7);
        $("#modal-agreement").modal('show');
        $("#modal-agreement .modal-body").loading();
      },
      success: function (data) {
        $("#modal-agreement .modal-body").html(data);
        restoreRule();
      },
      complete: function () {
        $("#modal-agreement .modal-body").stopLoading();
      }
    });
  }

  /* The consolidation rule last used in this review is selected again when the window opens (in this browser). */
  function ruleKey() {
    return "parsifal.consolidateRule." + $("#review-id").val();
  }

  function restoreRule() {
    var select = $("#modal-agreement #consolidate-form select[name=rule]");
    try {
      var rule = window.localStorage.getItem(ruleKey());
      if (rule && select.find("option[value='" + rule + "']").length) {
        select.val(rule);
      }
    } catch (e) { /* storage blocked: keep the default */ }
  }

  function rememberRule(rule) {
    try { window.localStorage.setItem(ruleKey(), rule); } catch (e) { /* storage blocked */ }
  }

  $("#btn-agreement").click(function () { loadAgreement(); });

  $("#modal-agreement").on("change", "#agreement-stage", function () {
    loadAgreement($(this).val());  // another stage may have other reviewers: the first two again
  });

  $("#modal-agreement").on("change", "#agreement-user-a, #agreement-user-b", function () {
    var userA = $("#modal-agreement #agreement-user-a").val();
    var userB = $("#modal-agreement #agreement-user-b").val();
    if (userA === userB) {
      $.parsifal.alert("Choose two reviewers", "Agreement compares two different reviewers.");
      return;
    }
    loadAgreement($("#modal-agreement #agreement-stage").val(), userA, userB);
  });

  $("#modal-agreement").on("click", "#btn-consolidate", function () {
    var btn = $(this);
    var stage = $("#modal-agreement #agreement-stage").val();
    var rule = $("#modal-agreement #consolidate-form select[name=rule]").val();
    var csrf_token = $("#modal-agreement input[name=csrfmiddlewaretoken]").val();
    $.ajax({
      url: '/reviews/conducting/consolidate/',
      type: 'post',
      cache: false,
      data: {
        'review-id': $("#review-id").val(),
        'stage': stage,
        'rule': rule,
        'user-a': $("#modal-agreement #agreement-user-a").val(),
        'user-b': $("#modal-agreement #agreement-user-b").val(),
        'csrfmiddlewaretoken': csrf_token
      },
      beforeSend: function () { btn.prop("disabled", true); },
      success: function (data) {
        agreementConsolidated = true;
        rememberRule(rule);
        $("#modal-agreement .modal-body").html(data);
      },
      error: function (xhr) {
        $.parsifal.alert("Could not consolidate", requestError(xhr));
        btn.prop("disabled", false);
      }
    });
  });

  $("#modal-agreement").on("hidden.bs.modal", function () {
    if (agreementConsolidated) {
      agreementConsolidated = false;
      loadList();
    }
  });

  /* A disagreement opens the article's details, to read it before deciding (the decisions are on its Reviewers
     tab); "Back to agreement" returns to the agreement window at the same stage. */
  var agreementStage = null;

  $("#modal-agreement").on("click", ".js-open-article", function (event) {
    event.preventDefault();
    var articleId = $(this).attr("data-article-id");
    agreementStage = $("#modal-agreement #agreement-stage").val() || "";
    $("#modal-agreement").one("hidden.bs.modal", function () {
      $("#btn-back-to-agreement").show();
      openArticle(articleId);
    }).modal("hide");
  });

  $("#btn-back-to-agreement").click(function () {
    var stage = agreementStage;
    $("#modal-article").one("hidden.bs.modal", function () { loadAgreement(stage); }).modal("hide");
  });

  $("#modal-article").on("hidden.bs.modal", function () {
    $("#btn-back-to-agreement").hide();
    agreementStage = null;
  });

  $("body").keydown(function (event) {
    var keyCode = event.which?event.which:event.keyCode;

    if (keyCode == ESCAPE_KEY) {
      if ($("body").hasClass("modal-open")) {
        $(".modal").modal('hide');
      }
      else {
        $(".source-articles tbody tr").removeClass("active");
      }
    }
    else if (!$("body").hasClass("modal-open") && !$(event.target).is("input[type=search], input[type=text], textarea")) {
      if (keyCode == UP_ARROW_KEY) {
        event.preventDefault();
        move(BACKWARD);
      }
      else if (keyCode == DOWN_ARROW_KEY) {
        event.preventDefault();
        move(FORWARD);
      }
      else if (keyCode == ENTER_KEY) {
       $(".source-articles tbody tr.active").click();
      }
    }
  });

  /* Makes ``row`` the active one, scrolled into sight. */
  function activate(row, step) {
    $(".source-articles tbody tr").removeClass("active");
    row.addClass("active");
    if (row.length && !isScrolledIntoView(row)) {
      if (step > 0)
        $('html, body').animate({scrollTop: $(row).offset().top}, 2000);
      else
        $('html, body').animate({scrollTop: $(row).offset().top - $(window).height()}, 2000);
    }
  }

  /* The next study (``step`` 1) or the previous one (-1) becomes the active one: on this page, or the first of the
     next page (the last of the previous one); past the end of the list, its start again. ``done`` runs when it is. */
  function move(step, done) {
    var rows = $(".source-articles tbody tr").not(".no-data");
    if (rows.length === 0) {
      return;  // nothing on this page
    }
    var index = rows.index(rows.filter(".active"));
    var next = index === -1 ? (step > 0 ? 0 : rows.length - 1) : index + step;
    var list = $(".source-tab-content .js-article-list");
    var page = parseInt(list.attr("data-page"), 10) || 1;
    var pages = parseInt(list.attr("data-pages"), 10) || 1;
    if (next >= 0 && next < rows.length) {
      activate(rows.eq(next), step);
      if (done) { done(); }
    }
    else if (pages <= 1) {
      activate(rows.eq((next + rows.length) % rows.length), step);
      if (done) { done(); }
    }
    else {
      var target = page + step;
      target = target < 1 ? pages : target > pages ? 1 : target;
      loadList({'page': target}, function () {
        var fresh = $(".source-articles tbody tr").not(".no-data");
        activate(step > 0 ? fresh.first() : fresh.last(), step);
        if (done) { done(); }
      });
    }
  }

  function loadActive() {
    $("#modal-article .modal-body").loadActiveArticle();
  }

  $("#btn-previous").click(function () {
    move(BACKWARD, loadActive);
  });

  $("#btn-next").click(function () {
    move(FORWARD, loadActive);
  });

  function save_article(move_next) {
    var article_id = $("#modal-article #article-id").val();
    $.ajax({
      url: '/reviews/conducting/save_article_details/',
      cache: false,
      // The study's fields only: the Reviewers tab, once opened, sits inside this form with the decision's own.
      data: $("#article-details :input").not("#tab-reviewers :input").serialize(),
      type: 'post',
      beforeSend: function () {
        $(".btn-save-article").prop("disabled", true);
      },
      success: function (data) {
        $(".source-articles table tbody tr[oid=" + article_id + "]").replaceWith(data);
        $(".source-articles table tbody tr[oid=" + article_id + "]").addClass("active");
        if (move_next) {
          move(FORWARD, loadActive);
        }
        else {
          $("#modal-article .alert .modal-alert").text("Article successfully saved!");
          $("#modal-article .alert").removeClass("alert-error").addClass("alert-success");
          $("#modal-article .alert").removeClass("hide");
        }
      },
      error: function () {
          $("#modal-article .alert .modal-alert").text("Something went wrong! That's all we know :(");
          $("#modal-article .alert").removeClass("alert-success").addClass("alert-error");
          $("#modal-article .alert").removeClass("hide");
      },
      complete: function () {
        $(".btn-save-article").prop("disabled", false);
      }
    });
  }

  $(".btn-save-article").click(function () {
    save_article(false);
  });

  $("#modal-article").on("click", "ul.tab a", function () {
    var tab_id = $(this).attr("href");
    $("#modal-article div.tabs form > div").hide();
    $("#modal-article ul.tab li").removeClass("active");
    $(this).closest("li").addClass("active");
    $(tab_id).show();
    return false;
  });

  $("#modal-article").on("change", "#status", function () {
    if ($("#save-and-move-next").is(":checked")) {
      save_article(true);
    }
  });

  /* "Show", the search (title, DOI or BibTeX key) and the star filter the whole list, on the server: the list comes
     again from its first page, with nothing selected. */
  $(".source-tab-content").on("click", "input[name=filter]", function () {
    loadList({'page': 1});
  });

  var searchTimer = null;
  $(".source-tab-content").on("input", ".js-article-search", function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () { loadList({'page': 1}); }, 300);
  });

  $(".source-tab-content").on("click", "table tbody tr td input[type=checkbox]", function (event) {
    event.stopPropagation();
  });

  $(".source-tab-content").on("click", "#ck-all-articles", function () {
    $(".source-tab-content table tbody tr td input[type=checkbox]").prop("checked", false);
    if ($(this).is(":checked")) {
      $(".source-tab-content table tbody tr:visible td input[type=checkbox]").prop("checked", true);
    }
    updateSelectedArticlesCount();
  });

  /* Every study of the list (every page, as filtered), as in the library: offered once the whole page is checked. */
  var selectingMatching = false;

  function showMatchingMessage() {
    var list = $(".source-tab-content .js-article-list");
    var whole = $("#ck-all-articles").is(":checked");
    if (!whole) { selectingMatching = false; }
    $(".js-message-select-matching", list).toggle(whole && !selectingMatching);
    $(".js-message-matching-selected", list).toggle(whole && selectingMatching);
  }

  $(".source-tab-content").on("click", ".js-select-matching", function () {
    selectingMatching = true;
    showMatchingMessage();
  });

  $(".source-tab-content").on("click", ".js-clear-matching", function () {
    selectingMatching = false;
    $("#ck-all-articles").prop("checked", false);
    $(".source-tab-content table tbody tr td input[type=checkbox]").prop("checked", false);
    updateSelectedArticlesCount();
  });

  function multiple_articles_actions(article_ids, action) {
    var review_id = $("#review-id").val();
    var csrf_token = $(".source-tab-content table").attr("csrf-token");
    var data = {
      'review-id': review_id,
      'article_ids': article_ids,
      'csrfmiddlewaretoken': csrf_token
    };
    var matching = selectingMatching;
    if (matching) {
      var state = listState();
      $.extend(data, {
        'select-all': 'filter',
        'source-id': state['source-id'],
        'status': state['status'],
        'q': state['q'],
        'starred': state['starred']
      });
    }

    $.ajax({
      url: '/reviews/conducting/multiple_articles_action/' + action + '/',
      data: data,
      type: 'post',
      cache: false,
      beforeSend: function () {
        $(".go-button").prop("disabled", true);
        $(".go-button").text("Processing...");
      },
      success: function (data) {
        if (matching) {
          loadList();  // studies of other pages changed too
          return;
        }
        switch (action) {
          case "remove":
            loadList();  // the studies after them move up into this page
            break;
          case "unclassify":
            $(".source-articles table tbody input[type=checkbox]:checked").each(function () {
              var row = $(this).closest("tr");
              $(row).attr("article-status", "U");
              $("td.js-status", row).html("<span class='label label-default'>Unclassified</span>");
            });
            break;
          case "accept":
            $(".source-articles table tbody input[type=checkbox]:checked").each(function () {
              var row = $(this).closest("tr");
              $(row).attr("article-status", "A");
              $("td.js-status", row).html("<span class='label label-success'>Accepted</span>");
            });
            break;
          case "reject":
            $(".source-articles table tbody input[type=checkbox]:checked").each(function () {
              var row = $(this).closest("tr");
              $(row).attr("article-status", "R");
              $("td.js-status", row).html("<span class='label label-danger'>Rejected</span>");
            });
            break;
          case "duplicated":
            $(".source-articles table tbody input[type=checkbox]:checked").each(function () {
              var row = $(this).closest("tr");
              $(row).attr("article-status", "D");
              $("td.js-status", row).html("<span class='label label-warning'>Duplicated</span>");
            });
            break;
        }
      },
      error: function () {

      },
      complete: function () {
        $(".go-button").prop("disabled", false);
        $(".go-button").text("Go");
        updateSelectedArticlesCount();
      }
    });
  }

  $(".source-tab-content").on("click", ".go-button", function () {
    var article_ids = '';
    var action = $(".source-tab-content .select-action").val();
    if (action) {
      $(".source-articles table tbody input[type=checkbox]:checked").each(function () {
        article_ids += $(this).val() + "|";
      });
      if (article_ids) {
        article_ids = article_ids.substring(0, article_ids.length - 1);
        switch (action) {
          case "remove":
            multiple_articles_actions(article_ids, action);
            break;
          case "unclassify":
            multiple_articles_actions(article_ids, action);
            break;
          case "accept":
            multiple_articles_actions(article_ids, action);
            break;
          case "reject":
            multiple_articles_actions(article_ids, action);
            break;
          case "duplicated":
            multiple_articles_actions(article_ids, action);
            break;
        }
      }
    }
  });

  $(".source-tab-content").on("click", "table tbody tr td input[type=checkbox]", function () {
    var total = $(".source-articles table tbody tr td input[type='checkbox']:visible").length;
    var checked = $(".source-articles table tbody tr td input[type='checkbox']:checked").length;
    if (checked === total) {
      $("#ck-all-articles").prop("checked", true);
    }
    else {
      $("#ck-all-articles").prop("checked", false);
    }
    updateSelectedArticlesCount();
  });

  $(".source-tab-content").on("click", "table tbody tr td:first-child", function (e) {
    e.stopPropagation();
    $("input[type='checkbox']", this).click();
    return false;
  });

  var updateSelectedArticlesCount = function () {
    var total = $(".source-articles table tbody tr td input[type='checkbox']:visible").length;
    var checked = $(".source-articles table tbody tr td input[type='checkbox']:checked").length;
    $(".articles-selected").text(checked);
    $(".articles-total").text(total);
    showMatchingMessage();
  };

  $(".source-tab-content").on("click", ".btn-find-duplicates", function () {
    $.ajax({
      url: '/reviews/conducting/find_duplicates/',
      data: {'review-id': $("#review-id").val()},
      type: 'get',
      cache: false,
      beforeSend: function () {
        $("#modal-duplicates .modal-body").css("max-height", $(window).height() * 0.7);
        $("#modal-duplicates").modal('show');
        $("#modal-duplicates .modal-body").loading();
      },
      success: function (data) {
        $("#modal-duplicates .modal-body").html(data);
      },
      complete: function () {
        $("#modal-duplicates .modal-body").stopLoading();
      }
    });
  });

  $("#modal-duplicates").on("click", ".btn-resolve", function () {
    var row = $(this).closest("tr");
    var btn = $(this);
    var review_id = $("#review-id").val();
    var article_id = $(row).attr("article-id");
    var duplicate = $(row).attr("duplicate");
    var csrf_token = $("#modal-duplicates input[name=csrfmiddlewaretoken]").val();
    $.ajax({
      url: '/reviews/conducting/resolve_duplicated/',
      data: {
        'review-id': review_id,
        'article-id': article_id,
        'csrfmiddlewaretoken': csrf_token
      },
      type: 'post',
      cache: false,
      beforeSend: function () {
        $(btn).prop("disabled", true);
        $(btn).text("Resolving...");
      },
      success: function (data) {
        $("td.js-status", row).html("<span class='label label-warning'>Duplicated</span>");
        $(btn).text("Resolved");
        $(row).attr("resolved", "true");
        var duplicates = $("#modal-duplicates .modal-body tr[duplicate=" + duplicate + "]");
        var duplicates_resolved = $("#modal-duplicates .modal-body tr[duplicate=" + duplicate + "][resolved=true]");

        if (duplicates.length - duplicates_resolved.length === 1) {
          var btn_resolved = $("#modal-duplicates .modal-body tr[duplicate=" + duplicate + "][resolved=false] button");
          $(btn_resolved).text("Resolved");
          $(btn_resolved).prop("disabled", true);
        }

        var article_row = $(".source-tab-content .source-articles tr[oid=" + article_id + "]");
        $(article_row).attr("article-status", "D");
        $("td.js-status", article_row).html("<span class=\"label label-warning\">Duplicated</span>");
      },
      error: function () {
        $(btn).prop("disabled", false);
        $(btn).text("Resolve");
      }
    });
  });

  $("#btn-resolve-all").click(function () {
    var review_id = $("#review-id").val();
    var csrf_token = $("#modal-duplicates input[name=csrfmiddlewaretoken]").val();
    var btn = $(this);
    $.ajax({
      url: '/reviews/conducting/resolve_all/',
      data: {
        'review-id': review_id,
        'csrfmiddlewaretoken': csrf_token
      },
      type: 'post',
      cache: false,
      beforeSend: function () {
        $(btn).prop("disabled", true);
        $(btn).text("Resolving...");
      },
      success: function (data) {
        if (data !== "") {
          var btn_modal = $("#modal-duplicates table tbody tr td button");
          $(btn_modal).prop("disabled", true);
          $(btn_modal).text("Resolved");
          var ids = data.split(",");
          for (var i = ids.length - 1; i >= 0; i--) {
            var article_row = $(".source-tab-content .source-articles tr[oid=" + ids[i] + "]");
            $(article_row).attr("article-status", "D");
            $("td.js-status", article_row).html("<span class=\"label label-warning\">Duplicated</span>");
          }
          }
      },
      complete: function () {
        $(btn).prop("disabled", false);
        $(btn).text("Resolve All");
      }
    });
  });

  // On page load

  if ($("ul#source-tab li").length > 0) {
    if($("ul#source-tab li.active").length === 0) {
      $("ul#source-tab li:eq(0)").addClass("active");
    }
    $("#source-tab li.active a").click();
  }


  /* Columns of the study list: check the ones to show, order them with the arrows, save; the list reloads. */
  var $columns = $("#modal-columns");

  $columns.on("click", ".js-column-move", function () {
    var item = $(this).closest("li");
    if ($(this).data("step") < 0) { item.prev().before(item); } else { item.next().after(item); }
  });

  $columns.on("click", ".js-columns-default", function () {
    var defaults = JSON.parse($("#study-columns-default").text());
    var list = $columns.find(".js-study-columns");
    var items = list.children("li").detach();
    defaults.forEach(function (key) {
      list.append(items.filter("[data-key='" + key + "']").find("input").prop("checked", true).end());
    });
    items.filter(function () { return defaults.indexOf($(this).data("key")) === -1; }).each(function () {
      list.append($(this).find("input").prop("checked", false).end());
    });
  });

  $columns.on("click", ".js-columns-save", function () {
    var btn = $(this).prop("disabled", true);
    var chosen = $columns.find(".js-study-columns li").filter(function () {
      return $(this).find("input").prop("checked");
    }).map(function () { return $(this).data("key"); }).get();
    $.ajax({
      url: '/reviews/conducting/save_study_columns/',
      type: 'post',
      traditional: true,
      data: {
        'review-id': $("#review-id").val(),
        'columns': chosen,
        'csrfmiddlewaretoken': $(".source-tab-content table").attr("csrf-token") || $("input[name=csrfmiddlewaretoken]").first().val()
      },
      success: function () {
        $columns.find(".js-columns-error").hide();
        $columns.modal("hide");
        $("#source-tab li.active a").click();  // the list again, with these columns
      },
      error: function (xhr) {
        var message = xhr.responseJSON && xhr.responseJSON.error ? xhr.responseJSON.error : "Could not save the columns.";
        $columns.find(".js-columns-error").text(message).show();
      },
      complete: function () { btn.prop("disabled", false); }
    });
  });
});
