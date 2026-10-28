/* The PRISMA 2020 flow diagram of Data Analysis (Study Selection), drawn as SVG from the numbers of
   analytics.prisma (#analysis-prisma-data), with the boxes and wording of the PRISMA 2020 template; downloaded as
   SVG or PNG. Choosing the "not retrieved" criterion saves it and draws the diagram again. */
$(function () {

  var container = document.getElementById("analysis-prisma");
  if (!container) {
    return;
  }
  var data = JSON.parse(document.getElementById("analysis-prisma-data").textContent);

  var SVG = "http://www.w3.org/2000/svg";
  var FONT = "'Helvetica Neue', Helvetica, Arial, sans-serif";
  var BOX = 300, GAP = 50, ROW_GAP = 28, LINE = 17, PAD = 10, LABEL = 30, CHARS = 42;
  var INCLUDED_HEIGHT = 80;  // room for the "Included" label beside it
  var COLORS = {
    border: "#333333",
    text: "#333333",
    header: "#f5f5f5",
    phase: "#d9edf7",
    phaseText: "#31708f",
    arrow: "#555555",
    note: "#777777"
  };

  function n(value) {
    return "(n = " + value + ")";
  }

  /* The lines of a box: items are {text, indent} (indent: a line under a heading); long texts are wrapped. */
  function wrap(items) {
    var lines = [];
    $.each(items, function (_, item) {
      var width = CHARS - (item.indent ? 3 : 0);
      var line = "";
      $.each(String(item.text).split(" "), function (_, word) {
        if (line && (line + " " + word).length > width) {
          lines.push({text: line, indent: item.indent});
          line = word;
        }
        else {
          line = line ? line + " " + word : word;
        }
      });
      lines.push({text: line, indent: item.indent});
    });
    return lines;
  }

  function element(name, attributes, parent) {
    var node = document.createElementNS(SVG, name);
    $.each(attributes, function (key, value) { node.setAttribute(key, value); });
    if (parent) { parent.appendChild(node); }
    return node;
  }

  function text(parent, x, y, content, attributes) {
    var node = element("text", $.extend({x: x, y: y, "font-family": FONT, "font-size": 13, fill: COLORS.text}, attributes || {}), parent);
    node.textContent = content;
    return node;
  }

  function boxHeight(items) {
    var height = wrap(items).length * LINE + 2 * PAD;
    return items === included ? Math.max(height, INCLUDED_HEIGHT) : height;
  }

  var included = null;  // the box of the studies included

  function box(svg, x, y, items, height, fill) {
    element("rect", {x: x, y: y, width: BOX, height: height, fill: fill || "#ffffff", stroke: COLORS.border, "stroke-width": 1}, svg);
    $.each(wrap(items), function (index, line) {
      text(svg, x + PAD + (line.indent ? 14 : 0), y + PAD + LINE * index + 13, line.text);
    });
  }

  function arrow(svg, points) {
    element("polyline", {
      points: $.map(points, function (point) { return point.join(","); }).join(" "),
      fill: "none", stroke: COLORS.arrow, "stroke-width": 1.5, "marker-end": "url(#prisma-arrow)"
    }, svg);
  }

  /* "Reports excluded:" with one line per reason, or "(n = 0)" when there is none. */
  function excludedReports(rows) {
    if (!rows.length) {
      return [{text: "Reports excluded " + n(0)}];
    }
    return [{text: "Reports excluded:"}].concat($.map(rows, function (row) {
      return {text: row.reason + " " + n(row.studies), indent: true};
    }));
  }

  /* The boxes of each row (a: databases and registers, b: their side boxes; c and d: other methods). */
  function rows() {
    var other = data.other_methods;
    var identified = [{text: "Records identified from:"}, {text: "Databases and registers " + n(data.records)}];
    $.each(data.databases, function (_, row) { identified.push({text: row.source + " " + n(row.records), indent: true}); });
    var excluded = [{text: "Records excluded " + n(data.excluded)}];
    if (data.excluded_by_automation) {
      excluded.push({text: "by people " + n(data.excluded_by_people), indent: true});
      excluded.push({text: "by automation tools " + n(data.excluded_by_automation), indent: true});
    }
    var showNotRetrieved = data.not_retrieved_criteria_id !== null;
    var result = [
      {
        a: identified,
        b: [{text: "Records removed before screening:"}, {text: "Duplicate records removed " + n(data.duplicates), indent: true}],
        c: other ? [{text: "Records identified from:"}].concat($.map(other.methods, function (row) {
          return {text: row.method + " " + n(row.records), indent: true};
        })) : null
      },
      {a: [{text: "Records screened " + n(data.screened)}], b: excluded},
      {
        a: [{text: "Reports sought for retrieval " + n(data.sought)}],
        b: showNotRetrieved ? [{text: "Reports not retrieved " + n(data.not_retrieved)}] : null,
        c: other ? [{text: "Reports sought for retrieval " + n(other.sought)}] : null,
        d: other && showNotRetrieved ? [{text: "Reports not retrieved " + n(other.not_retrieved)}] : null
      },
      {
        a: [{text: "Reports assessed for eligibility " + n(data.assessed)}],
        b: excludedReports(data.excluded_reports),
        c: other ? [{text: "Reports assessed for eligibility " + n(other.assessed)}] : null,
        d: other ? excludedReports(other.excluded_reports) : null
      },
      {a: [{text: "Studies included in review " + n(data.included)}, {text: "Reports of included studies " + n(data.included)}]}
    ];
    included = result[4].a;
    return result;
  }

  function draw() {
    var other = data.other_methods;
    var x = {a: LABEL + 14};
    x.b = x.a + BOX + GAP;
    x.c = x.b + BOX + GAP * 1.5;
    x.d = x.c + BOX + GAP;
    var width = (other ? x.d : x.b) + BOX + 2;
    var boxes = rows();

    var svg = element("svg", {xmlns: SVG, version: "1.1"});
    var defs = element("defs", {}, svg);
    var marker = element("marker", {id: "prisma-arrow", viewBox: "0 0 10 10", refX: 10, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto"}, defs);
    element("path", {d: "M0,0 L10,5 L0,10 z", fill: COLORS.arrow}, marker);
    element("rect", {x: 0, y: 0, width: "100%", height: "100%", fill: "#ffffff"}, svg);

    // Headers of the columns
    var header = 40;
    element("rect", {x: x.a, y: 0, width: x.b + BOX - x.a, height: header, fill: COLORS.header, stroke: COLORS.border}, svg);
    text(svg, (x.a + x.b + BOX) / 2, 25, "Identification of studies via databases and registers", {"text-anchor": "middle", "font-weight": "bold"});
    if (other) {
      element("rect", {x: x.c, y: 0, width: x.d + BOX - x.c, height: header, fill: COLORS.header, stroke: COLORS.border}, svg);
      text(svg, (x.c + x.d + BOX) / 2, 25, "Identification of studies via other methods", {"text-anchor": "middle", "font-weight": "bold"});
    }

    // Rows: the tallest box sets each row's height
    var top = header + ROW_GAP, tops = [], heights = [];
    $.each(boxes, function (index, row) {
      var height = 0;
      $.each(["a", "b", "c", "d"], function (_, key) {
        if (row[key]) { height = Math.max(height, boxHeight(row[key])); }
      });
      tops.push(top);
      heights.push(height);
      $.each(["a", "b", "c", "d"], function (_, key) {
        if (row[key]) { box(svg, x[key], top, row[key], boxHeight(row[key])); }
      });
      top += height + ROW_GAP;
    });

    // Arrows: down the databases column, to the side boxes, down the other methods column into the included box
    function bottom(index, key) { return tops[index] + boxHeight(boxes[index][key]); }
    for (var index = 0; index < boxes.length - 1; index++) {
      arrow(svg, [[x.a + BOX / 2, bottom(index, "a")], [x.a + BOX / 2, tops[index + 1]]]);
    }
    $.each(boxes, function (index, row) {
      $.each([["a", "b"], ["c", "d"]], function (_, pair) {
        if (row[pair[0]] && row[pair[1]]) {
          var y = tops[index] + Math.min(boxHeight(row[pair[0]]), boxHeight(row[pair[1]])) / 2;
          arrow(svg, [[x[pair[0]] + BOX, y], [x[pair[1]], y]]);
        }
      });
    });
    if (other) {
      arrow(svg, [[x.c + BOX / 2, bottom(0, "c")], [x.c + BOX / 2, tops[2]]]);
      arrow(svg, [[x.c + BOX / 2, bottom(2, "c")], [x.c + BOX / 2, tops[3]]]);
      var included = tops[4] + boxHeight(boxes[4].a) / 2;
      arrow(svg, [[x.c + BOX / 2, bottom(3, "c")], [x.c + BOX / 2, included], [x.a + BOX, included]]);
    }

    // Phases, on the left
    $.each([["Identification", 0, 0], ["Screening", 1, 3], ["Included", 4, 4]], function (_, phase) {
      var y = tops[phase[1]], height = tops[phase[2]] + heights[phase[2]] - y;
      element("rect", {x: 0, y: y, width: LABEL, height: height, rx: 4, fill: COLORS.phase, stroke: COLORS.phaseText, "stroke-width": 0.5}, svg);
      text(svg, LABEL / 2 + 5, y + height / 2, phase[0], {
        "text-anchor": "middle", "font-weight": "bold", fill: COLORS.phaseText,
        transform: "rotate(-90 " + (LABEL / 2 + 5) + " " + (y + height / 2) + ")"
      });
    });

    // Note, as in the template
    var note = top + 4;
    text(svg, x.a, note, "Based on the PRISMA 2020 flow diagram (Page et al., BMJ 2021;372:n71). Records excluded: by", {"font-size": 11, fill: COLORS.note});
    text(svg, x.a, note + 14, "automation tools when only AI agents rejected them at the screening.", {"font-size": 11, fill: COLORS.note});
    var height = note + 24;

    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    $(container).empty().append(svg);

    var awaiting = [];
    if (data.awaiting_screening) {
      awaiting.push(data.awaiting_screening + " stud" + (data.awaiting_screening === 1 ? "y is" : "ies are") + " still unclassified");
    }
    if (data.awaiting_full_text) {
      awaiting.push(data.awaiting_full_text + " accepted at the screening " + (data.awaiting_full_text === 1 ? "has" : "have") +
        " no full-text decision yet (Reviewers tab of the study)");
    }
    $(".js-prisma-awaiting").text(awaiting.length ? "Not final: " + awaiting.join("; ") + "." : "").toggle(awaiting.length > 0);
  }

  function download(blob, name) {
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = name;
    document.body.appendChild(link);
    link.click();
    setTimeout(function () { URL.revokeObjectURL(link.href); link.remove(); }, 0);
  }

  $(".js-prisma-download").click(function () {
    var svg = container.querySelector("svg");
    var source = new XMLSerializer().serializeToString(svg);
    if ($(this).attr("data-format") === "svg") {
      download(new Blob([source], {type: "image/svg+xml"}), "prisma-flow-diagram.svg");
      return;
    }
    var image = new Image(), scale = 2;
    image.onload = function () {
      var canvas = document.createElement("canvas");
      canvas.width = svg.width.baseVal.value * scale;
      canvas.height = svg.height.baseVal.value * scale;
      var context = canvas.getContext("2d");
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(function (blob) { download(blob, "prisma-flow-diagram.png"); }, "image/png");
    };
    image.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(source);
  });

  $(".js-prisma-not-retrieved").change(function () {
    var select = $(this).prop("disabled", true);
    $.ajax({
      url: "/reviews/conducting/save_prisma_settings/",
      type: "post",
      data: {
        "review-id": $("#review-id").val(),
        "not-retrieved-criteria-id": select.val(),
        "csrfmiddlewaretoken": $(".prisma-settings [name=csrfmiddlewaretoken]").val()
      },
      success: function (numbers) {
        data = numbers;
        draw();
      },
      error: function (xhr) {
        $.parsifal.alert("Could not save the criterion", $.parsifal.requestError(xhr));
      },
      complete: function () { select.prop("disabled", false); }
    });
  });

  draw();
});
