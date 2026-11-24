// range outputs, stream reload after a mode change, fullscreen for the live view
document.addEventListener("input", function (e) {
  if (e.target.type === "range" && e.target.nextElementSibling) e.target.nextElementSibling.value = e.target.value;
});
function reloadStream() {
  var img = document.getElementById("preview");
  if (img) img.src = "/live/stream?" + Date.now();
}
document.body.addEventListener("stream-restarted", function () { setTimeout(reloadStream, 1500); setTimeout(reloadStream, 5000); });
var fs = document.getElementById("fs");
function toggleFs() {
  var img = document.getElementById("preview");
  if (document.fullscreenElement) document.exitFullscreen(); else if (img && img.requestFullscreen) img.requestFullscreen();
}
if (fs) fs.addEventListener("click", toggleFs);
document.addEventListener("keydown", function (e) { if (e.key === "f" && fs && !/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) toggleFs(); });
