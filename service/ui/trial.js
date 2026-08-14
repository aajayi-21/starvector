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
    strokes: [],        /* {points: [[x, y], ...], color: null|"#rrggbb",
                            groupId: null|string, selected: bool} */
    groups: [],         /* {id, label} in creation order */
    relations: [],      /* {relation, of: [id, id]} */
    pastedText: null,
  };
}

function assembleRecord(state) {
  return {
    impressions: state.impressions.slice(),
    canvas_strokes: state.strokes.map(function (stroke) {
      var row = {
        points: stroke.points.map(function (point) {
          return [point[0], point[1]];
        }),
        group_id: stroke.groupId === undefined ? null : stroke.groupId,
      };
      /* The ink default emits no key (spec C1): a plain sketch is
       * byte-identical to one from before the color ruling. */
      if (stroke.color) { row.color = stroke.color; }
      return row;
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
      state.strokes.push({points: action.points,
                          color: action.color || null,
                          groupId: null, selected: false});
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
  /* Two backing states (P5): the daily sketch and the practice
   * sketch stay apart, and the shared intake surface re-parents
   * between the two views - the canvas survives a DOM move. */
  var dayState = emptyState();
  var practiceState = emptyState();
  var state = dayState;
  var dayView = "view-noday";
  var paletteBuilt = false;
  var practiceRounds = 0;
  var canvas = document.getElementById("canvas");
  var context = canvas.getContext("2d");
  var drawing = null;
  var CANVAS = 512;
  var INK = "#1a1c1e";
  var SELECTED = "#b3261e";
  /* The fixed palette (spec C1 section 5). Ink emits no color key. */
  var PALETTE = [
    {name: "ink", value: null},
    {name: "red", value: "#c5221f"},
    {name: "orange", value: "#e8710a"},
    {name: "yellow", value: "#f0b429"},
    {name: "green", value: "#1b6b3a"},
    {name: "blue", value: "#1a73e8"},
    {name: "purple", value: "#7a4ec9"},
    {name: "brown", value: "#795548"},
  ];
  var currentColor = null;
  /* One color for each group, in creation order, thus a stroke's
   * color on the canvas matches its group's swatch in the list. */
  var GROUP_COLORS = ["#1b6b3a", "#7a4ec9", "#0e7a8a", "#b3611e",
                      "#4356c9"];
  var RELATION_WORDING = {"left-of": "is left of",
                          "right-of": "is right of",
                          "above": "is above", "below": "is below"};

  function byId(id) { return document.getElementById(id); }

  function groupColor(groupId) {
    var index = state.groups.map(function (group) { return group.id; })
      .indexOf(groupId);
    return GROUP_COLORS[((index % GROUP_COLORS.length)
                         + GROUP_COLORS.length) % GROUP_COLORS.length];
  }

  function groupName(groupId) {
    var found = null;
    state.groups.forEach(function (group) {
      if (group.id === groupId) { found = group; }
    });
    if (!found) { return groupId; }
    return found.label ? found.label + " (" + found.id + ")" : found.id;
  }

  function relationWording(name) {
    return RELATION_WORDING[name] || ("is " + name);
  }
  function show(view) {
    ["view-loading", "view-noday", "view-intake", "view-submitted",
     "view-closed", "view-reveal", "view-practice"].forEach(
      function (name) {
        byId(name).classList.toggle("hidden", name !== view);
      });
    if (view !== "view-practice") { dayView = view; }
  }

  function drawPath(points, color, width) {
    context.beginPath();
    context.lineWidth = width;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.strokeStyle = color;
    points.forEach(function (point, index) {
      var x = point[0] * CANVAS;
      var y = point[1] * CANVAS;
      if (index === 0) { context.moveTo(x, y); }
      else { context.lineTo(x, y); }
    });
    context.stroke();
  }

  function redraw() {
    /* Selection and group membership are halos behind the stroke -
     * the stroke keeps its own color, thus the sketch on screen is
     * what the model sees, up to the halo. */
    context.clearRect(0, 0, CANVAS, CANVAS);
    state.strokes.forEach(function (stroke) {
      var halo = stroke.selected ? SELECTED
        : (stroke.groupId ? groupColor(stroke.groupId) : null);
      if (halo) { drawPath(stroke.points, halo, 9); }
      drawPath(stroke.points, stroke.color || INK, 3);
    });
  }

  function startPalette() {
    if (paletteBuilt) { return; }
    paletteBuilt = true;
    var row = byId("palette");
    PALETTE.forEach(function (entry) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "swatch-button";
      button.title = entry.name;
      button.style.background = entry.value || INK;
      if (entry.value === currentColor) {
        button.classList.add("current");
      }
      button.addEventListener("click", function () {
        currentColor = entry.value;
        row.querySelectorAll(".swatch-button").forEach(function (b) {
          b.classList.remove("current");
        });
        button.classList.add("current");
      });
      row.appendChild(button);
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
    drawPath(drawing.points, currentColor || INK, 3);
  });
  canvas.addEventListener("pointerup", function (event) {
    if (!drawing) { return; }
    if (drawing.moved && drawing.points.length > 1) {
      state.strokes.push({points: drawing.points, color: currentColor,
                          groupId: null, selected: false});
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

  function removeButton(onRemove) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "remove";
    button.textContent = "\u00d7";
    button.title = "remove";
    button.addEventListener("click", onRemove);
    return button;
  }

  function refreshLists() {
    byId("impression-list").innerHTML = "";
    state.impressions.forEach(function (text, index) {
      var item = document.createElement("li");
      item.textContent = text + " ";
      item.appendChild(removeButton(function () {
        state.impressions.splice(index, 1);
        refreshControls();
      }));
      byId("impression-list").appendChild(item);
    });
    byId("group-list").innerHTML = "";
    state.groups.forEach(function (group) {
      var item = document.createElement("li");
      var swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = groupColor(group.id);
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(
        group.label ? group.label + " (" + group.id + ")" : group.id));
      byId("group-list").appendChild(item);
    });
    byId("relation-list").innerHTML = "";
    state.relations.forEach(function (relation, index) {
      var item = document.createElement("li");
      item.textContent = groupName(relation.of[0]) + " "
        + relationWording(relation.relation) + " "
        + groupName(relation.of[1]) + " ";
      item.appendChild(removeButton(function () {
        state.relations.splice(index, 1);
        refreshControls();
      }));
      byId("relation-list").appendChild(item);
    });
    ["relation-first", "relation-second"].forEach(function (name) {
      var select = byId(name);
      var kept = select.value;
      select.innerHTML = "";
      state.groups.forEach(function (group) {
        var option = document.createElement("option");
        option.value = group.id;
        option.textContent = groupName(group.id);
        select.appendChild(option);
      });
      if (kept) { select.value = kept; }
    });
  }

  function scoreable() {
    return state.impressions.length > 0 || state.strokes.length > 0
      || (byId("paste-input").value.trim() !== "");
  }

  function countOf(count, word) {
    return count + " " + word + (count === 1 ? "" : "s");
  }

  function refreshSketchHint() {
    var selected = state.strokes.filter(function (stroke) {
      return stroke.selected;
    }).length;
    if (state.strokes.length === 0) {
      byId("sketch-hint").textContent =
        "Draw with the pointer - each drag is one stroke.";
    } else if (selected > 0) {
      byId("sketch-hint").textContent = countOf(selected, "stroke")
        + " selected - name the group below, then Make a group.";
    } else {
      byId("sketch-hint").textContent =
        "Click a stroke to select it - it gets a red halo.";
    }
    return selected;
  }

  function refreshControls() {
    var selected = refreshSketchHint();
    byId("group-button").disabled = selected === 0;
    var last = state.strokes[state.strokes.length - 1];
    byId("undo-button").disabled = !last || last.groupId !== null;
    var ready = state.groups.length >= 2;
    ["relation-first", "relation-name", "relation-second",
     "relation-button"].forEach(function (name) {
      byId(name).disabled = !ready;
    });
    byId("relation-hint").textContent = ready
      ? "Read the row as a sentence, then Add."
      : "Make two or more groups, then state how one sits relative "
        + "to another - \"the tower is left of the sea\".";
    byId("send-button").disabled = !scoreable();
    byId("send-summary").textContent = !scoreable() ? ""
      : countOf(state.impressions.length, "impression") + " \u00b7 "
        + countOf(state.strokes.length, "stroke") + " \u00b7 "
        + countOf(state.groups.length, "group") + " \u00b7 "
        + countOf(state.relations.length, "relation")
        + (byId("paste-input").value.trim() !== ""
           ? " \u00b7 pasted text" : "");
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
  byId("undo-button").addEventListener("click", function () {
    /* The last stroke goes, when it is not in a group yet - a
     * grouped stroke stays, thus group ids never dangle. */
    var last = state.strokes[state.strokes.length - 1];
    if (!last || last.groupId !== null) { return; }
    state.strokes.pop();
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

  function renderReportRows(tbody, rows) {
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
  }

  /* ---------- practice (P5) ---------- */

  function moveIntakeSurface(slotId) {
    byId(slotId).appendChild(byId("intake-surface"));
  }

  function swapState(next, slotId) {
    /* The paste textarea is live DOM inside the moved surface -
     * snapshot it into the outgoing state and restore the incoming
     * one, or practice notes ride into the permanent daily record. */
    var paste = byId("paste-input");
    state.pastedText = paste.value.trim() === "" ? null : paste.value;
    state = next;
    paste.value = state.pastedText || "";
    moveIntakeSurface(slotId);
    redraw();
    refreshControls();
  }

  function enterPractice() {
    fetch("/api/practice").then(function (response) {
      if (!response.ok) {
        byId("practice-empty").textContent =
          "No revealed day yet - play and reveal a day first.";
        byId("practice-empty").classList.remove("hidden");
        show("view-practice");
        return;
      }
      response.json().then(function (body) {
        var select = byId("practice-day");
        select.innerHTML = "";
        body.days.forEach(function (row) {
          var option = document.createElement("option");
          option.value = row.day;
          option.textContent = row.day + " · " + row.trial_code;
          select.appendChild(option);
        });
        byId("practice-empty").classList.add("hidden");
        startPalette();
        swapState(practiceState, "practice-intake-slot");
        byId("practice-result").classList.add("hidden");
        show("view-practice");
      });
    }).catch(function () {
      byId("practice-note").textContent = "the server did not answer";
    });
  }

  function leavePractice() {
    swapState(dayState, "day-intake-slot");
    show(dayView);
  }

  function scorePractice() {
    var day = byId("practice-day").value;
    if (!day) { return; }
    var paste = byId("paste-input").value;
    state.pastedText = paste.trim() === "" ? null : paste;
    byId("practice-score-button").disabled = true;
    byId("practice-note").textContent = "scoring…";
    byId("practice-error").textContent = "";
    fetch("/api/practice/score", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({day: day, record: assembleRecord(state)}),
    }).then(function (response) {
      return response.json().then(function (body) {
        byId("practice-score-button").disabled = false;
        byId("practice-note").textContent = "";
        if (!response.ok) {
          byId("practice-error").textContent =
            body.detail || body.cause || "refused";
          return;
        }
        practiceRounds += 1;
        byId("practice-session").textContent =
          practiceRounds + " scored this session";
        byId("practice-score-line").textContent =
          "trial score " + body.trial.p.toFixed(4)
          + " - you beat " + body.trial.beaten + " of "
          + body.trial.decoy_count + " decoys (rank "
          + body.trial.target_rank + ", position "
          + body.target_position + " of the full ordering)";
        var rows = body.report || [];
        byId("practice-report-table").classList.toggle(
          "hidden", rows.length === 0);
        renderReportRows(byId("practice-report-body"), rows);
        var head = byId("practice-head-body");
        head.innerHTML = "";
        (body.ranking_head || []).forEach(function (row) {
          var line = document.createElement("tr");
          if (row.is_target) { line.className = "ok"; }
          [String(row.position), row.fused.toFixed(4),
           row.is_target ? "your target" : ""].forEach(function (cell) {
            var td = document.createElement("td");
            td.textContent = cell;
            line.appendChild(td);
          });
          head.appendChild(line);
        });
        byId("practice-image").src = "/image/" + body.target_id;
        byId("practice-result").classList.remove("hidden");
      });
    }).catch(function () {
      byId("practice-score-button").disabled = false;
      byId("practice-note").textContent = "the server did not answer";
    });
  }

  byId("practice-link").addEventListener("click", function (event) {
    event.preventDefault();
    enterPractice();
  });
  byId("back-to-day").addEventListener("click", function (event) {
    event.preventDefault();
    leavePractice();
  });
  byId("practice-random").addEventListener("click", function () {
    var select = byId("practice-day");
    if (select.options.length > 0) {
      select.selectedIndex = Math.floor(
        Math.random() * select.options.length);
    }
  });
  byId("practice-score-button").addEventListener("click", scorePractice);

  function renderReveal() {
    fetch("/api/reveal").then(function (response) {
      if (!response.ok) { show("view-closed"); return; }
      response.json().then(function (body) {
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
        renderReportRows(byId("report-body"), rows);
        show("view-reveal");
      });
    });
  }

  fetch("/api/day").then(function (response) {
    if (!response.ok) { show("view-noday"); return; }
    response.json().then(function (day) {
      byId("day-label").textContent = day.day;
      byId("trial-code").textContent = day.trial_code;
      byId("commitment").textContent = day.commitment;
      var vocabulary = day.relation_vocabulary || [];
      var select = byId("relation-name");
      vocabulary.forEach(function (name) {
        var option = document.createElement("option");
        option.value = name;
        option.textContent = relationWording(name);
        select.appendChild(option);
      });
      if (day.status === "revealed") { renderReveal(); }
      else if (day.submitted) { show("view-submitted"); }
      else if (day.status === "closed") { show("view-closed"); }
      else { show("view-intake"); startPalette(); refreshControls(); }
    });
  }).catch(function () { show("view-noday"); });
}
