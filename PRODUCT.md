# GraphCalc: a local CAS graphing calculator in the browser

Package: `graphcalc` · Stack: `python` (toolchain profile)

## Vision
A local graphing calculator inspired by the TI-Nspire CX CAS. A Python HTTP server bound to 127.0.0.1 does all the math through a JSON API with one endpoint per operation, using sympy. It also serves one plain HTML/CSS/JS page with four tabs: Calculator, Graphs, Lists & Statistics, and CAS. The page only draws what the API returns. Every result can be checked over HTTP. A client mistake gets a 400 with a JSON error and never a 500. State is kept on disk, so it survives a restart.

## Users
- Students who want a free graphing calculator with CAS on their own computer
- Teachers who check exact and decimal results while preparing lessons
- Developers who want to script or test the math through the HTTP API

## Features (build order; each criterion is a black-box test)
### P1: The package starts, reports its version, serves a health check on 127.0.0.1, and has one passing unittest smoke test.
- [ ] `python -m graphcalc --version` prints `graphcalc 0.1.0` and exits 0
- [ ] `python -m graphcalc --port {port} --in-memory` serves GET /health with 200 and body {"status":"ok"}
- [ ] The server binds only to 127.0.0.1, and an unknown path answers 404 with a JSON body that has an "error" key

### P2: GET / serves one HTML page with four tabs (Calculator, Graphs, Lists & Statistics, CAS) plus plain CSS and JS files, with no external resources and no build step.
- [ ] GET / returns 200 text/html with elements whose ids are tab-calculator, tab-graphs, tab-lists and tab-cas, and a canvas with id graph-canvas
- [ ] GET /static/app.js returns 200 application/javascript and GET /static/style.css returns 200 text/css
- [ ] The page references no http(s) URL outside 127.0.0.1, and a path traversal like /static/../server.py returns 404

### P3: POST /api/calc/evaluate takes {"expr":str,"mode":"rad"|"deg" (optional)} and answers {"expr","exact","decimal","complex","domain_error"} (complex and domain_error are null unless set). It parses + - * / ^, parentheses and implied multiplication. Decimals are strings with 12 significant digits and no trailing zeros.
- [ ] {"expr":"1/3+1/6"} returns 200 with exact "1/2" and decimal "0.5"
- [ ] {"expr":"2(3+1)^2"} returns exact "32"; {"expr":"1/3"} returns decimal "0.333333333333"
- [ ] {"expr":"2+*3"} returns 400 with {"error":<message>}; a body with no expr returns 400 with error "missing parameter: expr"

### P4: Supports sin, cos, tan, asin, acos, atan, ln, log (base 10), sqrt, abs, n!, pi and e, with an angle mode of "rad" (the default) or "deg".
- [ ] {"expr":"sin(30)","mode":"deg"} returns exact "1/2"; {"expr":"sin(pi/6)"} returns exact "1/2"
- [ ] {"expr":"asin(1/2)","mode":"deg"} returns exact "30"
- [ ] {"expr":"sqrt(8)"} returns exact "2*sqrt(2)"; {"expr":"5!"} returns exact "120"; {"expr":"log(1000)"} returns exact "3"
- [ ] {"expr":"2pi"} returns exact "2*pi" and decimal "6.28318530718"; {"expr":"ln(e^2)"} returns exact "2"

### P5: Non-real results return 200 with an exact form and a rectangular complex form {"real","imag"}. 200 with a domain_error only when the math has no value (1/0, 0/0). 400 for client mistakes: syntax, missing or invalid parameters, redefining a constant. An undefined name is a symbol (as on the TI-Nspire CAS); decimal is null while a free name remains.
- [ ] {"expr":"sqrt(-4)"} returns 200 with exact "2*I" and complex {"real":"0","imag":"2"}; {"expr":"ln(-1)"} returns exact "I*pi" and complex {"real":"0","imag":"3.14159265359"}
- [ ] {"expr":"1/0"} returns 200 with exact null, decimal null and domain_error "division by zero"
- [ ] {"expr":"0/0"} returns 200 with exact null, decimal null and a non-null domain_error
- [ ] {"expr":"2x"} with x undefined returns 200 with exact "2*x" and decimal null; {"expr":"1","mode":"grad"} returns 400

### P6: Each successful evaluation is added to the history. `ans` recalls the last result.
- [ ] After evaluating "2+3", GET /api/calc/history returns 200 {"history":[...]} whose last entry is {"expr":"2+3","exact":"5","decimal":"5"}
- [ ] Evaluating "ans*2" after "2+3" returns exact "10"
- [ ] DELETE /api/calc/history returns 200 {"history":[]}, after which GET returns {"history":[]}; with an empty history, "ans" returns 400 with error "ans is undefined"

### P7: `name:=expr` defines a variable and `f(x):=expr` defines a function; the evaluate response gives the defined value or body as exact. Both are usable in later expressions and can be listed.
- [ ] Evaluating "a:=5" then "2a+1" returns exact "11"
- [ ] Evaluating "f(x):=x^2+1" then "f(3)" returns exact "10"
- [ ] GET /api/calc/vars returns {"variables":{"a":"5"},"functions":{"f":{"params":["x"],"body":"x^2 + 1"}}}; defining "pi:=3" returns 400 with error "cannot redefine constant pi"

### P8: The Calculator tab is wired to the calculator endpoints.
- [ ] GET / contains elements with ids calc-input, calc-mode, calc-submit, calc-history, calc-vars and calc-error
- [ ] GET /static/app.js contains the paths /api/calc/evaluate, /api/calc/history and /api/calc/vars

### P9: Variables, functions, lists and history are held in memory and written through atomically to a JSON file (--state PATH, default ./graphcalc_state.json), which is loaded again on startup. --in-memory turns off disk writes.
- [ ] After "a:=5" with --state S, restarting the server with the same --state S and evaluating "a" returns exact "5"
- [ ] The state file S parses as valid JSON after every change
- [ ] POST /api/state/reset returns 200 {"status":"reset"} and empties variables, functions, lists and history; with --in-memory no state file is created
- [ ] The repository's .gitignore lists graphcalc_state.json

### P10: POST /api/graph/plot takes {"functions":{"f1".."f4":expr},"window":{"xmin","xmax","ymin","ymax"},"samples":int} and answers {"x":[numbers],"series":{"f1":{"color":"#rrggbb","y":[number|null]}}}. Non-real, infinite or nan y-values are null so the curve shows a gap.
- [ ] {"functions":{"f1":"x^2"},"window":{"xmin":-2,"xmax":2,"ymin":-1,"ymax":5},"samples":5} returns x [-2,-1,0,1,2] and series.f1.y [4,1,0,1,4]
- [ ] f1 "sqrt(x)" sampled at x [-1,0,1] returns y [null,0,1]; f1 "1/x" at x=0 returns y null with status 200
- [ ] f1 to f4 each return a different series color; a fifth function or xmin >= xmax returns 400

### P11: POST /api/graph/window takes {"action":"zoom_in"|"zoom_out"|"pan"|"standard","factor","dx","dy","window"} and answers {"xmin","xmax","ymin","ymax"}; standard is -10..10 on both axes.
- [ ] {"action":"zoom_in","factor":2,"window":{"xmin":-10,"xmax":10,"ymin":-10,"ymax":10}} returns {"xmin":-5,"xmax":5,"ymin":-5,"ymax":5}
- [ ] zoom_out with factor 2 on the same window returns -20..20 on both axes
- [ ] {"action":"pan","dx":1,"dy":-2} on the standard window returns xmin -9, xmax 11, ymin -12, ymax 8; an unknown action returns 400

### P12: POST /api/graph/analyze takes {"operation":"value"|"zero"|"minimum"|"maximum"|"intersection","f":expr,"g":expr (intersection),"x" (value),"lower","upper"} and answers {"operation","x","y","domain_error"} with decimals of 12 significant digits.
- [ ] value of "x^2+1" at x=3 returns x "3", y "10"; zero of "x^2-4" on [0,5] returns x "2"
- [ ] minimum of "x^2-2x" on [-5,5] returns x "1", y "-1"; maximum of "-x^2+4" on [-3,3] returns x "0", y "4"
- [ ] intersection of "x" and "x^2" on [0.5,2] returns x "1", y "1"; zero of "x^2+1" on [-5,5] returns 200 with x null, y null and domain_error "no zero in interval"

### P13: POST /api/graph/table takes {"functions","start","step","rows"} and answers {"x":[str],"columns":{"f1":[str|null]}}.
- [ ] {"functions":{"f1":"x^2"},"start":0,"step":0.5,"rows":3} returns x ["0","0.5","1"] and columns.f1 ["0","0.25","1"]
- [ ] A non-real value is null in the table; step 0 or rows > 1000 returns 400

### P14: The Graphs tab is wired to the graph endpoints and draws on the canvas.
- [ ] GET / contains elements with ids graph-f1, graph-f2, graph-f3, graph-f4, graph-xmin, graph-xmax, graph-ymin, graph-ymax, graph-zoom-in, graph-zoom-out, graph-pan-left, graph-pan-right, graph-pan-up, graph-pan-down, graph-trace-x, graph-analyze and graph-table
- [ ] GET /static/app.js contains the paths /api/graph/plot, /api/graph/window, /api/graph/analyze and /api/graph/table

### P15: Named lists that can be created, read, updated and deleted through /api/lists, and used in expressions.
- [ ] PUT /api/lists/L1 {"values":["1","2","3"]} returns 200, GET /api/lists/L1 returns {"name":"L1","values":["1","2","3"]}, and GET /api/lists returns {"lists":[names]}
- [ ] DELETE /api/lists/L1 returns 200 {"deleted":"L1"} then GET returns 404; PUT with a value of "abc+" or a list name not matching [A-Za-z][A-Za-z0-9_]{0,15} returns 400
- [ ] Lists survive a restart with the same --state S, and POST /api/state/reset empties them
- [ ] With L1 = [1,2,3], evaluating "2*L1+1" returns exact "[3, 5, 7]"

### P16: POST /api/stats/onevar takes {"list":name} and answers n (integer) plus mean, median, sum, sx, sigma_x, min, q1, q3 and max, each {"exact","decimal"} (TI quartile method).
- [ ] For L1 [1,2,3,4,5] it returns n 5 and exact mean "3", median "3", sum "15", min "1", q1 "3/2" (decimal "1.5"), q3 "9/2" (decimal "4.5"), max "5"
- [ ] For the same list sx is exact "sqrt(10)/2" (decimal "1.58113883008") and sigma_x is exact "sqrt(2)" (decimal "1.41421356237")
- [ ] An empty list, a missing list key or an undefined list name returns 400

### P17: POST /api/stats/regression takes {"model":"linear"|"quadratic","x":[str],"y":[str]} and answers {"model","coefficients":{"a","b"[,"c"]},"r2","points":[[x,y]],"curve":[[x,y]]}. Coefficients and r2 are decimal strings with 12 significant digits.
- [ ] linear on x [1,2,3], y [2,4,6] returns coefficients a "2", b "0" and r2 "1"
- [ ] quadratic on x [0,1,2,3], y [1,2,5,10] returns a "1", b "0", c "1", r2 "1"
- [ ] points holds the data pairs and curve holds 50 points across the data x-range; lists of different lengths return 400

### P18: The Lists & Statistics tab is wired to the list and statistics endpoints.
- [ ] GET / contains elements with ids list-grid, stats-list, stats-output, regression-model, regression-output and a canvas with id stats-canvas
- [ ] GET /static/app.js contains the paths /api/lists, /api/stats/onevar and /api/stats/regression

### P19: POST /api/cas/simplify, /expand and /factor take {"expr"} and answer {"result"} in exact form with ^ for powers.
- [ ] simplify "(x^2-1)/(x-1)" returns result "x + 1"
- [ ] expand "(x+1)^2" returns result "x^2 + 2*x + 1"
- [ ] factor "x^2-5x+6" returns result "(x - 3)*(x - 2)"; a malformed expr returns 400

### P20: POST /api/cas/derivative {"expr","var"}, /integral {"expr","var","lower","upper" (optional)} and /limit {"expr","var","point","dir" (optional)} answer {"result"}. lower, upper and point each accept a number or an expression string such as "pi" or "oo".
- [ ] derivative of "x*sin(x)" by x returns "x*cos(x) + sin(x)"
- [ ] integral of "x^2" by x returns "x^3/3"; with lower 0 and upper 1 it returns "1/3"
- [ ] limit of "sin(x)/x" at point 0 returns "1"; limit of "1/x" at point 0 with dir "+" returns "oo"
- [ ] integral of "sin(x)" by x with lower 0 and upper "pi" returns "2"; limit of "1/x" at point "oo" returns "0"

### P21: POST /api/cas/solve takes {"equation":"lhs=rhs" or an expression taken to equal 0,"var"} and answers {"solutions":[str]} in exact form.
- [ ] solve "x^2=4" for x returns {"solutions":["-2","2"]}
- [ ] solve "x^2+1" for x returns {"solutions":["-I","I"]}
- [ ] solve "2y+3=7" for y returns {"solutions":["2"]}; a missing var returns 400

### P22: The CAS tab is wired to every CAS endpoint.
- [ ] GET / contains elements with ids cas-input, cas-var, cas-op, cas-submit and cas-output
- [ ] GET /static/app.js contains the paths /api/cas/simplify, /api/cas/expand, /api/cas/factor, /api/cas/derivative, /api/cas/integral, /api/cas/limit and /api/cas/solve

## Quality bar (release gate)
- Tests run with pytest (python -m pytest) and pytest-cov; line coverage is at least 85%
- coverage.py, ruff and mypy are CI/dev-only tools and are never runtime dependencies
- An end-to-end HTTP suite starts the server with --in-memory and checks a fixed list of canonical expressions against exact expected JSON covering arithmetic, symbolic math, complex output, variables, functions, lists, history and graph coordinates
- No request can cause a 500: fuzzed malformed expressions get 400 with a JSON error
- ruff lint passes with no errors
- Type checks pass (mypy) on the graphcalc package
- The package builds as an sdist and wheel (python -m build)
- A smoke check starts the server, gets 200 from GET /health and GET /, and stops it
- A dependency audit (pip-audit) reports no known vulnerabilities
- A secret scan of the repository finds no secrets
- The README run instructions (install sympy, then python -m graphcalc --port 8000) are run in CI
- Targets Python 3.12 or newer

## Approved dependencies
- sympy

## Runtime
- kind: http
- module: graphcalc
- args: --port {port} --in-memory
- health: /health

Generated by SCIO product mode; edit by hand or rerun `scio new` to revise.
