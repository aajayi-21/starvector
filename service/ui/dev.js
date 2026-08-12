"use strict";
/* The dev console logic (spec S1 section 14b, fourth ruling).
 *
 * Operator surfaces only: day controls, the target behind a toggle,
 * the stored submission rendered read-only, and the scoring and
 * ranking view. No sketch input and no send exists on this page -
 * play happens on the main page.
 */

function startDevConsole() {
  function byId(id) { return document.getElementById(id); }

  var LEADERBOARD_LIMIT = 25;
  var lastRankings = null;

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

  function startDayControls(status) {
    byId("open-day-button").classList.toggle(
      "hidden", status === "open");
    byId("close-day-button").classList.toggle(
      "hidden", status !== "open");
    byId("reveal-day-button").classList.toggle(
      "hidden", status !== "closed");
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
    fetch("/api/dev/rankings").then(function (answer) {
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
    var groups = byId("submission-groups");
    groups.innerHTML = "";
    (record.groups || []).forEach(function (group) {
      var item = document.createElement("li");
      item.textContent = "group " + group.id
        + (group.label ? " - " + group.label : "");
      groups.appendChild(item);
    });
    (record.relations || []).forEach(function (relation) {
      var item = document.createElement("li");
      item.textContent = "relation: " + relation.of[0] + " "
        + relation.relation + " " + relation.of[1];
      groups.appendChild(item);
    });
    byId("submission-paste").textContent =
      record.pasted_text ? "pasted: " + record.pasted_text : "";
  }

  byId("show-all-rankings").addEventListener("click", function () {
    if (lastRankings) { renderRankings(lastRankings, 0); }
  });
  byId("rank-button").addEventListener("click", loadRankings);

  fetch("/api/dev").then(function (response) {
    if (!response.ok) {
      byId("status-line").textContent =
        "start the server with --dev to use this console";
      return;
    }
    response.json().then(function (dev) {
      startDayControls(dev.status);
      if (dev.status === "none") {
        byId("status-line").textContent = "no day yet";
        byId("trial-code").textContent = "······";
        return;
      }
      byId("trial-code").textContent = dev.trial_code;
      byId("day-label").textContent = dev.day;
      byId("status-line").textContent = "status " + dev.status;
      var targetShown = false;
      byId("target-toggle").addEventListener("click", function () {
        targetShown = !targetShown;
        var image = byId("dev-target");
        if (targetShown && !image.src) {
          image.src = "/image/" + dev.target_id;
        }
        image.classList.toggle("hidden", !targetShown);
        byId("target-toggle").textContent =
          targetShown ? "Hide the target" : "Show the target";
      });
      fetch("/api/dev/submission").then(function (answer) {
        if (!answer.ok) { return; }
        answer.json().then(function (stored) {
          renderSubmission(stored);
          byId("rank-button").classList.remove("hidden");
          if (dev.status === "closed" || dev.status === "revealed") {
            loadRankings();
          }
        });
      }).catch(function () {});
    });
  }).catch(function () {
    byId("status-line").textContent = "the server did not answer";
  });

  fetch("/api/day").then(function (response) {
    if (!response.ok) { return; }
    response.json().then(function (day) {
      byId("commitment").textContent = day.commitment;
    });
  }).catch(function () {});
}

if (typeof module !== "undefined") {
  module.exports = {startDevConsole: startDevConsole};
}
