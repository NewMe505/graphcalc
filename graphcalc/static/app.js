(function () {
  "use strict";

  var buttons = document.querySelectorAll(".tab-button");
  var panels = document.querySelectorAll(".tab-panel");

  function showTab(tabId) {
    panels.forEach(function (panel) {
      panel.classList.toggle("active", panel.id === tabId);
    });
    buttons.forEach(function (button) {
      button.classList.toggle("active", button.dataset.tab === tabId);
    });
  }

  buttons.forEach(function (button) {
    button.addEventListener("click", function () {
      showTab(button.dataset.tab);
    });
  });

  showTab("tab-calculator");

  // ---- Calculator tab: wired to /api/calc/evaluate, /api/calc/history and
  // /api/calc/vars (plan step P8). The page only draws what the API
  // returns -- no client-side math, ever.
  var CALC_EVALUATE_PATH = "/api/calc/evaluate";
  var CALC_HISTORY_PATH = "/api/calc/history";
  var CALC_VARS_PATH = "/api/calc/vars";

  var calcInput = document.getElementById("calc-input");
  var calcMode = document.getElementById("calc-mode");
  var calcSubmit = document.getElementById("calc-submit");
  var calcHistory = document.getElementById("calc-history");
  var calcVars = document.getElementById("calc-vars");
  var calcError = document.getElementById("calc-error");

  function calcShowError(message) {
    calcError.textContent = message || "";
  }

  function calcFormatResult(entry) {
    if (entry.domain_error) {
      return entry.domain_error;
    }
    if (entry.complex) {
      return entry.exact + " = " + entry.complex.real + " + " + entry.complex.imag + "i";
    }
    if (entry.decimal && entry.decimal !== entry.exact) {
      return entry.exact + " = " + entry.decimal;
    }
    return entry.exact;
  }

  function calcRenderHistory(history) {
    calcHistory.innerHTML = "";
    history.forEach(function (entry) {
      var item = document.createElement("li");
      item.textContent = entry.expr + " => " + calcFormatResult(entry);
      calcHistory.appendChild(item);
    });
  }

  function calcRenderVars(data) {
    calcVars.innerHTML = "";
    var variables = data.variables || {};
    var functions = data.functions || {};
    Object.keys(variables).forEach(function (name) {
      var dt = document.createElement("dt");
      dt.textContent = name;
      var dd = document.createElement("dd");
      dd.textContent = variables[name];
      calcVars.appendChild(dt);
      calcVars.appendChild(dd);
    });
    Object.keys(functions).forEach(function (name) {
      var spec = functions[name];
      var dt = document.createElement("dt");
      dt.textContent = name + "(" + spec.params.join(", ") + ")";
      var dd = document.createElement("dd");
      dd.textContent = spec.body;
      calcVars.appendChild(dt);
      calcVars.appendChild(dd);
    });
  }

  function calcRefreshHistory() {
    fetch(CALC_HISTORY_PATH)
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        calcRenderHistory(data.history || []);
      });
  }

  function calcRefreshVars() {
    fetch(CALC_VARS_PATH)
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        calcRenderVars(data);
      });
  }

  function calcSubmitExpression() {
    calcShowError("");
    fetch(CALC_EVALUATE_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expr: calcInput.value, mode: calcMode.value }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          calcShowError(result.data.error || "error");
          return;
        }
        if (result.data.domain_error) {
          calcShowError(result.data.domain_error);
        }
        calcRefreshHistory();
        calcRefreshVars();
      })
      .catch(function (err) {
        calcShowError(String(err));
      });
  }

  if (calcSubmit) {
    calcSubmit.addEventListener("click", calcSubmitExpression);
    calcInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        calcSubmitExpression();
      }
    });
    calcRefreshHistory();
    calcRefreshVars();
  }

  // ---- Graphs tab: wired to /api/graph/plot, /api/graph/window,
  // /api/graph/analyze and /api/graph/table (plan step P14/S2). Same as the
  // Calculator tab above, the page only draws what the API returns -- no
  // client-side math, ever.
  var GRAPH_PLOT_PATH = "/api/graph/plot";
  var GRAPH_WINDOW_PATH = "/api/graph/window";
  var GRAPH_ANALYZE_PATH = "/api/graph/analyze";
  var GRAPH_TABLE_PATH = "/api/graph/table";

  var GRAPH_SLOTS = ["f1", "f2", "f3", "f4"];
  var GRAPH_ZOOM_FACTOR = 2;
  var GRAPH_PAN_FRACTION = 0.25;
  var GRAPH_TABLE_ROWS = 21;

  var graphInputs = GRAPH_SLOTS.map(function (slot) {
    return document.getElementById("graph-" + slot);
  });
  var graphXmin = document.getElementById("graph-xmin");
  var graphXmax = document.getElementById("graph-xmax");
  var graphYmin = document.getElementById("graph-ymin");
  var graphYmax = document.getElementById("graph-ymax");
  var graphWindowInputs = [graphXmin, graphXmax, graphYmin, graphYmax];
  var graphZoomIn = document.getElementById("graph-zoom-in");
  var graphZoomOut = document.getElementById("graph-zoom-out");
  var graphPanLeft = document.getElementById("graph-pan-left");
  var graphPanRight = document.getElementById("graph-pan-right");
  var graphPanUp = document.getElementById("graph-pan-up");
  var graphPanDown = document.getElementById("graph-pan-down");
  var graphTraceX = document.getElementById("graph-trace-x");
  var graphAnalyzeButton = document.getElementById("graph-analyze");
  var graphCanvas = document.getElementById("graph-canvas");
  var graphTable = document.getElementById("graph-table");

  if (graphCanvas) {
    var graphCtx = graphCanvas.getContext("2d");

    // A plain, unlabeled status line for an analyze result or a 400 JSON
    // error from any of the four graph endpoints. Created here, not in
    // index.html, because this step only touches app.js; it inherits the
    // page's global overflow-wrap/word-break rule (style.css, plan step
    // P33), so a long result or error message wraps instead of widening
    // the page, the same as calc-error already does.
    var graphStatus = document.createElement("p");
    if (graphAnalyzeButton && graphAnalyzeButton.parentNode) {
      graphAnalyzeButton.parentNode.appendChild(graphStatus);
    }

    function graphShowStatus(message) {
      graphStatus.textContent = message || "";
    }

    function graphReadFunctions() {
      var functions = {};
      GRAPH_SLOTS.forEach(function (slot, index) {
        var value = graphInputs[index].value;
        if (value) {
          functions[slot] = value;
        }
      });
      return functions;
    }

    function graphFirstFunction() {
      for (var i = 0; i < graphInputs.length; i++) {
        if (graphInputs[i].value) {
          return graphInputs[i].value;
        }
      }
      return null;
    }

    function graphReadWindow() {
      return {
        xmin: parseFloat(graphXmin.value),
        xmax: parseFloat(graphXmax.value),
        ymin: parseFloat(graphYmin.value),
        ymax: parseFloat(graphYmax.value),
      };
    }

    function graphApplyWindow(win) {
      graphXmin.value = win.xmin;
      graphXmax.value = win.xmax;
      graphYmin.value = win.ymin;
      graphYmax.value = win.ymax;
    }

    function graphToPixel(win, x, y) {
      var px = ((x - win.xmin) / (win.xmax - win.xmin)) * graphCanvas.width;
      var py =
        graphCanvas.height -
        ((y - win.ymin) / (win.ymax - win.ymin)) * graphCanvas.height;
      return [px, py];
    }

    function graphDrawAxes(win) {
      graphCtx.strokeStyle = "#999999";
      graphCtx.lineWidth = 1;
      if (win.ymin <= 0 && win.ymax >= 0) {
        var xAxis = graphToPixel(win, 0, 0);
        graphCtx.beginPath();
        graphCtx.moveTo(0, xAxis[1]);
        graphCtx.lineTo(graphCanvas.width, xAxis[1]);
        graphCtx.stroke();
      }
      if (win.xmin <= 0 && win.xmax >= 0) {
        var yAxis = graphToPixel(win, 0, 0);
        graphCtx.beginPath();
        graphCtx.moveTo(yAxis[0], 0);
        graphCtx.lineTo(yAxis[0], graphCanvas.height);
        graphCtx.stroke();
      }
    }

    // P34-BEGIN
    // Bug #40: a vertical asymptote (e.g. "1/x" at x=0) falls *between* two
    // sampled x-values -- plot() (P10) only ever returns null for a sample
    // exactly on the pole, so both neighbouring samples come back as huge
    // but finite floats, one on each side. Without this check,
    // graphDrawSeries below joins them with a near-vertical lineTo, drawing
    // a line across the gap that visually welds the two branches together.
    // A jump between two consecutive samples is treated as an asymptote --
    // never part of the curve -- only when both samples are finite numbers,
    // they swing from positive to negative (or back), and the swing is
    // more than twice the window's own height (ymax - ymin). A steep but
    // continuous curve such as "10*x" never swings by more than a small
    // fraction of the window between two adjacent canvas-width samples, so
    // it is never broken by this check (see NOTES.md for the one case this
    // heuristic does not cover: an even steeper continuous line).
    function graphIsAsymptoteJump(y0, y1, ymin, ymax) {
      if (
        typeof y0 !== "number" ||
        typeof y1 !== "number" ||
        !isFinite(y0) ||
        !isFinite(y1)
      ) {
        return false;
      }
      if (!(y0 * y1 < 0)) {
        return false;
      }
      return Math.abs(y1 - y0) > 2 * (ymax - ymin);
    }
    // P34-END

    // Draws each returned series on graph-canvas, mapping the window to
    // pixels and breaking the path wherever "y" is null -- a gap in the
    // domain (plan step P10's own series shape) must stay a gap, never a
    // straight line drawn across it -- and also wherever two consecutive
    // finite samples jump across a vertical asymptote (bug #40, P34).
    function graphDrawSeries(win, xs, series) {
      Object.keys(series).forEach(function (name) {
        var entry = series[name];
        var ys = entry.y || [];
        graphCtx.strokeStyle = entry.color || "#000000";
        graphCtx.lineWidth = 2;
        graphCtx.beginPath();
        var drawing = false;
        var prevY = null;
        xs.forEach(function (x, index) {
          var y = ys[index];
          if (y === null || y === undefined) {
            drawing = false;
            prevY = null;
            return;
          }
          var point = graphToPixel(win, x, y);
          if (drawing && !graphIsAsymptoteJump(prevY, y, win.ymin, win.ymax)) {
            graphCtx.lineTo(point[0], point[1]);
          } else {
            graphCtx.moveTo(point[0], point[1]);
            drawing = true;
          }
          prevY = y;
        });
        graphCtx.stroke();
      });
    }

    function graphRenderPlot(win, data) {
      graphCtx.clearRect(0, 0, graphCanvas.width, graphCanvas.height);
      graphDrawAxes(win);
      graphDrawSeries(win, data.x || [], data.series || {});
    }

    function graphRenderTable(data) {
      graphTable.innerHTML = "";
      var columnNames = Object.keys(data.columns || {});
      var headerRow = document.createElement("tr");
      var xHeader = document.createElement("th");
      xHeader.textContent = "x";
      headerRow.appendChild(xHeader);
      columnNames.forEach(function (name) {
        var th = document.createElement("th");
        th.textContent = name;
        headerRow.appendChild(th);
      });
      graphTable.appendChild(headerRow);

      (data.x || []).forEach(function (xValue, index) {
        var row = document.createElement("tr");
        var xCell = document.createElement("td");
        xCell.textContent = xValue;
        row.appendChild(xCell);
        columnNames.forEach(function (name) {
          var cell = document.createElement("td");
          var value = data.columns[name][index];
          cell.textContent = value === null || value === undefined ? "" : value;
          row.appendChild(cell);
        });
        graphTable.appendChild(row);
      });
    }

    // The table action (P13): POSTs to /api/graph/table for the same
    // functions and window the canvas just plotted, evenly spaced across
    // the current window, and renders the rows into graph-table.
    function graphRefreshTable(functions, win) {
      if (Object.keys(functions).length === 0) {
        graphTable.innerHTML = "";
        return;
      }
      var step = (win.xmax - win.xmin) / (GRAPH_TABLE_ROWS - 1);
      if (!isFinite(step) || step === 0) {
        return;
      }
      fetch(GRAPH_TABLE_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          functions: functions,
          start: win.xmin,
          step: step,
          rows: GRAPH_TABLE_ROWS,
        }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            graphShowStatus(result.data.error || "error");
            return;
          }
          graphRenderTable(result.data);
        })
        .catch(function (err) {
          graphShowStatus(String(err));
        });
    }

    // Reads graph-f1..f4 and the window inputs, then POSTs to plot.
    function graphPlot() {
      var functions = graphReadFunctions();
      var win = graphReadWindow();
      if (Object.keys(functions).length === 0) {
        graphCtx.clearRect(0, 0, graphCanvas.width, graphCanvas.height);
        graphDrawAxes(win);
        graphTable.innerHTML = "";
        return;
      }
      fetch(GRAPH_PLOT_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          functions: functions,
          window: win,
          samples: Math.max(2, graphCanvas.width),
        }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            graphShowStatus(result.data.error || "error");
            return;
          }
          graphShowStatus("");
          graphRenderPlot(win, result.data);
          graphRefreshTable(functions, win);
        })
        .catch(function (err) {
          graphShowStatus(String(err));
        });
    }

    // Zoom and pan buttons POST to window, update the window inputs from
    // the response, then replot.
    function graphWindowAction(extra) {
      var body = { window: graphReadWindow() };
      Object.keys(extra).forEach(function (key) {
        body[key] = extra[key];
      });
      fetch(GRAPH_WINDOW_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            graphShowStatus(result.data.error || "error");
            return;
          }
          graphApplyWindow(result.data);
          graphPlot();
        })
        .catch(function (err) {
          graphShowStatus(String(err));
        });
    }

    function graphPan(dxFactor, dyFactor) {
      var win = graphReadWindow();
      graphWindowAction({
        action: "pan",
        dx: (win.xmax - win.xmin) * GRAPH_PAN_FRACTION * dxFactor,
        dy: (win.ymax - win.ymin) * GRAPH_PAN_FRACTION * dyFactor,
      });
    }

    // The graph-analyze button POSTs to analyze using the trace-x value and
    // the first non-empty function, and shows the result as text.
    function graphAnalyze() {
      var expr = graphFirstFunction();
      if (!expr) {
        graphShowStatus("no function to analyze");
        return;
      }
      fetch(GRAPH_ANALYZE_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation: "value",
          f: expr,
          x: parseFloat(graphTraceX.value),
        }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            graphShowStatus(result.data.error || "error");
            return;
          }
          var data = result.data;
          if (data.domain_error) {
            graphShowStatus(data.domain_error);
          } else {
            graphShowStatus("x = " + data.x + ", y = " + data.y);
          }
        })
        .catch(function (err) {
          graphShowStatus(String(err));
        });
    }

    graphInputs.concat(graphWindowInputs).forEach(function (input) {
      input.addEventListener("change", graphPlot);
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          graphPlot();
        }
      });
    });

    graphZoomIn.addEventListener("click", function () {
      graphWindowAction({ action: "zoom_in", factor: GRAPH_ZOOM_FACTOR });
    });
    graphZoomOut.addEventListener("click", function () {
      graphWindowAction({ action: "zoom_out", factor: GRAPH_ZOOM_FACTOR });
    });
    graphPanLeft.addEventListener("click", function () {
      graphPan(-1, 0);
    });
    graphPanRight.addEventListener("click", function () {
      graphPan(1, 0);
    });
    graphPanUp.addEventListener("click", function () {
      graphPan(0, 1);
    });
    graphPanDown.addEventListener("click", function () {
      graphPan(0, -1);
    });
    graphAnalyzeButton.addEventListener("click", graphAnalyze);

    // Seed the window inputs from the server's own "standard" window
    // (rather than hard-coding -10..10 here) and draw the initial (empty)
    // plot -- consistent with "the page only draws what the API returns."
    graphWindowAction({ action: "standard" });
  }

  // ---- Lists & Statistics tab: wired to /api/lists, /api/stats/onevar and
  // /api/stats/regression (plan steps P18/S2 and P18/S3). Same as the
  // Calculator and Graphs tabs above, the page only draws what the API
  // returns -- no client-side math, ever: the regression fit itself (the
  // coefficients, r2, "points" and "curve") always comes from the
  // /api/stats/regression response, never computed here.
  var LISTS_PATH = "/api/lists";
  var STATS_ONEVAR_PATH = "/api/stats/onevar";
  var STATS_REGRESSION_PATH = "/api/stats/regression";

  var listsTabButton = document.querySelector('.tab-button[data-tab="tab-lists"]');
  var listGrid = document.getElementById("list-grid");
  var statsList = document.getElementById("stats-list");
  var statsOutput = document.getElementById("stats-output");
  var regressionModel = document.getElementById("regression-model");
  var regressionX = document.getElementById("regression-x");
  var regressionY = document.getElementById("regression-y");
  var regressionRunButton = document.getElementById("regression-run");
  var regressionOutput = document.getElementById("regression-output");
  var statsCanvas = document.getElementById("stats-canvas");

  if (listGrid && statsList && statsOutput) {
    // Lists fetched by loadLists() below, keyed by name, so regressionRun()
    // can read a chosen list's own values without a second round trip --
    // regression-x/regression-y only ever offer names loadLists() just
    // filled them with.
    var listsByName = {};

    var statsCtx = statsCanvas ? statsCanvas.getContext("2d") : null;

    function listsShowStatsError(message) {
      statsOutput.textContent = message || "";
    }

    // Same {"exact","decimal"} formatting rule calcFormatResult above
    // already applies to a /api/calc/evaluate entry: "decimal" is shown
    // alongside "exact" only when they actually differ, so an integer
    // result such as mean=3 (exact "3", decimal "3") shows plainly as "3",
    // never "3 = 3" or a raw "3.0". A plain (non-{exact,decimal}) value
    // such as "n" is just stringified.
    function statsFormatValue(value) {
      if (value && typeof value === "object" && "exact" in value) {
        if (value.decimal && value.decimal !== value.exact) {
          return value.exact + " = " + value.decimal;
        }
        return value.exact;
      }
      return String(value);
    }

    function listsRenderGrid(lists) {
      listGrid.innerHTML = "";
      lists.forEach(function (entry) {
        var block = document.createElement("div");
        var heading = document.createElement("h3");
        heading.textContent = entry.name;
        block.appendChild(heading);
        var valueList = document.createElement("ul");
        (entry.values || []).forEach(function (value) {
          var item = document.createElement("li");
          item.textContent = value;
          valueList.appendChild(item);
        });
        block.appendChild(valueList);
        listGrid.appendChild(block);
      });
    }

    // Rebuilds a <select>'s options from the current list names, keeping
    // whatever name was already chosen selected when it still exists.
    // loadLists() runs both on DOMContentLoaded and on every tab-lists
    // click (below), so a second, slower-to-resolve call can refill
    // regression-x/regression-y (or stats-list) after the user (or a test)
    // already picked a value from the first call's options; without this,
    // that refill would silently reset the picked value back to whichever
    // name sorts first, same as any plain select.innerHTML = "" rebuild.
    function listsFillSelect(select, lists) {
      if (!select) {
        return;
      }
      var previous = select.value;
      select.innerHTML = "";
      var kept = false;
      lists.forEach(function (entry) {
        var option = document.createElement("option");
        option.value = entry.name;
        option.textContent = entry.name;
        select.appendChild(option);
        if (entry.name === previous) {
          kept = true;
        }
      });
      if (kept) {
        select.value = previous;
      }
    }

    // GET /api/lists only returns names (plan step P15/S1) -- each list's
    // own values come from a separate GET /api/lists/<name>, fetched in
    // parallel so list-grid, stats-list, regression-x and regression-y all
    // render/fill once, not one list at a time.
    function loadLists() {
      return fetch(LISTS_PATH)
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          var names = data.lists || [];
          return Promise.all(
            names.map(function (name) {
              return fetch(LISTS_PATH + "/" + encodeURIComponent(name)).then(function (res) {
                return res.json();
              });
            })
          );
        })
        .then(function (lists) {
          listsRenderGrid(lists);
          listsFillSelect(statsList, lists);
          listsFillSelect(regressionX, lists);
          listsFillSelect(regressionY, lists);
          listsByName = {};
          lists.forEach(function (entry) {
            listsByName[entry.name] = entry;
          });
        });
    }

    function statsRenderOutput(data) {
      statsOutput.innerHTML = "";
      var dl = document.createElement("dl");
      Object.keys(data).forEach(function (key) {
        var dt = document.createElement("dt");
        dt.textContent = key;
        var dd = document.createElement("dd");
        dd.textContent = statsFormatValue(data[key]);
        dl.appendChild(dt);
        dl.appendChild(dd);
      });
      statsOutput.appendChild(dl);
    }

    // The stats-list dropdown's change handler: POSTs the chosen list to
    // /api/stats/onevar and renders the returned statistics verbatim, or
    // the JSON error message from a 400 (e.g. an empty list), into
    // stats-output.
    function statsRefreshOnevar() {
      var name = statsList.value;
      if (!name) {
        statsOutput.innerHTML = "";
        return;
      }
      fetch(STATS_ONEVAR_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ list: name }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            listsShowStatsError(result.data.error || "error");
            return;
          }
          statsRenderOutput(result.data);
        })
        .catch(function (err) {
          listsShowStatsError(String(err));
        });
    }

    statsList.addEventListener("change", statsRefreshOnevar);

    // Renders /api/stats/regression's own "model", "coefficients" and "r2"
    // into regression-output as plain "key = value" lines -- e.g. "a = 2"
    // and "b = 0" -- rather than the <dt>/<dd> pairs statsRenderOutput uses
    // above, so each coefficient reads as a single run of text rather than
    // being split across two elements. statsFormatValue is reused for the
    // normalised-number formatting rule even though this endpoint's own
    // coefficients/r2 are already plain decimal strings (never the
    // {"exact","decimal"} shape onevar returns): it just stringifies them
    // unchanged, so sharing it costs nothing and keeps one formatting rule
    // for the whole tab.
    function statsRenderRegression(data) {
      regressionOutput.innerHTML = "";
      var lines = [];
      if ("model" in data) {
        lines.push("model = " + statsFormatValue(data.model));
      }
      var coefficients = data.coefficients || {};
      Object.keys(coefficients).forEach(function (key) {
        lines.push(key + " = " + statsFormatValue(coefficients[key]));
      });
      if ("r2" in data) {
        lines.push("r2 = " + statsFormatValue(data.r2));
      }
      lines.forEach(function (line) {
        var p = document.createElement("p");
        p.textContent = line;
        regressionOutput.appendChild(p);
      });
    }

    // ---- stats-canvas drawing helpers: a local mirror of the Graphs tab's
    // graphToPixel/graphDrawAxes/graphDrawSeries above, kept separate (not
    // shared) since this block draws a fixed set of data points plus one
    // fitted curve from the regression response, not an arbitrary number of
    // sampled function series.

    function statsToPixel(win, x, y) {
      var px = ((x - win.xmin) / (win.xmax - win.xmin)) * statsCanvas.width;
      var py =
        statsCanvas.height -
        ((y - win.ymin) / (win.ymax - win.ymin)) * statsCanvas.height;
      return [px, py];
    }

    function statsDrawAxes(win) {
      statsCtx.strokeStyle = "#999999";
      statsCtx.lineWidth = 1;
      if (win.ymin <= 0 && win.ymax >= 0) {
        var xAxis = statsToPixel(win, 0, 0);
        statsCtx.beginPath();
        statsCtx.moveTo(0, xAxis[1]);
        statsCtx.lineTo(statsCanvas.width, xAxis[1]);
        statsCtx.stroke();
      }
      if (win.xmin <= 0 && win.xmax >= 0) {
        var yAxis = statsToPixel(win, 0, 0);
        statsCtx.beginPath();
        statsCtx.moveTo(yAxis[0], 0);
        statsCtx.lineTo(yAxis[0], statsCanvas.height);
        statsCtx.stroke();
      }
    }

    // Draws the regression's own "points" ([[x, y], ...] string pairs, in
    // the request's input order) as small filled dots.
    function statsDrawPoints(win, points) {
      statsCtx.fillStyle = "#1a73e8";
      points.forEach(function (pair) {
        var point = statsToPixel(win, parseFloat(pair[0]), parseFloat(pair[1]));
        statsCtx.beginPath();
        statsCtx.arc(point[0], point[1], 4, 0, 2 * Math.PI);
        statsCtx.fill();
      });
    }

    // Draws the regression's own "curve" (50 [x, y] pairs spanning
    // min(x)..max(x), already in x order) as a single connected line -- the
    // fitted curve itself, never recomputed here.
    function statsDrawCurve(win, curve) {
      statsCtx.strokeStyle = "#d93025";
      statsCtx.lineWidth = 2;
      statsCtx.beginPath();
      curve.forEach(function (pair, index) {
        var point = statsToPixel(win, parseFloat(pair[0]), parseFloat(pair[1]));
        if (index === 0) {
          statsCtx.moveTo(point[0], point[1]);
        } else {
          statsCtx.lineTo(point[0], point[1]);
        }
      });
      statsCtx.stroke();
    }

    // Sizes the window to the data itself -- the min/max of every x and y
    // value across both "points" and "curve" -- with a 10% margin on each
    // side so a point never lands exactly on the canvas edge. Falls back to
    // a 1-unit margin when every x (or every y) is equal, which "points"
    // alone could do even though a real regression's own x range cannot
    // (regression() already rejects fewer than two distinct x values).
    function statsComputeWindow(points, curve) {
      var xs = [];
      var ys = [];
      points.concat(curve).forEach(function (pair) {
        xs.push(parseFloat(pair[0]));
        ys.push(parseFloat(pair[1]));
      });
      var xmin = Math.min.apply(null, xs);
      var xmax = Math.max.apply(null, xs);
      var ymin = Math.min.apply(null, ys);
      var ymax = Math.max.apply(null, ys);
      var xPad = (xmax - xmin) * 0.1 || 1;
      var yPad = (ymax - ymin) * 0.1 || 1;
      return {
        xmin: xmin - xPad,
        xmax: xmax + xPad,
        ymin: ymin - yPad,
        ymax: ymax + yPad,
      };
    }

    function statsRenderRegressionPlot(data) {
      statsCtx.clearRect(0, 0, statsCanvas.width, statsCanvas.height);
      var points = data.points || [];
      var curve = data.curve || [];
      var win = statsComputeWindow(points, curve);
      statsDrawAxes(win);
      statsDrawCurve(win, curve);
      statsDrawPoints(win, points);
    }

    // The regression-run button: POSTs the chosen model and the chosen
    // x/y lists' own values (never list names -- /api/stats/regression
    // takes the raw value arrays, the same shape PUT /api/lists/<name>
    // takes) to /api/stats/regression, then renders the coefficients and
    // draws the fit -- both straight from the response.
    function regressionRun() {
      var xEntry = listsByName[regressionX.value];
      var yEntry = listsByName[regressionY.value];
      if (!xEntry || !yEntry) {
        regressionOutput.textContent = "choose an x list and a y list";
        return;
      }
      fetch(STATS_REGRESSION_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: regressionModel.value,
          x: xEntry.values,
          y: yEntry.values,
        }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            regressionOutput.textContent = result.data.error || "error";
            return;
          }
          statsRenderRegression(result.data);
          if (statsCtx) {
            statsRenderRegressionPlot(result.data);
          }
        })
        .catch(function (err) {
          regressionOutput.textContent = String(err);
        });
    }

    if (regressionRunButton) {
      regressionRunButton.addEventListener("click", regressionRun);
    }

    document.addEventListener("DOMContentLoaded", loadLists);
    if (listsTabButton) {
      listsTabButton.addEventListener("click", loadLists);
    }
  }

  // ---- CAS tab: wired to /api/cas/simplify, /expand, /factor, /derivative,
  // /integral, /limit and /solve (plan step P22/S2). Same as the
  // Calculator, Graphs and Lists & Statistics tabs above, the page only
  // draws what the API returns -- no client-side math, ever.
  var CAS_SIMPLIFY_PATH = "/api/cas/simplify";
  var CAS_EXPAND_PATH = "/api/cas/expand";
  var CAS_FACTOR_PATH = "/api/cas/factor";
  var CAS_DERIVATIVE_PATH = "/api/cas/derivative";
  var CAS_INTEGRAL_PATH = "/api/cas/integral";
  var CAS_LIMIT_PATH = "/api/cas/limit";
  var CAS_SOLVE_PATH = "/api/cas/solve";

  var casInput = document.getElementById("cas-input");
  var casVar = document.getElementById("cas-var");
  var casOp = document.getElementById("cas-op");
  var casSubmit = document.getElementById("cas-submit");
  var casOutput = document.getElementById("cas-output");

  if (casSubmit) {
    // Maps cas-op's own <option> values to each op's endpoint path.
    var CAS_OP_PATHS = {
      simplify: CAS_SIMPLIFY_PATH,
      expand: CAS_EXPAND_PATH,
      factor: CAS_FACTOR_PATH,
      derivative: CAS_DERIVATIVE_PATH,
      integral: CAS_INTEGRAL_PATH,
      limit: CAS_LIMIT_PATH,
      solve: CAS_SOLVE_PATH,
    };

    function casShowOutput(message) {
      casOutput.textContent = message || "";
    }

    // Error path (plan step P22/S3): cas-output gets an "error" class so a
    // 400's message is visually distinguishable from a plain result, same
    // textContent-based rendering either way so P33's wrap rule still
    // applies. Always paired with casClearOutput() at the start of the next
    // submit, so an error never lingers once a later submit's result (or a
    // later error) is ready to replace it.
    function casShowError(message) {
      casOutput.textContent = message;
      casOutput.classList.add("error");
    }

    function casClearOutput() {
      casOutput.textContent = "";
      casOutput.classList.remove("error");
    }

    // Builds the right POST body for the chosen op: {"expr"} for
    // simplify/expand/factor, {"expr","var"} for derivative/integral/limit,
    // and {"equation","var"} for solve -- the field names confirmed against
    // graphcalc/cli.py's own _handle_cas_* handlers (cli.py:899-1170).
    function casBuildPayload(op) {
      if (op === "solve") {
        return { equation: casInput.value, var: casVar.value };
      }
      if (op === "derivative" || op === "integral" || op === "limit") {
        return { expr: casInput.value, var: casVar.value };
      }
      return { expr: casInput.value };
    }

    // Reads cas-op, POSTs the matching payload to that op's own endpoint,
    // and writes the response's "result" (or, for solve, its "solutions"
    // list joined by ", ") into cas-output -- or, on a 400, "Error: " plus
    // that response's own "error" message, with an "error" class so it
    // reads as a failure, not a result (plan step P22/S3). cas-output is
    // cleared (text and "error" class both) at the very start of every
    // submit, so the previous submit's result or error never lingers once a
    // new one is in flight, and the next submit's own outcome -- success or
    // failure -- always fully replaces it (the same "last submit wins" rule
    // every other tab's own status/error element already follows).
    function casSubmitExpression() {
      var op = casOp.value;
      var path = CAS_OP_PATHS[op];
      casClearOutput();
      fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(casBuildPayload(op)),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            casShowError("Error: " + (result.data.error || "error"));
            return;
          }
          if (op === "solve") {
            casShowOutput((result.data.solutions || []).join(", "));
          } else {
            casShowOutput(result.data.result);
          }
        })
        .catch(function () {
          // A network failure (server unreachable) or a parse failure
          // (res.json() rejecting on a non-JSON body) both land here --
          // never the raw error object/text, since the point is a stable,
          // generic message a user can act on either way.
          casShowError("Error: request failed");
        });
    }

    casSubmit.addEventListener("click", casSubmitExpression);
    casInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        casSubmitExpression();
      }
    });
  }
})();
