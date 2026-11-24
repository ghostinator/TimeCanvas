// plays a time range of captured frames in the browser (CSP: no inline script)
// Load starts fetching every frame in the background (a few at a time, nearest the playhead first);
// playback waits on a frame that has not arrived yet instead of skipping it.
(function () {
  var $ = function (i) { return document.getElementById(i); };
  var PARALLEL = 8;   // nginx speaks HTTP/2, so these share one connection; the server answers a frame in a few ms, the network path is the limit
  var frames = [], idx = 0, timer = null;
  var st = [], tries = [], done = 0, busy = 0, cursor = 0, gen = 0;   // st: 0 waiting, 1 loading, 2 loaded (or gave up), 3 cooling off before a retry
  function url(j) { return "/media/" + frames[j][0] + "/file"; }
  function progress() {
    var n = frames.length, all = done >= n;
    $("pload").max = n; $("pload").value = done;
    $("pbuftxt").textContent = all ? "all " + n + " frames loaded" : "loading frames " + done + "/" + n;
    $("pbuf").hidden = !n;
  }
  function pump() {
    var g = gen, n = frames.length;
    while (busy < PARALLEL && done + busy < n) {
      var j = -1;
      for (var k = 0; k < n; k++) { var c = (cursor + k) % n; if (st[c] === 0) { j = c; break; } }
      if (j < 0) return;
      st[j] = 1; busy++;
      (function (j) {
        var im = new Image();
        im.onload = function () { if (g !== gen) return; st[j] = 2; busy--; done++; progress(); pump(); };
        im.onerror = function () {   // e.g. nginx rate limit: try again shortly, give up after 3 tries so playback never hangs
          if (g !== gen) return; busy--;
          if (++tries[j] < 3) { st[j] = 3; setTimeout(function () { if (g === gen) { st[j] = 0; pump(); } }, 1000); } else { st[j] = 2; done++; progress(); pump(); }
        };
        im.src = url(j);   // the browser cache keeps it for the viewer; no reference is held here
      })(j);
    }
  }
  function show(i) {
    idx = i; cursor = i; $("pseek").value = i;
    $("pimg").src = url(i); $("pstamp").textContent = frames[i][1] + "  (" + (i + 1) + "/" + frames.length + ")";
    pump();
  }
  function stop() { if (timer) clearInterval(timer); timer = null; $("pplay").textContent = "▶ Play"; }
  function start() {
    stop(); $("pplay").textContent = "⏸ Pause";
    timer = setInterval(function () {
      var nx = idx + 1 >= frames.length ? ($("ploop").checked ? 0 : -1) : idx + 1;
      if (nx < 0) { stop(); return; }
      if (st[nx] !== 2) { cursor = nx; pump(); return; }   // not here yet: hold this frame and fetch the next one first
      show(nx);
    }, 1000 / +$("pfps").value);
  }
  $("range").addEventListener("submit", function (e) {
    e.preventDefault(); stop(); gen++; frames = []; st = []; done = busy = cursor = 0; progress();
    var q = "start=" + encodeURIComponent($("pstart").value) + "&end=" + encodeURIComponent($("pend").value) + "&step=" + $("pstep").value;
    fetch("/play/frames?" + q, { credentials: "same-origin" }).then(function (r) { if (!r.ok) throw 0; return r.json(); }).then(function (j) {
      frames = j.frames; st = frames.map(function () { return 0; }); tries = frames.map(function () { return 0; });
      $("pinfo").textContent = j.total + " frames in range" + (j.step > 1 ? ", showing every " + j.step + "th" : "");
      $("player").hidden = !frames.length; $("saveform").hidden = !j.total;
      $("sstart").value = $("pstart").value; $("send").value = $("pend").value;
      if (frames.length) { $("pseek").max = frames.length - 1; progress(); show(0); }
    }).catch(function () { $("pinfo").textContent = "Could not load that range (end must be after start)."; });
  });
  $("pplay").addEventListener("click", function () { timer ? stop() : start(); });
  $("pseek").addEventListener("input", function () { show(+this.value); });
  $("pfps").addEventListener("change", function () { $("sfps").value = this.value; if (timer) start(); });
  $("sfps").value = $("pfps").value;
})();
