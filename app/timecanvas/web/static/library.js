// bulk selection + confirmation for destructive buttons (CSP forbids inline handlers)
(function () {
  var all = document.getElementById("selall"), count = document.getElementById("selcount");
  function boxes() { return Array.prototype.slice.call(document.querySelectorAll("input[name=ids]")); }
  function update() { if (count) count.textContent = boxes().filter(function (b) { return b.checked; }).length + " selected"; }
  if (all) all.addEventListener("change", function () { boxes().forEach(function (b) { b.checked = all.checked; }); update(); });
  document.addEventListener("change", function (e) { if (e.target.name === "ids") update(); });
  document.addEventListener("click", function (e) {
    var b = e.target.closest("button[data-confirm]");
    if (!b) return;
    if (!window.confirm(b.getAttribute("data-confirm"))) { e.preventDefault(); return; }
    var f = b.form; if (f && f.elements.confirm) f.elements.confirm.value = "yes";
  });
  // an action with nothing selected is a mistake, not a no-op
  var bulk = document.getElementById("bulk");
  if (bulk) bulk.addEventListener("submit", function (e) { if (!boxes().some(function (b) { return b.checked; })) { e.preventDefault(); window.alert("Select at least one item first."); } });
})();
// shift-click range select + keyboard navigation over the tiles (frames) or rows (videos)
(function () {
  var cur = null, anchor = null;
  function items() { return Array.prototype.slice.call(document.querySelectorAll(".thumbs figure, table.vids tr")).filter(function (i) { return i.querySelector("input[name=ids]"); }); }
  function box(i) { return i.querySelector("input[name=ids]"); }
  function fire(b) { b.dispatchEvent(new Event("change", { bubbles: true })); }
  function range(a, b, want) {
    var l = items(), i = l.indexOf(a), j = l.indexOf(b); if (i < 0 || j < 0) return;
    l.slice(Math.min(i, j), Math.max(i, j) + 1).forEach(function (it) { box(it).checked = want; }); fire(box(b));
  }
  function setCur(it) {
    if (cur) cur.classList.remove("cur");
    cur = it; if (cur) { cur.classList.add("cur"); cur.scrollIntoView({ block: "nearest" }); }
  }
  document.addEventListener("click", function (e) {
    var it = e.target.closest && e.target.closest(".thumbs figure, table.vids tr");
    if (!it || !box(it) || e.target.closest("button, select")) return;
    var onBox = e.target === box(it);
    if (e.shiftKey && anchor && document.contains(anchor)) {
      if (!onBox) e.preventDefault();                       // shift-click on a link must not open a new window
      var want = onBox ? box(it).checked : !box(it).checked;
      window.getSelection().removeAllRanges(); range(anchor, it, want); setCur(it);
    } else if (onBox) { anchor = it; setCur(it); }
  }, true);
  document.addEventListener("keydown", function (e) {
    if (document.querySelector("dialog[open]") || /^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(e.target.tagName) && e.key !== "Escape") return;
    var l = items(); if (!l.length) return;
    var k = e.key, mod = e.metaKey || e.ctrlKey;
    if (mod && k.toLowerCase() === "a") { e.preventDefault(); l.forEach(function (i) { box(i).checked = true; }); fire(box(l[0])); return; }
    if (k === "Escape") { l.forEach(function (i) { box(i).checked = false; }); fire(box(l[0])); setCur(null); return; }
    if (mod || e.altKey) return;
    var i = cur ? l.indexOf(cur) : -1, cols = 1;
    if (l[0].classList.contains("pick") || l[0].tagName === "FIGURE") { var top = l[0].offsetTop; cols = l.filter(function (x) { return x.offsetTop === top; }).length || 1; }
    var d = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols }[k];
    if (d !== undefined) {
      e.preventDefault(); var n = Math.max(0, Math.min(l.length - 1, i < 0 ? 0 : i + d));
      if (e.shiftKey) { if (!anchor) anchor = l[Math.max(i, 0)]; range(anchor, l[n], true); }
      else anchor = l[n];
      setCur(l[n]);
    } else if (k === " " && cur) { e.preventDefault(); box(cur).checked = !box(cur).checked; anchor = cur; fire(box(cur)); }
    else if (k === "Enter" && cur) { var a = cur.querySelector("a[data-lb]"); if (a) { e.preventDefault(); window.tcOpenViewer(a); } }
  });
})();
// CSP forbids inline handlers: selects marked data-autosubmit submit their form on change
document.addEventListener("change", function (e) { if (e.target.hasAttribute && e.target.hasAttribute("data-autosubmit")) e.target.form.submit(); });
