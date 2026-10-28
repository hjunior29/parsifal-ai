/* Google Charts is loaded once for the whole page: its loader refuses a second load, which left the charts drawn
   after it empty. When it is ready, "charts-ready" draws the charts below the first three. */
$(function () {
    google.charts.load('current', {'packages': ['corechart']});
    google.charts.setOnLoadCallback(drawChartCallback);

    function drawChartCallback() {
      if (document.getElementById('articles-selection-pie')) {  // the Study Selection section
        drawChart();
        drawYearLines();
      }
      $(document).trigger("charts-ready");
    }

    function drawPieChart(rows) {
      var data = new google.visualization.DataTable();
      data.addColumn('string', 'Source');
      data.addColumn('number', 'Number of Articles');
      data.addRows(rows);
      var options = {'height': 400};
      var chart = new google.visualization.PieChart(document.getElementById('articles-selection-pie'));
      chart.draw(data, $.parsifal.chartOptions(options));
    }

    function drawColumnChart(rows) {
      var data = google.visualization.arrayToDataTable(rows);
      var options = {
        vAxis: {title: 'Number of Articles',  titleTextStyle: {color: '#3A3D40'}},
        'height': 400
      };
      var chart = new google.visualization.ColumnChart(document.getElementById('articles-selection-column'));
      chart.draw(data, $.parsifal.chartOptions(options));
    }

    function drawLineChart(rows) {
      var data = google.visualization.arrayToDataTable(rows);
      var options = {
        vAxis: {title: 'Number of Articles',  titleTextStyle: {color: '#3A3D40'}},
        'height': 400
      };
      var chart = new google.visualization.LineChart(document.getElementById('articles-selection-line'));
      chart.draw(data, $.parsifal.chartOptions(options));
    }

    function drawChart() {
      $.ajax({
        url: '/reviews/conducting/articles_selection_chart/',
        data: {'review-id': $("#review-id").val()},
        type: 'get',
        cache: false,
        beforeSend: function () {
          $("#articles-selection-pie").spinner(false);
          $("#articles-selection-column").spinner(false);
        },
        success: function (data) {
          var source_data = data.split(",");
          var rows_pie = [];
          var rows_chart = [['Source', 'Selected', 'Accepted']];
          for (var i = source_data.length - 1; i >= 0; i--) {
            row = source_data[i].split(":");
            rows_pie.push([row[0], parseInt(row[1])]);
            rows_chart.push([row[0], parseInt(row[1]), parseInt(row[2])]);
          }
          drawPieChart(rows_pie);
          drawColumnChart(rows_chart);
        },
        complete: function () {
          $("#articles-selection-pie").spinner();
          $("#articles-selection-column").spinner();
        }
      });
    }

    function drawYearLines() {
      $.ajax({
        url: '/reviews/conducting/articles_per_year/',
        data: {'review-id': $("#review-id").val()},
        type: 'get',
        cache: false,
        beforeSend: function () {
          $("#articles-selection-line").spinner(false);
        },
        success: function (data) {
          var source_data = data.split(",");
          var rows = [['Year', 'Number of Articles']];
          for (var i = source_data.length - 1; i >= 0; i--) {
            row = source_data[i].split(":");
            rows.push([row[0], parseInt(row[1])]);
          }
          drawLineChart(rows);
        },
        complete: function () {
          $("#articles-selection-line").spinner();
        }
      });
    }
});

/* The charts below the first three and the funnel of the selection: the statuses per source, the criteria most used
   and the studies per year. Their data come with the page (json_script). */
$(function () {
  var COLORS = {accepted: "#5cb85c", rejected: "#d9534f", unclassified: "#999999", duplicated: "#f0ad4e"};
  // Pixels under a horizontal bar chart for the axis numbers and its title: left to Google Charts, a short chart (one
  // or two bars) drops the numbers.
  var AXIS_ROOM = 70;
  // The funnel's stages: the totals in the blue of the charts above, the rest in the statuses' colors.
  var STAGE_COLORS = {
    imported: "#3366cc", duplicated: COLORS.duplicated, unique: "#3366cc", rejected: COLORS.rejected,
    unclassified: COLORS.unclassified, accepted: COLORS.accepted, final: COLORS.accepted,
    // Quality Assessment and Data Extraction in numbers
    studies: "#3366cc", assessed: COLORS.accepted, partly: COLORS.duplicated, not_assessed: COLORS.unclassified,
    above: COLORS.accepted, at_most: COLORS.rejected, selected: "#3366cc", done: COLORS.accepted,
    todo: COLORS.unclassified
  };

  /* A funnel of bars (each stage's count, and its share of the stage it comes from); also the numbers of Quality
     Assessment and Data Extraction. */
  function funnel(stages, elementId) {
    var element = document.getElementById(elementId || "analysis-funnel");
    if (!element || !stages.length || !stages[0].count) { return; }
    var data = new google.visualization.DataTable();
    data.addColumn("string", "Stage");
    data.addColumn("number", "Number of Articles");
    data.addColumn({type: "string", role: "style"});
    data.addColumn({type: "string", role: "annotation"});
    data.addColumn({type: "string", role: "tooltip"});
    stages.forEach(function (stage) {
      var share = stage.of && stage.share !== null ? stage.share + "% " + stage.of : "";
      data.addRow([
        stage.label,
        stage.count,
        STAGE_COLORS[stage.key],
        stage.count + (stage.of && stage.share !== null ? " · " + stage.share + "%" : ""),
        stage.label.replace("− ", "") + ": " + stage.count + (share ? " (" + share + ")" : "")
      ]);
    });
    new google.visualization.BarChart(element).draw(data, $.parsifal.chartOptions({
      height: elementId ? Math.max(220, 55 * stages.length + 90) : 400,
      legend: {position: "none"},
      hAxis: {title: "Number of Articles", titleTextStyle: {color: "#3A3D40"}, minValue: 0},
      annotations: {alwaysOutside: true}
    }));
  }

  function data(id) {
    var node = document.getElementById(id);
    return node ? JSON.parse(node.textContent) : null;
  }

  function stacked(elementId, rows, statuses) {
    var element = document.getElementById(elementId);
    if (!element || rows.length < 2) { return; }
    var chart = new google.visualization.ColumnChart(element);
    chart.draw(google.visualization.arrayToDataTable(rows), $.parsifal.chartOptions({
      height: 400,
      isStacked: true,
      colors: statuses.map(function (status) { return COLORS[status]; }),
      vAxis: {title: "Number of Articles", titleTextStyle: {color: "#3A3D40"}},
      legend: {position: "top"}
    }));
  }

  function ranking(elementId, criteria, color) {
    var element = document.getElementById(elementId);
    if (!element || !criteria.length) { return; }
    var rows = [["Criterion", "Studies"]];
    criteria.forEach(function (criterion) {
      var description = criterion.description.length > 70 ? criterion.description.slice(0, 67) + "…" : criterion.description;
      rows.push([criterion.key + " — " + description, criterion.studies]);
    });
    var chart = new google.visualization.BarChart(element);
    chart.draw(google.visualization.arrayToDataTable(rows), $.parsifal.chartOptions({
      height: Math.max(170, 40 * criteria.length + 100),
      colors: [color],
      legend: {position: "none"},
      chartArea: {left: "45%", width: "50%", top: 20, bottom: AXIS_ROOM},
      hAxis: {title: "Number of Articles", minValue: 0, format: "0"}
    }));
  }

  function draw() {
    var summary = data("analysis-summary");
    var criteria = data("analysis-criteria");
    var years = data("analysis-years-data");
    if (!summary) { return; }

    var statuses = ["accepted", "rejected", "unclassified", "duplicated"];
    funnel(data("analysis-funnel-data") || []);

    var sources = [["Source", "Accepted", "Rejected", "Unclassified", "Duplicated"]];
    summary.by_source.forEach(function (row) {
      sources.push([row.source, row.accepted, row.rejected, row.unclassified, row.duplicated]);
    });
    stacked("analysis-sources", sources, statuses);

    ranking("analysis-exclusion", criteria.exclusion, COLORS.rejected);
    ranking("analysis-inclusion", criteria.inclusion, COLORS.accepted);

    var perYear = [["Year", "Accepted", "Rejected", "Unclassified"]];
    years.forEach(function (row) {
      perYear.push([row.year === null ? "Unknown" : String(row.year), row.accepted, row.rejected, row.unclassified]);
    });
    stacked("analysis-years", perYear, ["accepted", "rejected", "unclassified"]);
  }

  $(document).on("charts-ready", draw);
  $(document).on("draw-stages", function (event, stages) { funnel(stages, "analysis-stages"); });
});

/* The Quality Assessment and Data Extraction sections: their numbers, the scores, the answers to each question, and
   how often each option of the choice fields was chosen. Their data come with the page (json_script). */
$(function () {
  var BLUE = "#3366cc";
  var GRAY = "#999999";
  var AXIS_ROOM = 70;  // as above

  function data(id) {
    var node = document.getElementById(id);
    return node ? JSON.parse(node.textContent) : null;
  }

  function shortLabel(text, size) {
    return text.length > size ? text.slice(0, size - 3) + "…" : text;
  }

  function percent(part, whole) {
    return whole ? Math.round(100 * part / whole) + "%" : "";
  }

  /* The answers' colors, from the highest weight to the lowest: green to red when there are two or three. */
  function answerColors(count) {
    if (count === 2) { return ["#5cb85c", "#d9534f"]; }
    if (count === 3) { return ["#5cb85c", "#f0ad4e", "#d9534f"]; }
    return null;  // Google's own, in order
  }

  function scores(quality) {
    var element = document.getElementById("analysis-scores");
    if (!element || !quality.scores.length) { return; }
    var rows = [["Score", "Number of Articles"]];
    quality.scores.forEach(function (row) { rows.push([String(row.score), row.studies]); });
    new google.visualization.ColumnChart(element).draw(google.visualization.arrayToDataTable(rows), $.parsifal.chartOptions({
      height: 400,
      colors: [BLUE],
      legend: {position: "none"},
      hAxis: {title: "Score"},
      vAxis: {title: "Number of Articles", titleTextStyle: {color: "#3A3D40"}, minValue: 0, format: "0"}
    }));
  }

  function questions(quality) {
    var element = document.getElementById("analysis-questions");
    if (!element || !quality.by_question.length) { return; }
    var header = ["Question"];
    quality.answers.forEach(function (answer) { header.push(answer.description); });
    header.push("No answer");
    var rows = [header];
    quality.by_question.forEach(function (question) {
      var row = [question.key + " — " + shortLabel(question.description, 70)];
      question.answers.forEach(function (answer) { row.push(answer.studies); });
      row.push(question.unanswered);
      rows.push(row);
    });
    var colors = answerColors(quality.answers.length);
    var options = {
      height: Math.max(200, 50 * quality.by_question.length + 120),
      isStacked: true,
      legend: {position: "top"},
      chartArea: {left: "45%", width: "50%", top: 50, bottom: AXIS_ROOM},
      hAxis: {title: "Number of Articles", minValue: 0, format: "0"}
    };
    if (colors) { options.colors = colors.concat([GRAY]); }
    new google.visualization.BarChart(element).draw(google.visualization.arrayToDataTable(rows), $.parsifal.chartOptions(options));
  }

  /* One chart per choice field: each option's studies, the most chosen first, with its share of the studies that
     answered (a multiple choice field's shares may add up to more than 100%). */
  function field(field) {
    var element = document.getElementById("analysis-field-" + field.id);
    if (!element) { return; }
    var table = new google.visualization.DataTable();
    table.addColumn("string", "Option");
    table.addColumn("number", "Number of Articles");
    table.addColumn({type: "string", role: "annotation"});
    table.addColumn({type: "string", role: "tooltip"});
    field.options.forEach(function (option) {
      var share = percent(option.studies, field.answered);
      table.addRow([
        shortLabel(option.value, 60),
        option.studies,
        option.studies + (share ? " · " + share : ""),
        option.value + ": " + option.studies + (share ? " (" + share + " of the " + field.answered + " that answered)" : "")
      ]);
    });
    new google.visualization.BarChart(element).draw(table, $.parsifal.chartOptions({
      height: Math.max(170, 40 * field.options.length + 100),
      colors: [BLUE],
      legend: {position: "none"},
      chartArea: {left: "35%", width: "55%", top: 20, bottom: AXIS_ROOM},
      hAxis: {title: "Number of Articles", minValue: 0, format: "0"},
      annotations: {alwaysOutside: true}
    }));
  }

  function draw() {
    var quality = data("analysis-quality");
    var extraction = data("analysis-extraction");
    if (!quality && !extraction) { return; }
    $(document).trigger("draw-stages", [data("analysis-stages-data") || []]);
    if (quality) {
      scores(quality);
      questions(quality);
    }
    if (extraction) {
      extraction.fields.forEach(field);
    }
  }

  $(document).on("charts-ready", draw);
});
