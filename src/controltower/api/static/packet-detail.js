/**
 * Weekly Schedule Intelligence Packet — operator UI enrichment.
 * Reads existing section HTML only (no API); presentation layer.
 */
(function () {
  "use strict";

  function textSection(key) {
    var el = document.querySelector('.pkt-section-block[data-section-key="' + key + '"]');
    if (!el) return "";
    return el.innerText.replace(/\s+/g, " ").trim();
  }

  function setText(id, value) {
    var n = document.getElementById(id);
    if (n) n.textContent = value || "—";
  }

  function parseProjectedFinish(t) {
    if (!t) return "—";
    var m = t.match(/Projected finish:\s*([^\n]+?)(?=\s*Authority\/source:|$)/i);
    return m ? m[1].trim() : "—";
  }

  function parseMovement(t) {
    if (!t) return { label: "—", reason: "" };
    var m = t.match(/Movement:\s*([^—\n]+)\s*—\s*([^\n]+)/i);
    if (m) return { label: m[1].trim(), reason: m[2].trim() };
    m = t.match(/Movement:\s*([^\n]+)/i);
    return m ? { label: m[1].trim(), reason: "" } : { label: "—", reason: "" };
  }

  function parseRiskLevel(t) {
    if (!t) return "";
    var m = t.match(/\brisk\s+(low|medium|high)\b/i);
    return m ? m[1].toLowerCase() : "";
  }

  function parsePrimaryDriver(t) {
    if (!t) return "—";
    var m =
      t.match(/Controlling driver \(meeting packet\):\s*([^\n]+)/i) ||
      t.match(/Finish driver \(summary\):\s*([^\n]+)/i) ||
      t.match(/Finish driver detail:\s*([^—\n]+)/i);
    return m ? m[1].trim() : "—";
  }

  function parseTopDriversFromDom() {
    var block = document.querySelector('.pkt-section-block[data-section-key="key_drivers"]');
    if (!block) return [];
    var paras = block.querySelectorAll("p");
    var found = false;
    var out = [];
    for (var i = 0; i < paras.length; i++) {
      var pt = paras[i].textContent || "";
      if (/top schedule drivers/i.test(pt)) {
        found = true;
        var ul = paras[i].nextElementSibling;
        while (ul && ul.tagName !== "UL") ul = ul.nextElementSibling;
        if (ul && ul.tagName === "UL") {
          var lis = ul.querySelectorAll(":scope > li");
          for (var j = 0; j < lis.length && out.length < 5; j++) {
            var line = (lis[j].textContent || "").replace(/\s+/g, " ").trim();
            if (line) out.push(line);
          }
        }
        break;
      }
    }
    if (!found) {
      var lis = block.querySelectorAll("ul > li");
      for (var k = 0; k < lis.length && out.length < 5; k++) {
        var ln = (lis[k].textContent || "").replace(/\s+/g, " ").trim();
        if (ln && !/^driver comparison/i.test(ln)) out.push(ln);
      }
    }
    return out.slice(0, 5);
  }

  function parseCycles(full) {
    if (!full) return "—";
    var m =
      full.match(/(\d+)\s+schedule cycle/i) ||
      full.match(/(\d+)\s+cycle\(s\)\s+remain/i) ||
      full.match(/(\d+)\s+cycle\(s\)/i);
    return m ? m[1] : "—";
  }

  function parseOpenEnds(full) {
    if (!full) return "—";
    var m = full.match(/(\d+)\s+open starts and (\d+)\s+open finishes/i);
    if (m) return String(parseInt(m[1], 10) + parseInt(m[2], 10));
    m = full.match(/(\d+)\s+open-end condition/i);
    return m ? m[1] : "—";
  }

  function parseMargin(full) {
    if (!full) return "—";
    var m =
      full.match(/Margin[^0-9%]*([\d.]+)\s*%/i) ||
      full.match(/margin[^0-9%]*([\d.]+)\s*%/i) ||
      full.match(/\b([\d.]+)%\s*\(margin/i);
    return m ? m[1] + "%" : "—";
  }

  function riskClass(level) {
    var l = (level || "").toLowerCase();
    if (l === "high" || l === "critical") return "pkt-risk--high";
    if (l === "medium" || l === "watch") return "pkt-risk--medium";
    if (l === "low") return "pkt-risk--low";
    return "pkt-risk--unknown";
  }

  function decorateRiskItems() {
    var block = document.querySelector('.pkt-section-block[data-section-key="near_term_risks"]');
    if (!block) return;
    var lis = block.querySelectorAll("ul > li");
    lis.forEach(function (li) {
      if (li.classList.contains("pkt-risk-row")) return;
      var raw = li.innerHTML;
      var sev = "";
      var smHtml = raw.match(/<strong>(HIGH|CRITICAL|MEDIUM|LOW)\b/i);
      if (smHtml) sev = smHtml[1].toUpperCase();
      if (!sev) {
        var t = (li.textContent || "").trim();
        var mm = t.match(/^(HIGH|CRITICAL|MEDIUM|LOW)\b/i);
        if (mm) sev = mm[1].toUpperCase();
      }
      li.classList.add("pkt-risk-row");
      if (sev) {
        li.classList.add(riskClass(sev === "CRITICAL" ? "high" : sev.toLowerCase()));
        var barPct = sev === "HIGH" || sev === "CRITICAL" ? 100 : sev === "MEDIUM" ? 55 : sev === "LOW" ? 28 : 40;
        var badge = document.createElement("span");
        badge.className = "pkt-risk-badge " + riskClass(sev === "CRITICAL" ? "high" : sev.toLowerCase());
        badge.textContent = sev === "CRITICAL" ? "HIGH" : sev;
        var bar = document.createElement("span");
        bar.className = "pkt-risk-meter";
        bar.setAttribute("aria-hidden", "true");
        var fill = document.createElement("span");
        fill.className = "pkt-risk-meter__fill";
        fill.style.width = barPct + "%";
        bar.appendChild(fill);
        var inner = document.createElement("div");
        inner.className = "pkt-risk-row__inner";
        while (li.firstChild) inner.appendChild(li.firstChild);
        li.appendChild(inner);
        inner.insertBefore(badge, inner.firstChild);
        inner.insertBefore(bar, inner.firstChild.nextSibling);
      }
    });
  }

  function actionPriorityFromLi(li) {
    var html = li.innerHTML;
    var m = html.match(/\((high|medium|low)\)/i);
    if (m) return m[1].toLowerCase();
    var t = li.textContent || "";
    if (/\(high\)/i.test(t)) return "high";
    if (/\(medium\)/i.test(t)) return "medium";
    if (/\(low\)/i.test(t)) return "low";
    return "unspecified";
  }

  function decorateActionRegister() {
    var blocks = document.querySelectorAll(".pkt-action-register-prose");
    blocks.forEach(function (block) {
      var h3s = block.querySelectorAll("h3");
      h3s.forEach(function (h3) {
        h3.classList.add("pkt-action-group-title");
      });
      var lis = block.querySelectorAll("ul > li");
      lis.forEach(function (li) {
        li.classList.add("pkt-action-card");
        var pr = actionPriorityFromLi(li);
        li.setAttribute("data-priority", pr);
        var strong = li.querySelector("strong");
        if (strong) {
          var sm = document.createElement("span");
          sm.className = "pkt-action-card__role";
          sm.textContent = strong.textContent.replace(/\s*\((high|medium|low)\)\s*:?\s*$/i, "").trim();
          var rest = document.createElement("div");
          rest.className = "pkt-action-card__body";
          var node = strong.nextSibling;
          while (node) {
            var next = node.nextSibling;
            rest.appendChild(node);
            node = next;
          }
          li.textContent = "";
          var head = document.createElement("div");
          head.className = "pkt-action-card__head";
          var tag = document.createElement("span");
          tag.className = "pkt-priority-tag pkt-priority-tag--" + pr;
          tag.textContent = pr === "unspecified" ? "Priority" : pr.toUpperCase();
          head.appendChild(tag);
          head.appendChild(sm);
          li.appendChild(head);
          li.appendChild(rest);
        }
      });
    });
    groupActionsByPriority();
  }

  function decorateRequiredDecisions() {
    var block = document.querySelector('.pkt-section-block[data-section-key="required_decisions"] .pkt-prose');
    if (!block) return;
    var lis = block.querySelectorAll("ul > li");
    lis.forEach(function (li) {
      li.classList.add("pkt-action-card", "pkt-action-card--compact");
      li.setAttribute("data-priority", "high");
      if (!li.querySelector(".pkt-priority-tag")) {
        var tag = document.createElement("span");
        tag.className = "pkt-priority-tag pkt-priority-tag--high";
        tag.textContent = "DECISION";
        li.insertBefore(tag, li.firstChild);
      }
    });
  }

  function fillRail() {
    var ulR = document.getElementById("pkt-rail-risks");
    var ulA = document.getElementById("pkt-rail-actions");
    var stFinish = document.getElementById("pkt-rail-stat-finish");
    var stRisk = document.getElementById("pkt-rail-stat-risk");
    var stMove = document.getElementById("pkt-rail-stat-movement");
    if (ulR) {
      ulR.innerHTML = "";
      var block = document.querySelector('.pkt-section-block[data-section-key="near_term_risks"]');
      if (block) {
        var items = block.querySelectorAll("ul > li");
        var n = 0;
        items.forEach(function (li) {
          if (n >= 4) return;
          var line = (li.textContent || "").replace(/\s+/g, " ").trim();
          if (line.length < 4) return;
          var li2 = document.createElement("li");
          li2.textContent = line.length > 220 ? line.slice(0, 217) + "…" : line;
          ulR.appendChild(li2);
          n++;
        });
      }
      if (!ulR.children.length) {
        var empty = document.createElement("li");
        empty.className = "pkt-rail-empty";
        empty.textContent = "No elevated risks listed in packet.";
        ulR.appendChild(empty);
      }
    }
    if (ulA) {
      ulA.innerHTML = "";
      var ab = document.querySelector(".pkt-action-register-prose");
      if (ab) {
        var alis = ab.querySelectorAll("ul > li");
        var na = 0;
        alis.forEach(function (li) {
          if (na >= 5) return;
          var line = (li.textContent || "").replace(/\s+/g, " ").trim();
          if (!line) return;
          var li3 = document.createElement("li");
          li3.textContent = line.length > 200 ? line.slice(0, 197) + "…" : line;
          ulA.appendChild(li3);
          na++;
        });
      }
      if (!ulA.children.length) {
        var dec = document.querySelector('.pkt-section-block[data-section-key="required_decisions"]');
        if (dec) {
          dec.querySelectorAll("ul > li").forEach(function (li, idx) {
            if (idx >= 5) return;
            var line = (li.textContent || "").replace(/\s+/g, " ").trim();
            if (!line) return;
            var li4 = document.createElement("li");
            li4.textContent = line;
            ulA.appendChild(li4);
          });
        }
      }
      if (!ulA.children.length) {
        var e2 = document.createElement("li");
        e2.className = "pkt-rail-empty";
        e2.textContent = "No queued actions surfaced.";
        ulA.appendChild(e2);
      }
    }
    var finish = parseProjectedFinish(textSection("finish_milestone_outlook"));
    var risk = parseRiskLevel(textSection("executive_summary"));
    var mov = parseMovement(textSection("delta_vs_prior"));
    if (stFinish) stFinish.textContent = finish;
    if (stRisk) stRisk.textContent = risk ? risk.toUpperCase() : "—";
    if (stMove) stMove.textContent = mov.label;
  }

  function fillDriverHighlightFixed(primary, topList) {
    var mount = document.getElementById("pkt-driver-highlight-mount");
    if (!mount) return;
    mount.innerHTML = "";
    if (primary === "—" && (!topList || !topList.length)) {
      mount.hidden = true;
      return;
    }
    mount.hidden = false;
    if (primary !== "—") {
      var pri = document.createElement("div");
      pri.className = "pkt-driver-primary";
      var lb = document.createElement("span");
      lb.className = "pkt-driver-primary__label";
      lb.textContent = "Primary driver";
      var val = document.createElement("span");
      val.className = "pkt-driver-primary__value";
      val.textContent = primary;
      pri.appendChild(lb);
      pri.appendChild(val);
      mount.appendChild(pri);
    }
    if (topList.length) {
      var cap = document.createElement("div");
      cap.className = "pkt-driver-top-caption";
      cap.textContent = "Top schedule drivers";
      mount.appendChild(cap);
      var ol = document.createElement("ol");
      ol.className = "pkt-driver-top-list";
      topList.forEach(function (item) {
        var li = document.createElement("li");
        li.textContent = item;
        ol.appendChild(li);
      });
      mount.appendChild(ol);
    }
  }

  function groupActionsByPriority() {
    document.querySelectorAll(".pkt-action-register-prose ul").forEach(function (ul) {
      var items = Array.prototype.slice.call(ul.querySelectorAll(":scope > li.pkt-action-card"));
      var order = { high: 0, medium: 1, low: 2, unspecified: 3 };
      items.sort(function (a, b) {
        var pa = order[a.getAttribute("data-priority") || "unspecified"];
        var pb = order[b.getAttribute("data-priority") || "unspecified"];
        return pa - pb;
      });
      items.forEach(function (li) {
        ul.appendChild(li);
      });
    });
  }

  function run() {
    var exec = textSection("executive_summary");
    var finish = textSection("finish_milestone_outlook");
    var delta = textSection("delta_vs_prior");
    var drivers = textSection("key_drivers");
    var fullScan = [exec, finish, delta, drivers, textSection("near_term_risks")].join("\n");

    var finishDate = parseProjectedFinish(finish);
    var movement = parseMovement(delta);
    var risk = parseRiskLevel(exec);
    var riskUpper = risk ? risk.toUpperCase() : "—";
    var topDrivers = parseTopDriversFromDom();
    var primary = parsePrimaryDriver(drivers);
    if (primary === "—" && topDrivers.length) primary = topDrivers[0];
    var statusLabel = movement.label;

    setText("pkt-cmd-finish", finishDate);
    var deltaFull = movement.label + (movement.reason ? " — " + movement.reason : "");
    setText("pkt-cmd-delta", deltaFull);
    var deltaEl = document.getElementById("pkt-cmd-delta");
    if (deltaEl && deltaFull.length > 180) deltaEl.setAttribute("title", deltaFull);
    var riskPill = document.getElementById("pkt-cmd-risk");
    if (riskPill) {
      riskPill.textContent = riskUpper;
      riskPill.className = "pkt-risk-pill pkt-risk-pill--command " + riskClass(risk);
    }
    setText("pkt-cmd-driver", primary);
    setText("pkt-cmd-status", statusLabel);

    var strip = document.getElementById("pkt-command-strip");
    if (strip) strip.setAttribute("data-risk", risk || "unknown");

    setText("pkt-kpi-finish", finishDate);
    setText("pkt-kpi-delta", movement.label);
    var kpiRisk = document.getElementById("pkt-kpi-risk");
    if (kpiRisk) {
      kpiRisk.textContent = riskUpper;
      kpiRisk.className =
        "pkt-kpi-card__value pkt-kpi-card__value--hero pkt-kpi-card__value--risk " + riskClass(risk);
    }
    setText("pkt-kpi-cycles", parseCycles(fullScan));
    setText("pkt-kpi-open-ends", parseOpenEnds(fullScan));
    setText("pkt-kpi-margin", parseMargin(fullScan));

    fillDriverHighlightFixed(primary, topDrivers);
    decorateRiskItems();
    decorateActionRegister();
    decorateRequiredDecisions();
    fillRail();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
