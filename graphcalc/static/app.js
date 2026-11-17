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

    // Draws each returned series on graph-canvas, mapping the window to
    // pixels and breaking the path wherever "y" is null -- a gap in the
    // domain (plan step P10's own series shape) must stay a gap, never a
    // straight line drawn across it.
    function graphDrawSeries(win, xs, series) {
      Object.keys(series).forEach(function (name) {
        var entry = series[name];
        var ys = entry.y || [];
        graphCtx.strokeStyle = entry.color || "#000000";
        graphCtx.lineWidth = 2;
        graphCtx.beginPath();
        var drawing = false;
        xs.forEach(function (x, index) {
          var y = ys[index];
          if (y === null || y === undefined) {
            drawing = false;
            return;
          }
          var point = graphToPixel(win, x, y);
          if (drawing) {
            graphCtx.lineTo(point[0], point[1]);
          } else {
            graphCtx.moveTo(point[0], point[1]);
            drawing = true;
          }
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
})();
