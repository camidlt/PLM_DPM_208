// Baie de cellules en direct : interroge le serveur toutes les 2 s et anime chaque module
// avec une balistique pondérée (masse, amortissement, léger dépassement), jamais un saut instantané.
(function () {
  var roots = document.querySelectorAll("[data-live]");
  if (!roots.length) return;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var LABEL = { OK: "Nominal", WARNING: "Surveillance", CRITICAL: "Critique" };

  function fmtTs(v) {
    if (!v) return "";
    var s = String(v).replace("Z", "").split("T");
    if (s.length < 2) return v;
    var d = s[0].split("-");
    return "Dernière mesure " + d[2] + "/" + d[1] + "/" + d[0] + " " + s[1].slice(0, 8);
  }

  function Cell(el) {
    this.el = el;
    this.max = parseFloat(el.dataset.max) || 2;
    this.cur = parseFloat(el.dataset.r) || 0;
    this.target = this.cur;
    this.vel = 0;
    this.val = el.querySelector("[data-val]");
    this.fill = el.querySelector(".fill");
    this.trace = el.querySelector("svg.trace polyline");
    this.health = el.querySelector("[data-health-label]");
    this.temp = el.querySelector("[data-temp]");
    el.style.setProperty("--maxp", "50%");
    this.paint();
  }
  Cell.prototype.pct = function (r) { return Math.max(0, Math.min(100, r / (this.max * 2) * 100)); };
  Cell.prototype.paint = function () {
    var p = this.pct(this.cur);
    this.fill.style.height = p.toFixed(1) + "%";
    this.el.style.setProperty("--w", p.toFixed(1) + "%");
    this.val.textContent = Math.max(0, this.cur).toFixed(2);
  };
  // ressort amorti : k raideur, c amortissement (sous-critique, donc léger dépassement)
  Cell.prototype.step = function (dt) {
    var k = 70, c = 11;
    var a = k * (this.target - this.cur) - c * this.vel;
    this.vel += a * dt;
    this.cur += this.vel * dt;
    if (Math.abs(this.target - this.cur) < 0.002 && Math.abs(this.vel) < 0.01) {
      this.cur = this.target; this.vel = 0; this.paint(); return false;
    }
    this.paint();
    return true;
  };
  Cell.prototype.update = function (m) {
    if (m.rmax) this.max = m.rmax;
    if (m.r !== null && m.r !== undefined) this.target = m.r;
    var h = m.health || "OK";
    this.el.dataset.health = h;
    if (this.health) this.health.textContent = LABEL[h] || h;
    if (this.temp && m.t !== null && m.t !== undefined) this.temp.textContent = Number(m.t).toFixed(1) + " °C";
    if (this.trace && m.points && m.points.length > 1) {
      var self = this, n = m.points.length;
      this.trace.setAttribute("points", m.points.map(function (pt, i) {
        var y = 30 - self.pct(pt.r) * 0.3;
        return (i / (n - 1) * 100).toFixed(1) + "," + y.toFixed(1);
      }).join(" "));
    }
    if (reduce) { this.cur = this.target; this.paint(); }
  };

  roots.forEach(function (root) {
    var cells = {};
    root.querySelectorAll(".cell[data-index]").forEach(function (el) { cells[el.dataset.index] = new Cell(el); });
    var dev = root.querySelector("[data-device]");
    var summary = root.querySelector("[data-summary]");
    var running = false, last = 0;

    function loop(t) {
      var dt = Math.min(0.05, (t - last) / 1000 || 0.016);
      last = t;
      var moving = false;
      Object.keys(cells).forEach(function (k) { if (cells[k].step(dt)) moving = true; });
      if (moving) requestAnimationFrame(loop); else running = false;
    }
    function kick() { if (!running && !reduce) { running = true; last = performance.now(); requestAnimationFrame(loop); } }

    var trend = root.querySelector("[data-trend]");

    function apply(data) {
      if (!data || !data.modules) return;
      var over = 0, overIdx = [];
      data.modules.forEach(function (m) {
        if (cells[m.index]) cells[m.index].update(m);
        if (m.r !== null && m.rmax && m.r > m.rmax) { over++; overIdx.push(m.index); }
      });
      if (trend) drawTrend(trend, data);
      refreshReport(overIdx.join(","));
      if (summary) {
        summary.textContent = over ? over + (over > 1 ? " modules hors seuil" : " module hors seuil") : "Modules dans les tolérances";
        summary.className = "badge " + (over ? "st-Waste" : "st-RECEIVED");
      }
      if (dev) {
        dev.dataset.online = data.online ? "true" : "false";
        dev.querySelector("[data-dev-state]").textContent = data.online ? "BMS ESP32 en ligne" : "BMS hors ligne";
        var d = data.device;
        dev.querySelector("[data-dev-detail]").textContent = d
          ? d.source + " · " + d.packets + " paquets · vu il y a " + Math.round(d.ageSeconds) + " s"
          : "En attente de l'ESP32 sur /api/telemetry";
        dev.querySelector("[data-dev-last]").textContent = fmtTs(data.lastTelemetryAt);
      }
      kick();
    }

    function poll() {
      if (document.hidden) return;
      fetch(root.dataset.live, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(apply)
        .catch(function () {});
    }
    poll();
    setInterval(poll, 2000);
  });

  // Garagiste : quand la liste des modules hors seuil change, le panneau de diagnostic
  // (alerte rouge et formulaire prérempli) est rechargé, sauf si l'utilisateur est en train de saisir.
  function refreshReport(overNow) {
    var report = document.getElementById("report");
    if (!report || report.dataset.alerts === undefined || report.dataset.alerts === overNow) return;
    var active = document.activeElement;
    if (active && report.contains(active) && /INPUT|TEXTAREA|SELECT/.test(active.tagName)) return;
    report.dataset.alerts = overNow;   // une seule fois par changement
    fetch(window.location.pathname, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (html) {
        if (!html) return;
        var fresh = new DOMParser().parseFromString(html, "text/html").getElementById("report");
        if (fresh) { report.replaceWith(fresh); document.dispatchEvent(new Event("report:refreshed")); }
      }).catch(function () {});
  }

  // Courbe de tendance : une polyligne par module, seuil constructeur en pointillés
  var NS = "http://www.w3.org/2000/svg";
  var SERIES = ["#e6edf3", "#12abdb", "#7790a8", "#4f9fd6", "#afc0cf", "#2f8fb8"];
  var W = 640, H = 220, L = 40, R = 40, T = 14, B = 26;

  function el(name, attrs, text) {
    var n = document.createElementNS(NS, name);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text !== undefined) n.textContent = text;
    return n;
  }
  // étiquette d'axe : la date si les relevés couvrent plusieurs jours, sinon l'heure
  function stamp(ts, multiDay) {
    var p = String(ts || "").split("T"), d = (p[0] || "").split("-");
    return multiDay ? d[2] + "/" + d[1] + "/" + d[0] : (p[1] || "").slice(0, 8);
  }

  function drawTrend(box, data) {
    var svg = box.querySelector(":scope > svg");   // pas l'icône du titre
    var mods = data.modules.filter(function (m) { return m.points && m.points.length; });
    var meta = box.querySelector("[data-trend-meta]");
    if (!mods.length) return;
    var n = Math.max.apply(null, mods.map(function (m) { return m.points.length; }));
    var rmax = Math.max.apply(null, data.modules.map(function (m) { return m.rmax || 0; }));
    var top = rmax * 1.2;
    mods.forEach(function (m) { m.points.forEach(function (p) { if (p.r > top) top = p.r; }); });
    top = Math.ceil(top * 1.1 * 2) / 2;
    var x = function (i, len) { return L + (len > 1 ? i / (len - 1) : 1) * (W - L - R); };
    var y = function (r) { return T + (1 - r / top) * (H - T - B); };

    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var grid = el("g", { "class": "grid" }), axis = el("g", { "class": "axis" });
    var step = top <= 3 ? 0.5 : (top <= 8 ? 1 : 2);
    for (var v = 0; v <= top + 1e-9; v += step) {
      grid.appendChild(el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v) }));
      axis.appendChild(el("text", { x: L - 6, y: y(v) + 3, "text-anchor": "end" }, v.toFixed(v % 1 ? 1 : 0)));
    }
    var first = mods[0].points[0], lastP = mods[0].points[mods[0].points.length - 1];
    var multiDay = String(first.ts).slice(0, 10) !== String(lastP.ts).slice(0, 10);
    axis.appendChild(el("text", { x: L, y: H - 6 }, stamp(first.ts, multiDay)));
    axis.appendChild(el("text", { x: W - R, y: H - 6, "text-anchor": "end" }, stamp(lastP.ts, multiDay)));
    axis.appendChild(el("text", { x: 4, y: T + 2 }, "mΩ"));
    svg.appendChild(grid); svg.appendChild(axis);

    if (rmax) {
      svg.appendChild(el("line", { "class": "limit", x1: L, x2: W - R, y1: y(rmax), y2: y(rmax) }));
      svg.appendChild(el("text", { "class": "limit-label", x: L + 6, y: y(rmax) - 5 }, "seuil max " + rmax + " mΩ"));
    }
    var ends = el("g", { "class": "end" }), labels = [];
    mods.forEach(function (m, k) {
      var hot = m.health === "CRITICAL" || (m.rmax && m.r > m.rmax);
      var color = hot ? "var(--hot)" : (m.health === "WARNING" ? "var(--warn)" : SERIES[k % SERIES.length]);
      var len = m.points.length, off = n - len;
      var pts = m.points.map(function (p, i) { return x(i + off, n).toFixed(1) + "," + y(p.r).toFixed(1); }).join(" ");
      svg.appendChild(el("polyline", { "class": "series" + (hot ? " over" : ""), points: pts, stroke: color }));
      var lp = m.points[len - 1];
      ends.appendChild(el("circle", { cx: x(n - 1, n), cy: y(lp.r), r: 3, fill: color }));
      labels.push({ y: y(lp.r) + 3, color: color, text: "M" + m.index });
    });
    // étiquettes de fin de courbe : écartées d'au moins 11 px pour rester lisibles
    labels.sort(function (a, b) { return a.y - b.y; });
    for (var i = 1; i < labels.length; i++) {
      if (labels[i].y - labels[i - 1].y < 11) labels[i].y = labels[i - 1].y + 11;
    }
    labels.forEach(function (lb) { ends.appendChild(el("text", { x: W - R + 8, y: lb.y, fill: lb.color }, lb.text)); });
    svg.appendChild(ends);
    if (meta) meta.textContent = n + " relevés par module" + (data.readings ? " · " + data.readings + " trames dans le graphe" : "");
  }
})();
