"use strict";
/* The dev console logic (spec S1 section 14b, fourth and fifth
 * rulings).
 *
 * Operator surfaces only: the day browser over each stored day, day
 * controls on the latest one, the target behind a toggle, the stored
 * submission rendered read-only, and the scoring view with the
 * standardized score of each channel beside the fused number plus
 * the atom report. No sketch input and no send exists on this page -
 * play happens on the main page.
 */

function startDevConsole() {
  function byId(id) { return document.getElementById(id); }

  var LEADERBOARD_LIMIT = 25;
  var lastRankings = null;
  var currentRow = null;
  var latestDay = null;
  var targetShown = false;

  function lifecycleAction(path, confirmation) {
    if (confirmation && !window.confirm(confirmation)) { return; }
    byId("day-control-note").textContent = "working…";
    fetch(path, {method: "POST"}).then(function (response) {
      return response.json().then(function (body) {
        if (response.ok) { window.location.reload(); }
        else {
          byId("day-control-note").textContent =
            body.detail || body.cause || "refused";
        }
      });
    }).catch(function () {
      byId("day-control-note").textContent = "the server did not answer";
    });
  }

  function refreshDayControls() {
    /* The control row moves the latest day alone - a past day in
     * the browser reads with no controls. */
    var status = currentRow ? currentRow.status : "none";
    var movable = currentRow === null || currentRow.day === latestDay;
    byId("open-day-button").classList.toggle(
      "hidden", !movable || status === "open");
    byId("close-day-button").classList.toggle(
      "hidden", !movable || status !== "open");
    byId("reveal-day-button").classList.toggle(
      "hidden", !movable || status !== "closed");
  }

  function refreshTarget() {
    var image = byId("dev-target");
    var thumb = byId("rankings-target");
    if (targetShown && currentRow && !image.src.length) {
      image.src = "/image/" + currentRow.target_id;
      thumb.src = image.src;
    }
    image.classList.toggle("hidden", !targetShown);
    thumb.classList.toggle("hidden", !targetShown);
    byId("target-toggle").textContent =
      targetShown ? "Hide the target" : "Show the target";
  }

  function renderReport(rows) {
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
  }

  function renderRankings(body, limit) {
    lastRankings = body;
    byId("dev-trial").textContent =
      "trial score " + body.trial.p.toFixed(4)
      + " - target at position " + body.target_position
      + " of " + body.rankings.length
      + " (rank " + body.trial.target_rank + " of "
      + (body.trial.decoy_count + 1) + " after the near-duplicate "
      + "group exits)";
    renderReport(body.report || []);
    var channels = body.channel_names || [];
    var head = byId("rankings-head");
    head.innerHTML = "";
    var headRow = document.createElement("tr");
    ["#", "", "image"].concat(channels).concat(["fused"])
      .forEach(function (label) {
        var th = document.createElement("th");
        th.textContent = label;
        headRow.appendChild(th);
      });
    head.appendChild(headRow);
    var rows = body.rankings;
    var shown = rows;
    if (limit && rows.length > limit) {
      shown = rows.slice(0, limit).concat(
        rows.slice(limit).filter(function (row) {
          return row.is_target;
        }));
    }
    var tbody = byId("rankings-body");
    tbody.innerHTML = "";
    shown.forEach(function (row) {
      var line = document.createElement("tr");
      if (row.is_target) { line.className = "target-row"; }
      var cell = document.createElement("td");
      cell.textContent = String(row.position);
      line.appendChild(cell);
      var imageCell = document.createElement("td");
      var thumb = document.createElement("img");
      thumb.src = "/image/" + row.image_id;
      thumb.width = 40;
      thumb.loading = "lazy";
      imageCell.appendChild(thumb);
      line.appendChild(imageCell);
      var idCell = document.createElement("td");
      idCell.textContent = row.image_id.slice(0, 8)
        + (row.is_target ? " ← target" : "");
      line.appendChild(idCell);
      channels.forEach(function (name) {
        var channelCell = document.createElement("td");
        var value = (row.channels || {})[name];
        channelCell.textContent =
          value === undefined ? "-" : value.toFixed(4);
        line.appendChild(channelCell);
      });
      var fusedCell = document.createElement("td");
      fusedCell.textContent = row.fused.toFixed(4);
      line.appendChild(fusedCell);
      tbody.appendChild(line);
    });
    byId("rankings").classList.remove("hidden");
    byId("show-all-rankings").classList.toggle(
      "hidden", !limit || rows.length <= limit);
  }

  function loadRankings() {
    byId("rank-note").textContent = "scoring…";
    fetch("/api/dev/rankings?day=" + encodeURIComponent(currentRow.day))
      .then(function (answer) {
        return answer.json().then(function (body) {
          if (!answer.ok) {
            byId("rank-note").textContent =
              body.detail || body.cause || "refused";
            return;
          }
          byId("rank-note").textContent = "";
          renderRankings(body, LEADERBOARD_LIMIT);
        });
      }).catch(function () {
        byId("rank-note").textContent = "the server did not answer";
      });
  }

  function renderSubmission(stored) {
    byId("submission-note").classList.add("hidden");
    byId("submission-view").classList.remove("hidden");
    byId("submission-received").textContent = stored.received_at;
    byId("submission-trial-id").textContent = stored.trial_id;
    var record = stored.record;
    var sketch = byId("submission-sketch");
    sketch.innerHTML = "";
    (record.canvas_strokes || []).forEach(function (stroke) {
      var line = document.createElementNS(
        "http://www.w3.org/2000/svg", "polyline");
      line.setAttribute("points", stroke.points.map(function (point) {
        return (point[0] * 100).toFixed(2) + ","
          + (point[1] * 100).toFixed(2);
      }).join(" "));
      line.setAttribute("fill", "none");
      line.setAttribute("stroke",
                        stroke.group_id ? "#1b6b3a" : "#1a1c1e");
      line.setAttribute("stroke-width", "1");
      sketch.appendChild(line);
    });
    var impressions = byId("submission-impressions");
    impressions.innerHTML = "";
    (record.impressions || []).forEach(function (text) {
      var item = document.createElement("li");
      item.textContent = "impression: " + text;
      impressions.appendChild(item);
    });
    var labels = {};
    (record.groups || []).forEach(function (group) {
      labels[group.id] = group.label
        ? group.label + " (" + group.id + ")" : group.id;
    });
    var groups = byId("submission-groups");
    groups.innerHTML = "";
    (record.groups || []).forEach(function (group) {
      var item = document.createElement("li");
      item.textContent = "group: " + labels[group.id];
      groups.appendChild(item);
    });
    (record.relations || []).forEach(function (relation) {
      var item = document.createElement("li");
      item.textContent = "relation: "
        + (labels[relation.of[0]] || relation.of[0]) + " "
        + relation.relation + " "
        + (labels[relation.of[1]] || relation.of[1]);
      groups.appendChild(item);
    });
    byId("submission-paste").textContent =
      record.pasted_text ? "pasted: " + record.pasted_text : "";
  }

  function showDay(row) {
    currentRow = row;
    targetShown = false;
    var image = byId("dev-target");
    image.removeAttribute("src");
    byId("rankings-target").removeAttribute("src");
    refreshTarget();
    refreshDayControls();
    byId("trial-code").textContent = row.trial_code;
    byId("day-label").textContent = row.day;
    byId("status-line").textContent = "status " + row.status;
    byId("commitment").textContent = row.commitment;
    byId("submission-note").classList.remove("hidden");
    byId("submission-view").classList.add("hidden");
    byId("rank-button").classList.add("hidden");
    byId("rankings").classList.add("hidden");
    byId("report-table").classList.add("hidden");
    byId("show-all-rankings").classList.add("hidden");
    byId("dev-trial").textContent = "";
    byId("rank-note").textContent = "";
    fetch("/api/dev/submission?day=" + encodeURIComponent(row.day))
      .then(function (answer) {
        if (!answer.ok) { return; }
        answer.json().then(function (stored) {
          renderSubmission(stored);
          byId("rank-button").classList.remove("hidden");
          if (row.status === "closed" || row.status === "revealed") {
            loadRankings();
          }
        });
      }).catch(function () {});
  }

  byId("show-all-rankings").addEventListener("click", function () {
    if (lastRankings) { renderRankings(lastRankings, 0); }
  });
  byId("rank-button").addEventListener("click", loadRankings);
  byId("target-toggle").addEventListener("click", function () {
    if (!currentRow) { return; }
    targetShown = !targetShown;
    refreshTarget();
  });
  byId("open-day-button").addEventListener("click", function () {
    lifecycleAction("/api/day/open", null);
  });
  byId("close-day-button").addEventListener("click", function () {
    lifecycleAction("/api/day/close",
                    "Close the day? Scoring runs and the window "
                    + "locks.");
  });
  byId("reveal-day-button").addEventListener("click", function () {
    lifecycleAction("/api/day/reveal", null);
  });

  fetch("/api/dev/days").then(function (response) {
    if (!response.ok) {
      byId("status-line").textContent =
        "start the server with --dev to use this console";
      return;
    }
    response.json().then(function (body) {
      var rows = body.days || [];
      if (rows.length === 0) {
        byId("status-line").textContent = "no day yet";
        byId("trial-code").textContent = "······";
        refreshDayControls();
        return;
      }
      latestDay = rows[0].day;
      var select = byId("day-select");
      select.classList.remove("hidden");
      rows.forEach(function (row) {
        var option = document.createElement("option");
        option.value = row.day;
        option.textContent = row.day + " · " + row.trial_code
          + " · " + row.status + (row.submitted ? " · sent" : "");
        select.appendChild(option);
      });
      select.addEventListener("change", function () {
        rows.forEach(function (row) {
          if (row.day === select.value) { showDay(row); }
        });
      });
      showDay(rows[0]);
    });
  }).catch(function () {
    byId("status-line").textContent = "the server did not answer";
  });
}

if (typeof module !== "undefined") {
  module.exports = {startDevConsole: startDevConsole};
}
