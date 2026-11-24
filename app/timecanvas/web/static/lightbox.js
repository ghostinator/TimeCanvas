// Pop-up viewer for frames, videos and the live stream (CSP: external script, no inline handlers).
// Plain left-click opens it; Cmd/Ctrl/Shift/middle-click keep their normal browser meaning (new tab, range-select).
(function () {
  var dlg, stage, cap, items = [], idx = 0;
  function build() {
    dlg = document.createElement("dialog"); dlg.className = "lb"; dlg.setAttribute("aria-label", "Viewer");
    dlg.innerHTML = '<button type="button" class="lb-x" aria-label="Close">×</button><button type="button" class="lb-nav lb-prev" aria-label="Previous">‹</button>' +
      '<button type="button" class="lb-nav lb-next" aria-label="Next">›</button><div class="lb-stage"></div><div class="lb-cap"></div>';
    document.body.appendChild(dlg);
    stage = dlg.querySelector(".lb-stage"); cap = dlg.querySelector(".lb-cap");
    dlg.addEventListener("click", function (e) {
      if (e.target === dlg || e.target.classList.contains("lb-x")) dlg.close();
      else if (e.target.classList.contains("lb-prev")) step(-1);
      else if (e.target.classList.contains("lb-next")) step(1);
    });
    dlg.addEventListener("close", function () { stage.textContent = ""; });
    dlg.addEventListener("keydown", function (e) {
      if (e.target.tagName === "VIDEO") return;           // arrows seek inside a video
      if (e.key === "ArrowLeft") { step(-1); e.preventDefault(); } else if (e.key === "ArrowRight") { step(1); e.preventDefault(); }
    });
  }
  function show(i) {
    var a = items[i], kind = a.getAttribute("data-lb"), el;
    idx = i; stage.textContent = "";
    if (kind === "video") { el = document.createElement("video"); el.controls = true; el.autoplay = true; el.src = a.getAttribute("href"); }
    else { el = document.createElement("img"); el.src = kind === "stream" ? "/live/stream" : a.getAttribute("href"); el.alt = a.getAttribute("data-cap") || ""; }
    stage.appendChild(el);
    var dl = kind === "stream" ? "" : ' · <a href="' + a.getAttribute("href") + (a.getAttribute("href").indexOf("?") < 0 ? "?dl=1" : "&dl=1") + '">download</a>';
    cap.textContent = (a.getAttribute("data-cap") || "") + (items.length > 1 ? "  (" + (i + 1) + "/" + items.length + ")" : "");
    cap.insertAdjacentHTML("beforeend", dl);
    dlg.classList.toggle("single", items.length < 2);
  }
  function step(d) { if (items.length > 1) show((idx + d + items.length) % items.length); }
  window.tcOpenViewer = function (a) {
    if (!dlg) build();
    var kind = a.getAttribute("data-lb");
    items = kind === "stream" ? [a] : [].slice.call(document.querySelectorAll('a[data-lb]:not([data-lb=stream])'));
    show(Math.max(0, items.indexOf(a)));
    if (!dlg.open) dlg.showModal();
  };
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[data-lb]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault(); window.tcOpenViewer(a);
  });
})();
