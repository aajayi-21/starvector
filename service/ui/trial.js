"use strict";
/* The intake page logic (spec S1 section 9).
 *
 * The pure core - emptyState, applyScript, assembleRecord - builds
 * the exact harness wire record and is exported for the fixture
 * test. The page half captures pointer strokes on a square canvas,
 * normalized to the unit square (the section 8 shape), and posts
 * the assembled record once.
 */

/* ---------- the pure core ---------- */

function emptyState() {
  return {
    impressions: [],
    strokes: [],        /* {points: [[x, y], ...], groupId: null|string,
                            selected: bool} */
    groups: [],         /* {id, label} in creation order */
    relations: [],      /* {relation, of: [id, id]} */
    pastedText: null,
  };
}

function assembleRecord(state) {
  return {
    impressions: state.impressions.slice(),
    canvas_strokes: state.strokes.map(function (stroke) {
      return {
        points: stroke.points.map(function (point) {
          return [point[0], point[1]];
        }),
        group_id: stroke.groupId === undefined ? null : stroke.groupId,
      };
    }),
    groups: state.groups.map(function (group) {
      return {id: group.id, label: group.label};
    }),
    relations: state.relations.map(function (relation) {
      return {relation: relation.relation, of: relation.of.slice()};
    }),
    pasted_text: state.pastedText,
  };
}

function groupSelected(state, label) {
  var selected = state.strokes.filter(function (s) { return s.selected; });
  if (selected.length === 0) { return null; }
  var id = "g" + (state.groups.length + 1);
  state.groups.push({id: id, label: label || ""});
  selected.forEach(function (stroke) {
    stroke.groupId = id;
    stroke.selected = false;
  });
  return id;
}

function applyScript(script) {
  /* Replays a recorded interaction into a state - the section 11
   * fixture mechanism. Actions: impression, stroke, selectStrokes,
   * group, relation, paste. */
  var state = emptyState();
  script.forEach(function (action) {
    if (action.action === "impression") {
      state.impressions.push(action.text);
    } else if (action.action === "stroke") {
      state.strokes.push({points: action.points, groupId: null,
                          selected: false});
    } else if (action.action === "selectStrokes") {
      action.indexes.forEach(function (index) {
        state.strokes[index].selected = true;
      });
    } else if (action.action === "group") {
      groupSelected(state, action.label);
    } else if (action.action === "relation") {
      state.relations.push({relation: action.relation,
                            of: [action.first, action.second]});
    } else if (action.action === "paste") {
      state.pastedText = action.text === "" ? null : action.text;
    } else {
      throw new Error("unknown action: " + action.action);
    }
  });
  return state;
}

if (typeof module !== "undefined") {
  module.exports = {emptyState: emptyState, applyScript: applyScript,
                    assembleRecord: assembleRecord,
                    groupSelected: groupSelected};
}

/* ---------- the page half ---------- */

function startTrialPage() {
  var state = emptyState();
  var canvas = document.getElementById("canvas");
  var context = canvas.getContext("2d");
  var drawing = null;
  var CANVAS = 512;

  function byId(id) { return document.getElementById(id); }
  function show(view) {
    ["view-loading", "view-noday", "view-intake", "view-submitted",
     "view-closed", "view-reveal"].forEach(function (name) {
      byId(name).classList.toggle("hidden", name !== view);
    });
  }

  function redraw() {
    context.clearRect(0, 0, CANVAS, CANVAS);
    state.strokes.forEach(function (stroke) {
      context.beginPath();
      context.lineWidth = 3;
      context.lineCap = "round";
      context.lineJoin = "round";
      context.strokeStyle = stroke.selected ? "#b3261e"
        : (stroke.groupId ? "#1b6b3a" : "#1a1c1e");
      stroke.points.forEach(function (point, index) {
        var x = point[0] * CANVAS;
        var y = point[1] * CANVAS;
        if (index === 0) { context.moveTo(x, y); }
        else { context.lineTo(x, y); }
      });
      context.stroke();
    });
  }

  function clamp01(value) {
    return Math.min(1, Math.max(0, value));
  }

  function pointOf(event) {
    var rect = canvas.getBoundingClientRect();
    return [clamp01((event.clientX - rect.left) / rect.width),
            clamp01((event.clientY - rect.top) / rect.height)];
  }

  function nearestStroke(point) {
    var best = -1;
    var bestDistance = 0.03;   /* unit-square hit radius */
    state.strokes.forEach(function (stroke, index) {
      stroke.points.forEach(function (candidate) {
        var dx = candidate[0] - point[0];
        var dy = candidate[1] - point[1];
        var distance = Math.sqrt(dx * dx + dy * dy);
        if (distance < bestDistance) {
          best = index;
          bestDistance = distance;
        }
      });
    });
    return best;
  }

  canvas.addEventListener("pointerdown", function (event) {
    canvas.setPointerCapture(event.pointerId);
    drawing = {points: [pointOf(event)], moved: false};
  });
  canvas.addEventListener("pointermove", function (event) {
    if (!drawing) { return; }
    drawing.points.push(pointOf(event));
    drawing.moved = true;
    context.clearRect(0, 0, CANVAS, CANVAS);
    redraw();
    context.beginPath();
    context.lineWidth = 3;
    context.strokeStyle = "#1a1c1e";
    drawing.points.forEach(function (point, index) {
      var x = point[0] * CANVAS;
      var y = point[1] * CANVAS;
      if (index === 0) { context.moveTo(x, y); }
      else { context.lineTo(x, y); }
    });
    context.stroke();
  });
  canvas.addEventListener("pointerup", function (event) {
    if (!drawing) { return; }
    if (drawing.moved && drawing.points.length > 1) {
      state.strokes.push({points: drawing.points, groupId: null,
                          selected: false});
    } else {
      var hit = nearestStroke(pointOf(event));
      if (hit >= 0) {
        state.strokes[hit].selected = !state.strokes[hit].selected;
      }
    }
    drawing = null;
    redraw();
    refreshControls();
  });

  function refreshLists() {
    byId("impression-list").innerHTML = "";
    state.impressions.forEach(function (text) {
      var item = document.createElement("li");
      item.textContent = text;
      byId("impression-list").appendChild(item);
    });
    byId("group-list").innerHTML = "";
    state.groups.forEach(function (group) {
      var item = document.createElement("li");
      item.textContent = group.id + (group.label ? " - " + group.label : "");
      byId("group-list").appendChild(item);
    });
    byId("relation-list").innerHTML = "";
    state.relations.forEach(function (relation) {
      var item = document.createElement("li");
      item.textContent = relation.of[0] + " " + relation.relation + " "
        + relation.of[1];
      byId("relation-list").appendChild(item);
    });
    ["relation-first", "relation-second"].forEach(function (name) {
      var select = byId(name);
      select.innerHTML = "";
      state.groups.forEach(function (group) {
        var option = document.createElement("option");
        option.value = group.id;
        option.textContent = group.id;
        select.appendChild(option);
      });
    });
  }

  function scoreable() {
    return state.impressions.length > 0 || state.strokes.length > 0
      || (byId("paste-input").value.trim() !== "");
  }

  function refreshControls() {
    byId("send-button").disabled = !scoreable();
    byId("send-note").textContent = scoreable() ? ""
      : "add an impression, strokes, or pasted text first";
    refreshLists();
  }

  byId("impression-input").addEventListener("keydown", function (event) {
    if (event.key !== "Enter") { return; }
    var text = event.target.value.trim();
    if (text) {
      state.impressions.push(text);
      event.target.value = "";
      refreshControls();
    }
  });
  byId("group-button").addEventListener("click", function () {
    groupSelected(state, byId("group-label").value.trim());
    byId("group-label").value = "";
    redraw();
    refreshControls();
  });
  byId("clear-button").addEventListener("click", function () {
    state.strokes = [];
    state.groups = [];
    state.relations = [];
    redraw();
    refreshControls();
  });
  byId("relation-button").addEventListener("click", function () {
    var first = byId("relation-first").value;
    var second = byId("relation-second").value;
    if (!first || !second || first === second) { return; }
    state.relations.push({relation: byId("relation-name").value,
                          of: [first, second]});
    refreshControls();
  });
  byId("paste-input").addEventListener("input", refreshControls);
  byId("send-button").addEventListener("click", function () {
    var paste = byId("paste-input").value;
    state.pastedText = paste.trim() === "" ? null : paste;
    fetch("/api/submission", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(assembleRecord(state)),
    }).then(function (response) {
      return response.json().then(function (body) {
        if (response.ok) {
          byId("ack-trial").textContent = body.trial_id;
          byId("ack-atoms").textContent = body.atom_count;
          show("view-submitted");
        } else {
          byId("send-error").textContent =
            body.detail || body.cause || "refused";
        }
      });
    }).catch(function () {
      byId("send-error").textContent = "the server did not answer";
    });
  });

  function renderReveal() {
    fetch("/api/reveal").then(function (response) {
      if (!response.ok) { show("view-closed"); return; }
      response.json().then(function (body) {
        byId("target-image").src = "/image/" + body.target_id;
        byId("reveal-secret").textContent = body.secret;
        byId("reveal-check").textContent = body.check;
        if (body.trial) {
          byId("reveal-score").textContent =
            "trial score " + body.trial.p.toFixed(4)
            + " - you beat " + body.trial.beaten + " of "
            + body.trial.decoy_count + " decoys (rank "
            + body.trial.target_rank + ")";
        } else {
          byId("reveal-score").textContent = "no submission this day";
        }
        var rows = body.report || [];
        byId("report-table").classList.toggle("hidden", rows.length === 0);
        var tbody = byId("report-body");
        tbody.innerHTML = "";
        rows.forEach(function (row) {
          var line = document.createElement("tr");
          [row.atom_text, row.element === null ? "-" : row.element,
           row.weight.toFixed(3), row.similarity.toFixed(3),
           row.rarity.toFixed(2)].forEach(function (cell) {
            var td = document.createElement("td");
            td.textContent = String(cell);
            line.appendChild(td);
          });
          tbody.appendChild(line);
        });
        show("view-reveal");
      });
    });
  }

  fetch("/api/day").then(function (response) {
    if (!response.ok) { show("view-noday"); return; }
    response.json().then(function (day) {
      byId("day-label").textContent = day.day;
      byId("commitment").textContent = day.commitment;
      var vocabulary = day.relation_vocabulary || [];
      var select = byId("relation-name");
      vocabulary.forEach(function (name) {
        var option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        select.appendChild(option);
      });
      if (day.status === "revealed") { renderReveal(); }
      else if (day.submitted) { show("view-submitted"); }
      else if (day.status === "closed") { show("view-closed"); }
      else { show("view-intake"); refreshControls(); }
    });
  }).catch(function () { show("view-noday"); });
}
