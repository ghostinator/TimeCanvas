"""TimeCanvas dashboard (FastAPI + Jinja2 + HTMX). Binds to 127.0.0.1; nginx provides TLS + Basic Auth and sets X-Remote-User."""
import json, os, re, secrets, subprocess, urllib.request
from html import escape as html_escape
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, available_timezones

from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import alerts, archive, cleanup, config as cfgmod, db, files, helperclient, paths, reconcile, render, v4l2, version

HERE = os.path.dirname(__file__)
async def csrf_check(request: Request):
    """CSRF for all state-changing requests: double-submit cookie (form field or X-CSRF-Token header) + same-origin check."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    sent = request.headers.get("x-csrf-token") or (await request.form()).get("csrf")
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin and re.sub(r"^https?://", "", origin).split("/")[0] != request.headers.get("host"):
        raise HTTPException(403, "bad origin")
    if not sent or not secrets.compare_digest(str(sent), request.cookies.get("tc_csrf", "")):
        raise HTTPException(403, "csrf check failed")


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, dependencies=[Depends(csrf_check)])
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
T = Jinja2Templates(directory=os.path.join(HERE, "templates"))
HELPER = "/run/timecanvas-helper.sock"
TS = render.TS
PRESETS = sorted(render.PRESETS)


# ---------- plumbing ----------
def cfg():
    return cfgmod.load()


def conn():
    return db.connect(cfg()["storage"]["db"])


helper = helperclient.call


@app.middleware("http")
async def guard(request: Request, call_next):
    # Auth (defence in depth): nginx authenticates and sets X-Remote-User; refuse anything without it.
    if not request.headers.get("x-remote-user"):
        return PlainTextResponse("authentication required", status_code=401)
    token = request.cookies.get("tc_csrf") or secrets.token_urlsafe(24)  # secret-scan: allow (generates a CSRF token)
    request.state.csrf = token
    resp = await call_next(request)
    resp.set_cookie("tc_csrf", token, secure=True, samesite="strict", httponly=False, path="/")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'"
    return resp


def page(request, name, **kw):
    return T.TemplateResponse(request, name, {"csrf": request.state.csrf, "version": version(), "user": request.headers.get("x-remote-user"),
                                              "msg": request.query_params.get("msg"), **kw})


def back(url, msg):
    from urllib.parse import quote
    return RedirectResponse(f"{url}{'&' if '?' in url else '?'}msg={quote(msg)}", status_code=303)


async def form_of(request):
    return {k: v for k, v in (await request.form()).items() if isinstance(v, str)}


def audit(c, request, action, detail=""):
    c.execute("INSERT INTO audit_events(ts_utc,actor,action,detail) VALUES(?,?,?,?)", (db.utcnow(), request.headers.get("x-remote-user"), action, detail[:500]))
    c.commit()


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024


T.env.filters["human"] = human


def local(ts, tz, fmt="%Y-%m-%d %H:%M:%S"):
    if not ts:
        return "-"
    return datetime.strptime(ts, TS).replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz)).strftime(fmt)


T.env.filters["local"] = lambda ts, tz="America/Denver": local(ts, tz)


# ---------- overview ----------
def svc(unit):
    r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=5)
    return r.stdout.strip() or "unknown"


def status_data(c):
    ecfg = cfgmod.effective(cfg(), c)
    tz = ecfg["timezone"]
    st = json.loads(db.get_setting(c, "status") or "{}")
    last = c.execute("SELECT * FROM capture_events ORDER BY id DESC LIMIT 1").fetchone()
    last_ok = c.execute("SELECT ts_utc FROM capture_events WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
    iv = max(10, min(3600, ecfg["capture"]["interval_seconds"]))
    now = datetime.now(timezone.utc)
    nxt = (int(now.timestamp() // iv) + 1) * iv
    s, e = render.day_range(datetime.now(ZoneInfo(tz)).date(), tz)
    today = c.execute("SELECT COUNT(*) FROM capture_events WHERE status='ok' AND ts_utc>=? AND ts_utc<?", (render.fmt(s), render.fmt(e))).fetchone()[0]
    avg = c.execute("SELECT AVG(size_bytes) FROM (SELECT size_bytes FROM media_files WHERE media_type='image' AND status='ok' ORDER BY id DESC LIMIT 500)").fetchone()[0] or 190000
    per_day = 86400 / iv * avg
    age = int(now.timestamp() - datetime.strptime(last_ok[0], TS).replace(tzinfo=timezone.utc).timestamp()) if last_ok else None
    job = c.execute("SELECT id,kind,progress FROM render_jobs WHERE status='running' ORDER BY id DESC LIMIT 1").fetchone()
    vid = c.execute("SELECT id,ts_utc FROM media_files WHERE media_type='video' AND status='ok' ORDER BY id DESC LIMIT 1").fetchone()
    cut = render.fmt(now - timedelta(hours=24))
    errs = c.execute("SELECT ts_utc,level,source,message FROM health_events WHERE level IN ('warning','error','critical') AND ts_utc>=? ORDER BY id DESC LIMIT 8", (cut,)).fetchall()
    older = c.execute("SELECT COUNT(*) FROM health_events WHERE level IN ('warning','error','critical') AND ts_utc<?", (cut,)).fetchone()[0]
    pct = st.get("disk_pct", 0)
    return {"st": st, "last": last, "age": age, "next_in": int(nxt - now.timestamp()), "today": today, "job": job, "video": vid, "errs": errs, "older": older,
            "disk_pct": pct, "disk_free": st.get("disk_free_bytes", 0), "days_left": int(st.get("disk_free_bytes", 0) / per_day) if per_day else None,
            "disk_class": "crit" if pct >= ecfg["storage"]["disk_critical_percent"] else "warn" if pct >= ecfg["storage"]["disk_warning_percent"] else "ok",
            "services": {u: svc(f"timecanvas-{u}") for u in ("ustreamer.service", "capture.timer", "render-worker.service", "web.service", "health.timer")},
            "tz": tz}


@app.get("/", response_class=HTMLResponse)
def overview(request: Request):
    return page(request, "overview.html", **status_data(conn()))


@app.get("/partials/status", response_class=HTMLResponse)
def partial_status(request: Request):
    return page(request, "_status.html", **status_data(conn()))


@app.get("/camera/test-frame")
def test_frame():
    try:
        with urllib.request.urlopen(cfg()["camera"]["streamer_url"] + "/snapshot", timeout=5) as r:
            return Response(r.read(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})
    except Exception:
        raise HTTPException(503, "camera/streamer unavailable")


# ---------- library ----------
PER_PAGE = (24, 60, 120, 240)
VSORT = {"date": "m.ts_utc", "size": "m.size_bytes", "duration": "m.duration", "name": "m.path"}
FSORT = {"time": "m.ts_utc", "size": "m.size_bytes"}


def videos_sorted(c, key, direction, q="", pinned=False):
    col = VSORT.get(key, VSORT["date"])
    d = "ASC" if direction == "asc" else "DESC"
    for r in c.execute("SELECT id,path FROM media_files WHERE media_type='video' AND status='ok' AND duration IS NULL LIMIT 10").fetchall():
        try:  # backfill durations of videos rendered before the column existed (a few per page view)
            real = paths.safe_path(r["path"], cfg()["storage"]["root"])
            dur = render.probe(real).get("duration")
            c.execute("UPDATE media_files SET duration=? WHERE id=?", (dur, r["id"])); c.commit()
        except Exception:
            pass
    return c.execute("SELECT m.*, p.media_id IS NOT NULL AS pinned FROM media_files m LEFT JOIN pinned_media p ON p.media_id=m.id "
                     f"WHERE m.media_type='video' AND m.status='ok' AND replace(m.path, rtrim(m.path, replace(m.path, '/', '')), '') LIKE ? ESCAPE '\\' {'AND p.media_id IS NOT NULL' if pinned else ''} ORDER BY {col} {d} LIMIT 200",
                     ("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",)).fetchall()


def hour_strip(c, d, tz, interval):
    """24 local-hour cells for day d: how many frames were captured in each hour vs. how many the interval should give."""
    s, e = render.day_range(d, tz); z = ZoneInfo(tz)
    n = [0] * 24
    for r in c.execute("SELECT ts_utc FROM media_files WHERE media_type='image' AND status='ok' AND ts_utc>=? AND ts_utc<?", (render.fmt(s), render.fmt(e))):
        n[datetime.strptime(r[0], TS).replace(tzinfo=timezone.utc).astimezone(z).hour] += 1
    want = max(1, 3600 // max(10, interval))
    return [{"h": h, "n": n[h], "d": round(min(1.0, n[h] / want), 2)} for h in range(24)]


def day_counts(c, y, m, tz):
    out = {}
    d = date(y, m, 1)
    while d.month == m:
        s, e = render.day_range(d, tz)
        out[d.day] = c.execute("SELECT COUNT(*) FROM media_files WHERE media_type='image' AND status='ok' AND ts_utc>=? AND ts_utc<?", (render.fmt(s), render.fmt(e))).fetchone()[0]
        d += timedelta(days=1)
    return out


@app.get("/library", response_class=HTMLResponse)
def library(request: Request, day: str = "", month: str = "", page_no: int = 1, per_page: int = 60, tab: str = "frames",
            fsort: str = "time", fdir: str = "asc", tfrom: str = "", tto: str = "", fpinned: int = 0, q: str = ""):
    c = conn(); tz = cfgmod.effective(cfg(), c)["timezone"]
    today = datetime.now(ZoneInfo(tz)).date()
    try:
        d = date.fromisoformat(day) if day else today
        mo = date.fromisoformat(month + "-01") if month else d.replace(day=1)
        s, e = render.day_range(d, tz)
        if re.fullmatch(r"\d\d:\d\d", tfrom): s = render.parse_local(f"{d}T{tfrom}", tz)
        else: tfrom = ""
        if re.fullmatch(r"\d\d:\d\d", tto): e = render.parse_local(f"{d}T{tto}", tz)
        else: tto = ""
    except ValueError:
        raise HTTPException(400, "bad date")
    tab = "videos" if tab == "videos" else "frames"
    per_page = per_page if per_page in PER_PAGE else 60
    page_no = max(1, min(page_no, 10000))
    fsort = fsort if fsort in FSORT else "time"; fdir = "desc" if fdir == "desc" else "asc"
    pin = "AND p.media_id IS NOT NULL" if fpinned else ""
    total = c.execute("SELECT COUNT(*) FROM media_files m LEFT JOIN pinned_media p ON p.media_id=m.id WHERE m.media_type='image' AND m.status='ok' AND m.ts_utc>=? AND m.ts_utc<? " + pin,
                      (render.fmt(s), render.fmt(e))).fetchone()[0]
    pages = max(1, -(-total // per_page)); page_no = min(page_no, pages)
    rows = c.execute("SELECT m.*, p.media_id IS NOT NULL AS pinned FROM media_files m LEFT JOIN pinned_media p ON p.media_id=m.id "
                     f"WHERE m.media_type='image' AND m.status='ok' AND m.ts_utc>=? AND m.ts_utc<? {pin} ORDER BY {FSORT[fsort]} {fdir.upper()}, m.id LIMIT ? OFFSET ?",
                     (render.fmt(s), render.fmt(e), per_page, (page_no - 1) * per_page)).fetchall()
    vids = videos_sorted(c, request.query_params.get("vsort", "date"), request.query_params.get("vdir", "desc"), q[:100], bool(fpinned))
    first_wd = mo.weekday()
    strip = hour_strip(c, d, tz, cfgmod.effective(cfg(), c)["capture"]["interval_seconds"])
    prev_m = (mo - timedelta(days=1)).strftime("%Y-%m"); next_m = (mo + timedelta(days=32)).replace(day=1).strftime("%Y-%m")
    return page(request, "library.html", vsort=request.query_params.get("vsort", "date"), vdir=request.query_params.get("vdir", "desc"), d=d, mo=mo, counts=day_counts(c, mo.year, mo.month, tz), first_wd=first_wd, rows=rows, total=total,
                vids=vids, strip=strip, tab=tab, fsort=fsort, fdir=fdir, tfrom=tfrom, tto=tto, fpinned=fpinned, q=q, page_no=page_no, per_page=per_page, per_pages=PER_PAGE, pages=pages, tz=tz, prev_m=prev_m, next_m=next_m, today=today)


def media_row(c, mid):
    r = c.execute("SELECT * FROM media_files WHERE id=? AND status='ok'", (mid,)).fetchone()
    if not r:
        raise HTTPException(404)
    try:
        return r, paths.safe_path(r["path"], cfg()["storage"]["root"])
    except ValueError:
        raise HTTPException(404)


@app.get("/media/{mid}/file")
def media_file(mid: int, dl: int = 0):
    r, p = media_row(conn(), mid)
    if not os.path.isfile(p):
        raise HTTPException(404)
    mt = "image/jpeg" if r["media_type"] == "image" else ("image/webp" if p.endswith(".webp") else "video/mp4")
    # frames never change once written: let the browser keep what the Play tab preloaded instead of re-asking for each one
    hdr = {"Cache-Control": "private, max-age=3600"} if r["media_type"] == "image" and not dl else None
    return FileResponse(p, media_type=mt, filename=os.path.basename(p) if dl else None, content_disposition_type="attachment" if dl else "inline", headers=hdr)


@app.get("/media/{mid}/thumb")
def media_thumb(mid: int):
    r, p = media_row(conn(), mid)
    root = cfg()["storage"]["root"]
    t = os.path.join(root, "thumbnails", f"m{mid}.jpg")
    if not os.path.isfile(t):
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", p, "-frames:v", "1", "-vf", "scale=320:-2", t], timeout=30)
    if not os.path.isfile(t):
        raise HTTPException(404)
    return FileResponse(t, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.post("/media/{mid}/pin")
async def pin(request: Request, mid: int):
    c = conn(); media_row(c, mid)
    c.execute("INSERT OR IGNORE INTO pinned_media VALUES(?,?,NULL)", (mid, db.utcnow())); audit(c, request, "pin", str(mid))
    return back(request.headers.get("referer", "/library").split(request.headers["host"])[-1] or "/library", "pinned")


@app.post("/media/{mid}/unpin")
async def unpin(request: Request, mid: int):
    c = conn()
    c.execute("DELETE FROM pinned_media WHERE media_id=?", (mid,)); audit(c, request, "unpin", str(mid))
    return back(request.headers.get("referer", "/library").split(request.headers["host"])[-1] or "/library", "unpinned")


@app.post("/media/{mid}/delete")
async def delete_media(request: Request, mid: int):
    c = conn(); r, p = media_row(c, mid)
    f = await form_of(request)
    if f.get("confirm") != "yes":
        raise HTTPException(400, "confirmation required")
    if c.execute("SELECT 1 FROM pinned_media WHERE media_id=?", (mid,)).fetchone() or r["protected"]:
        raise HTTPException(409, "pinned/protected media cannot be deleted; unpin first")
    if r["media_type"] == "image" and cleanup.in_active_render(cleanup.active_ranges(c), r["ts_utc"]):
        raise HTTPException(409, "this frame belongs to a queued/running render")
    ok = cleanup.delete_one(c, cfg()["storage"]["root"], mid, r["path"], f"manual delete by {request.headers.get('x-remote-user')}")
    return back("/library", "deleted" if ok else "delete failed")


# ---------- bulk actions, storage by day, range delete ----------
def zip_response(rows, name):
    try:
        out = files.build_zip(cfg()["storage"]["root"], rows)
    except ValueError as ex:
        return None, str(ex)
    return FileResponse(out, media_type="application/zip", filename=name, background=BackgroundTask(os.unlink, out)), None


def bulk_result(res):
    return ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in res.items() if v) or "nothing to do"


@app.post("/library/bulk")
async def library_bulk(request: Request):
    form = await request.form()
    c = conn(); act = form.get("action", "")
    ids = [i for i in form.getlist("ids") if isinstance(i, str) and i.isdigit()]
    if not ids or len(ids) > files.MAX_IDS:
        return back("/library", f"select between 1 and {files.MAX_IDS} items")
    rows = files.rows_by_ids(c, ids)
    root = cfg()["storage"]["root"]
    if act == "zip":
        resp, err = zip_response(rows, f"timecanvas-selection-{len(rows)}.zip")
        audit(c, request, "bulk.zip", f"{len(rows)} items")
        return resp or back("/library", err)
    if act in ("pin", "unpin"):
        n = files.bulk_pin(c, rows, act == "pin"); audit(c, request, f"bulk.{act}", f"{n} items")
        return back("/library", f"{n} item(s) {act}ned" if act == "pin" else f"{n} item(s) unpinned")
    if act == "delete":
        if form.get("confirm") != "yes":
            return back("/library", "confirmation required")
        res = files.bulk_delete(c, root, rows, f"bulk delete by {request.headers.get('x-remote-user')}")
        audit(c, request, "bulk.delete", json.dumps(res))
        return back("/library", "bulk delete: " + bulk_result(res))
    return back("/library", "unknown action")


@app.get("/storage", response_class=HTMLResponse)
def storage(request: Request, month: str = ""):
    c = conn(); tz = cfgmod.effective(cfg(), c)["timezone"]
    try:
        mo = date.fromisoformat(month + "-01") if month else datetime.now(ZoneInfo(tz)).date().replace(day=1)
    except ValueError:
        raise HTTPException(400, "bad month")
    days = [files.day_stats(c, d, tz) for d in files.month_days(mo.year, mo.month)]
    tot = {"frames": sum(x["frames"] for x in days), "bytes": sum(x["bytes"] for x in days), "pinned": sum(x["pinned"] for x in days)}
    return page(request, "storage.html", days=days, mo=mo, tot=tot, tz=tz, today=datetime.now(ZoneInfo(tz)).date(),
                prev_m=(mo - timedelta(days=1)).strftime("%Y-%m"), next_m=(mo + timedelta(days=32)).replace(day=1).strftime("%Y-%m"))


def day_bounds(day, tz):
    return render.day_range(date.fromisoformat(day), tz)


@app.post("/storage/day")
async def storage_day(request: Request):
    f = await form_of(request); c = conn(); tz = cfgmod.effective(cfg(), c)["timezone"]
    try:
        s, e = day_bounds(f.get("day", ""), tz)
    except ValueError:
        return back("/storage", "bad date")
    act = f.get("action", ""); rows = files.range_rows(c, s, e, ("image",))
    root = cfg()["storage"]["root"]; back_url = f"/storage?month={f['day'][:7]}"
    if act == "zip":
        resp, err = zip_response(rows, f"timecanvas-{f['day']}.zip"); audit(c, request, "day.zip", f["day"])
        return resp or back(back_url, err)
    if act in ("pin", "unpin"):
        n = files.bulk_pin(c, rows, act == "pin"); audit(c, request, f"day.{act}", f"{f['day']} {n} frames")
        return back(back_url, f"{f['day']}: {n} frame(s) {'pinned' if act == 'pin' else 'unpinned'}")
    if act == "delete":
        if f.get("confirm") != "yes":
            return back(back_url, "confirmation required")
        res = files.bulk_delete(c, root, rows, f"day delete {f['day']} by {request.headers.get('x-remote-user')}")
        audit(c, request, "day.delete", f"{f['day']} {json.dumps(res)}")
        return back(back_url, f"{f['day']}: " + bulk_result(res))
    return back(back_url, "unknown action")


def range_select(c, f, tz):
    """Shared by the preview and the delete so both always act on exactly the same set."""
    d0 = date.fromisoformat(f["from"]); d1 = date.fromisoformat(f["to"])
    if d1 < d0 or (d1 - d0).days > 3650:
        raise ValueError("bad range")
    kinds = {"frames": ("image",), "videos": ("video",), "both": ("image", "video")}[f.get("type", "frames")]
    s, _ = render.day_range(d0, tz); _, e = render.day_range(d1, tz)
    rows = files.range_rows(c, s, e, kinds)
    ok, pinned, busy = files.deletable(c, rows)
    return ok, pinned, busy


@app.get("/storage/range-preview", response_class=HTMLResponse)
def range_preview(request: Request):
    c = conn(); tz = cfgmod.effective(cfg(), c)["timezone"]; q = dict(request.query_params)
    try:
        ok, pinned, busy = range_select(c, q, tz)
    except (ValueError, KeyError):
        return HTMLResponse('<p class="crit">Choose a valid from/to date.</p>')
    return page(request, "_range_preview.html", q=q, n=len(ok), size=sum(r["size_bytes"] for r in ok), pinned=pinned, busy=busy,
                sample=[r["path"].rsplit("/", 1)[-1] for r in ok[:5]])


@app.post("/storage/range-delete")
async def range_delete(request: Request):
    f = await form_of(request); c = conn(); tz = cfgmod.effective(cfg(), c)["timezone"]
    if f.get("confirm") != "yes":
        return back("/storage", "confirmation required")
    try:
        ok, pinned, busy = range_select(c, f, tz)
    except (ValueError, KeyError):
        return back("/storage", "invalid range")
    res = files.bulk_delete(c, cfg()["storage"]["root"], ok, f"range delete {f['from']}..{f['to']} by {request.headers.get('x-remote-user')}")
    res["skipped_pinned"] += pinned; res["skipped_render"] += busy
    audit(c, request, "range.delete", f"{f['from']}..{f['to']} {f.get('type')} {json.dumps(res)}")
    return back("/storage", "range delete: " + bulk_result(res))


# ---------- play a time range in the browser ----------
PLAY_CAP = 3000


@app.get("/play", response_class=HTMLResponse)
def play(request: Request, start: str = "", end: str = ""):
    tz = cfgmod.effective(cfg(), conn())["timezone"]
    now = datetime.now(ZoneInfo(tz))
    ok = lambda v: v if re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d", v) else ""
    return page(request, "play.html", start=ok(start) or now.strftime("%Y-%m-%dT00:00"), end=ok(end) or now.strftime("%Y-%m-%dT%H:%M"), cap=PLAY_CAP)


@app.get("/play/frames")
def play_frames(start: str, end: str, step: int = 1):
    c = conn(); tz = cfgmod.effective(cfg(), c)["timezone"]
    try:
        s, e = render.parse_local(start, tz), render.parse_local(end, tz)
    except ValueError:
        raise HTTPException(400, "bad time")
    if e <= s or (e - s).days > 400:
        raise HTTPException(400, "bad range")
    rows = c.execute("SELECT id,ts_utc FROM media_files WHERE media_type='image' AND status='ok' AND ts_utc>=? AND ts_utc<? ORDER BY ts_utc, id",
                     (render.fmt(s), render.fmt(e))).fetchall()
    total = len(rows); step = max(1, min(step, 1000))
    if total // step > PLAY_CAP:   # never ship an unbounded list: widen the step instead
        step = -(-total // PLAY_CAP)
    z = ZoneInfo(tz)
    out = [[r["id"], datetime.strptime(r["ts_utc"], render.TS).replace(tzinfo=timezone.utc).astimezone(z).strftime("%Y-%m-%d %H:%M:%S")] for r in rows[::step]]
    return {"total": total, "step": step, "frames": out}


# ---------- renders ----------
@app.get("/renders", response_class=HTMLResponse)
def renders(request: Request, start: str = "", end: str = "", fps: int = 30, fmt: str = "", edit: int = 0):
    c = conn(); rc = cfgmod.effective(cfg(), c)["render"]; tz = cfgmod.effective(cfg(), c)["timezone"]
    ed = None
    if edit:
        j = c.execute("SELECT * FROM render_jobs WHERE id=?", (edit,)).fetchone()
        if j:
            p = json.loads(j["params_json"]); f_ = "%Y-%m-%dT%H:%M"
            ed = {"id": j["id"], "status": j["status"], "kind": j["kind"], "start": local(j["range_start_utc"], tz, f_), "end": local(j["range_end_utc"], tz, f_),
                  "fps": p.get("fps", 30), "crf": p.get("crf", 23), "preset": p.get("preset", "medium"), "rotate": p.get("rotate", 0), "overlay": p.get("overlay", False),
                  "format": p.get("format", "mp4"), "crop": ",".join(map(str, p["crop"])) if p.get("crop") else "", "scale": ",".join(map(str, p["scale"])) if p.get("scale") else ""}
    return page(request, "renders.html", jobs=c.execute("SELECT * FROM render_jobs ORDER BY id DESC LIMIT 50").fetchall(), presets=PRESETS, rc=rc, ed=ed,
                fps=fps if 1 <= fps <= 60 else rc["fps"], tz=tz, today=_safe_date(start[:10]) or datetime.now(ZoneInfo(tz)).date(),
                start=start if re.fullmatch(r"[\d-]{10}(T\d\d:\d\d)?", start) else "", end=end if re.fullmatch(r"[\d-]{10}(T\d\d:\d\d)?", end) else "", fmt=fmt if fmt in ("mp4", "webp") else "mp4")


def _safe_date(v):
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


@app.get("/partials/renders", response_class=HTMLResponse)
def renders_partial(request: Request):
    c = conn()
    return page(request, "_jobs.html", tz=cfgmod.effective(cfg(), c)["timezone"], jobs=c.execute("SELECT * FROM render_jobs ORDER BY id DESC LIMIT 50").fetchall())


def ints(s, n):
    parts = [x.strip() for x in (s or "").split(",") if x.strip()]
    if not parts:
        return None
    if len(parts) != n or not all(re.fullmatch(r"\d{1,5}", x) for x in parts):
        raise ValueError(f"expected {n} comma-separated integers")
    return [int(x) for x in parts]


@app.post("/renders")
async def renders_create(request: Request):
    f = await form_of(request); c = conn(); tz = cfgmod.effective(cfg(), c)["timezone"]
    try:
        kind = f.get("kind", "custom")
        if kind not in ("daily", "weekly", "monthly", "custom"):
            raise ValueError("bad kind")
        st, en = f["start"], f.get("end") or f["start"]
        d0 = date.fromisoformat(st[:10]); d1 = date.fromisoformat(en[:10])
        if kind == "daily":
            d1 = d0
        elif kind == "weekly":
            d1 = d0 + timedelta(days=6)
        elif kind == "monthly":
            d1 = (d0.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1); d0 = d0.replace(day=1)
        if d1 < d0 or (d1 - d0).days > 400:
            raise ValueError("bad range")
        p = render.validate_params({"fps": f.get("fps", 30), "crf": f.get("crf", 23), "preset": f.get("preset", "medium"),
                                    "crop": ints(f.get("crop"), 4), "scale": ints(f.get("scale"), 2), "rotate": f.get("rotate", 0), "overlay": f.get("overlay") == "on", "format": f.get("format", "mp4")})
        if kind == "custom":   # exact local times (datetime-local), or whole days when only dates are given
            s, e = render.parse_local(st, tz), render.parse_local(en, tz, end=True)
            if "T" in en and e <= s: raise ValueError("end must be after start")
        else:
            s, _ = render.day_range(d0, tz); _, e = render.day_range(d1, tz)
        if e <= s or (e - s).days > 400: raise ValueError("bad range")
        eid = int(f["edit_id"]) if f.get("edit_id", "").isdigit() else 0
        if eid:
            old = c.execute("SELECT status FROM render_jobs WHERE id=?", (eid,)).fetchone()
            if not old:
                raise ValueError("that job no longer exists")
            if old["status"] == "running":
                raise ValueError("job is running: cancel it first, then edit")
            if old["status"] in ("queued", "failed", "cancelled"):   # not produced anything: change it in place and queue it again
                key = render.job_key(kind, s, e, p)
                dup = c.execute("SELECT id FROM render_jobs WHERE idempotency_key=? AND id!=?", (key, eid)).fetchone()
                if dup:
                    raise ValueError(f"job {dup[0]} already has exactly these settings")
                c.execute("UPDATE render_jobs SET kind=?,range_start_utc=?,range_end_utc=?,params_json=?,idempotency_key=?,status='queued',progress=0,error=NULL,pid=NULL,"
                          "started_utc=NULL,completed_utc=NULL,output_media_id=NULL WHERE id=?", (kind, render.fmt(s), render.fmt(e), json.dumps(p), key, eid))
                audit(c, request, "render.edit", f"job {eid}")
                return back("/renders", f"job {eid} updated and queued")
            # a finished job keeps its video: the edited settings become a new job
        jid = render.create_job(c, kind, s, e, p, rerender=True)
        audit(c, request, "render.edit.new" if eid else "render.create", f"job {jid}" + (f" (from {eid})" if eid else ""))
    except (ValueError, KeyError) as ex:
        return back("/renders", f"invalid: {ex}")
    return back("/renders", f"job {jid} queued")


@app.post("/renders/{jid}/cancel")
async def render_cancel(request: Request, jid: int):
    c = conn()
    c.execute("UPDATE render_jobs SET status='cancelled' WHERE id=? AND status IN ('queued','running')", (jid,)); c.commit()
    audit(c, request, "render.cancel", str(jid))
    return back("/renders", "cancel requested")


@app.post("/renders/{jid}/retry")
async def render_retry(request: Request, jid: int):
    c = conn()
    c.execute("UPDATE render_jobs SET status='queued',progress=0,error=NULL,pid=NULL WHERE id=? AND status IN ('failed','cancelled')", (jid,)); c.commit()
    audit(c, request, "render.retry", str(jid))
    return back("/renders", "retry queued")


# ---------- sessions ----------
@app.get("/sessions", response_class=HTMLResponse)
def sessions(request: Request, edit: int = 0):
    c = conn(); tz = cfgmod.effective(cfg(), c)["timezone"]
    ed = None
    r_ = c.execute("SELECT * FROM sessions WHERE id=?", (edit,)).fetchone() if edit else None
    if r_:
        sch = json.loads(r_["schedule_json"]) if r_["schedule_json"] else {}; f_ = "%Y-%m-%dT%H:%M"
        ed = {"id": r_["id"], "name": r_["name"], "start": local(r_["start_utc"], tz, f_), "end": local(r_["end_utc"], tz, f_) if r_["end_utc"] else "", "interval": r_["interval_seconds"] or "",
              "days": ",".join(map(str, sch.get("days", []))), "hours": ",".join(map(str, sch.get("hours", [])))}
    rows = []
    for s in c.execute("SELECT * FROM sessions ORDER BY id DESC").fetchall():
        end = s["end_utc"] or db.utcnow()
        n = c.execute("SELECT COUNT(*) FROM media_files WHERE media_type='image' AND status='ok' AND ts_utc>=? AND ts_utc<?", (s["start_utc"], end)).fetchone()[0]
        rows.append((s, n))
    return page(request, "sessions.html", rows=rows, tz=tz, ed=ed)


@app.post("/sessions")
async def session_create(request: Request):
    f = await form_of(request); c = conn(); tz = cfgmod.effective(cfg(), c)["timezone"]
    try:
        name = f["name"].strip()
        if not 1 <= len(name) <= 80:
            raise ValueError("name 1-80 chars")
        z = ZoneInfo(tz)
        st = datetime.fromisoformat(f["start"]).replace(tzinfo=z).astimezone(timezone.utc)
        en = datetime.fromisoformat(f["end"]).replace(tzinfo=z).astimezone(timezone.utc) if f.get("end") else None
        if en and en <= st:
            raise ValueError("end must be after start")
        iv = int(f["interval"]) if f.get("interval") else None
        if iv is not None and not 10 <= iv <= 3600:
            raise ValueError("interval 10-3600")
        sch = {}
        if f.get("days"):
            sch["days"] = [int(x) for x in f["days"].split(",") if re.fullmatch(r"[0-6]", x.strip())]
        if f.get("hours"):
            h = ints(f["hours"], 2)
            if not (0 <= h[0] < h[1] <= 24):
                raise ValueError("hours must be start,end within 0-24")
            sch["hours"] = h
        eid = int(f["edit_id"]) if f.get("edit_id", "").isdigit() else 0
        if eid:
            if not c.execute("SELECT 1 FROM sessions WHERE id=?", (eid,)).fetchone():
                raise ValueError("that session no longer exists")
            c.execute("UPDATE sessions SET name=?,start_utc=?,end_utc=?,interval_seconds=?,schedule_json=? WHERE id=?",
                      (name, render.fmt(st), render.fmt(en) if en else None, iv, json.dumps(sch) if sch else None, eid))
            audit(c, request, "session.edit", f"{eid} {name}")
            return back("/sessions", "session updated")
        c.execute("INSERT INTO sessions(name,start_utc,end_utc,interval_seconds,schedule_json,created_utc) VALUES(?,?,?,?,?,?)",
                  (name, render.fmt(st), render.fmt(en) if en else None, iv, json.dumps(sch) if sch else None, db.utcnow()))
        audit(c, request, "session.create", name)
    except (ValueError, KeyError) as ex:
        return back("/sessions", f"invalid: {ex}")
    return back("/sessions", "session created")


@app.post("/sessions/{sid}/delete")
async def session_delete(request: Request, sid: int):
    c = conn(); c.execute("DELETE FROM sessions WHERE id=?", (sid,)); audit(c, request, "session.delete", str(sid))
    return back("/sessions", "session deleted (media kept)")


# ---------- camera ----------
def camera_view(request):
    c = conn(); ok, info = helper("camera-info")
    modes = v4l2.parse_modes(info) if ok else {}
    cur = re.search(r"^#MODE (\S*) ?(\S*)", info, re.M) if ok else None
    state = _state()
    cur_res = f"{state['source']['resolution']['width']}x{state['source']['resolution']['height']}" if state else ""
    return {"ok": ok, "info": info, "ctrls": v4l2.parse_ctrls(info) if ok else [], "modes": v4l2.mode_list(modes), "cur_res": cur_res,
            "cur_fps": cur.group(2) if cur and cur.group(2) else (cfg()["camera"]["fps"]), "cam": cfg()["camera"],
            "profiles": c.execute("SELECT * FROM camera_profiles ORDER BY name").fetchall(), "state": state}


def _state():
    try:
        with urllib.request.urlopen(cfg()["camera"]["streamer_url"] + "/state", timeout=3) as r:
            return json.load(r)["result"]
    except Exception:
        return None


@app.get("/camera", response_class=HTMLResponse)
def camera(request: Request):
    return page(request, "camera.html", **camera_view(request))


@app.get("/partials/camera-controls", response_class=HTMLResponse)
def camera_controls_partial(request: Request):
    return page(request, "_ctrls.html", **camera_view(request))


@app.get("/live", response_class=HTMLResponse)
def live(request: Request):
    return page(request, "live.html", state=_state())


def fragment(ok, text):
    return HTMLResponse(f'<span class="{"ok" if ok else "crit"}">{"✓" if ok else "✗"} {html_escape(text)[:160]}</span>')


@app.post("/camera/set")
async def camera_set(request: Request):
    f = await form_of(request)
    try:
        ok, out = helper("camera-set", name=f.get("name", ""), value=int(f.get("value", "x")))
    except ValueError:
        ok, out = False, "value must be an integer"
    audit(conn(), request, "camera.set", f"{f.get('name')}={f.get('value')} ok={ok}")
    if request.headers.get("hx-request"):
        r = fragment(ok, "applied" if ok else out)
        if f.get("name") in ("auto_exposure", "white_balance_automatic"):
            r.headers["HX-Trigger"] = "ctrls-changed"  # which controls are active changed: reload the panel
        return r
    return back("/camera", "applied" if ok else f"failed: {out[:100]}")


@app.post("/camera/mode")
async def camera_mode(request: Request):
    f = await form_of(request)
    try:
        w, h, fps = (int(x) for x in f.get("mode", "").split("x"))
    except ValueError:
        return fragment(False, "bad mode") if request.headers.get("hx-request") else back("/camera", "bad mode")
    ok, out = helper("camera-mode", width=w, height=h, fps=fps)
    audit(conn(), request, "camera.mode", f"{w}x{h}@{fps} ok={ok}: {out[:100]}")
    if request.headers.get("hx-request"):
        r = fragment(ok, out)
        r.headers["HX-Trigger"] = "stream-restarted"
        return r
    return back("/camera", out)


@app.post("/camera/reset")
async def camera_reset(request: Request):
    ok, out = helper("camera-reset"); audit(conn(), request, "camera.reset", f"ok={ok}")
    r = fragment(ok, out) if request.headers.get("hx-request") else back("/camera", out)
    if request.headers.get("hx-request"):
        r.headers["HX-Trigger"] = "ctrls-changed"
    return r


@app.post("/camera/restart")
async def camera_restart(request: Request):
    ok, out = helper("restart-camera"); audit(conn(), request, "camera.restart", f"ok={ok}")
    return back("/camera", "camera broker restarted" if ok else f"failed: {out[:100]}")


@app.post("/camera/profile")
async def profile_save(request: Request):
    f = await form_of(request); c = conn()
    name = f.get("pname", "").strip()
    vals = {c_["name"]: int(c_["value"]) for c_ in camera_view(request)["ctrls"] if c_["value"] is not None and not c_["readonly"] and not c_["inactive"]}
    if not re.fullmatch(r"[\w .-]{1,40}", name) or not vals:
        return back("/camera", "invalid profile")
    c.execute("INSERT INTO camera_profiles(name,controls_json,created_utc) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET controls_json=excluded.controls_json", (name, json.dumps(vals), db.utcnow()))
    audit(c, request, "camera.profile.save", name)
    return back("/camera", "profile saved from the current camera values")


@app.post("/camera/profile/apply")
async def profile_apply(request: Request):
    f = await form_of(request); c = conn()
    r = c.execute("SELECT * FROM camera_profiles WHERE name=?", (f.get("pname", ""),)).fetchone()
    if not r:
        return back("/camera", "no such profile")
    vals = json.loads(r["controls_json"])
    order = sorted(vals, key=lambda n: (n not in ("auto_exposure", "white_balance_automatic"), n))
    bad = [k for k in order if not helper("camera-set", name=k, value=vals[k])[0]]
    audit(c, request, "camera.profile.apply", f"{r['name']} skipped={bad}")
    return back("/camera", "profile applied" + (f" (skipped: {', '.join(bad)})" if bad else ""))


# ---------- settings ----------
RULES = {"capture_interval_seconds": (10, 3600), "frame_retention_days": (1, 3650), "video_retention_days": (1, 3650),
         "disk_warning_percent": (50, 98), "disk_critical_percent": (51, 99), "render_fps": (1, 60), "render_crf": (14, 35)}


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    c = conn(); e = cfgmod.effective(cfg(), c)
    vals = {"capture_interval_seconds": e["capture"]["interval_seconds"], "frame_retention_days": e["storage"]["frame_retention_days"],
            "video_retention_days": e["storage"]["video_retention_days"], "disk_warning_percent": e["storage"]["disk_warning_percent"],
            "disk_critical_percent": e["storage"]["disk_critical_percent"], "render_fps": e["render"]["fps"], "render_crf": e["render"]["crf"],
            "render_preset": e["render"]["preset"], "timezone": e["timezone"], "capture_enabled": db.get_setting(c, "capture_enabled", "1")}
    return page(request, "settings.html", v=vals, rules=RULES, presets=PRESETS)


@app.post("/settings")
async def settings_save(request: Request):
    f = await form_of(request); c = conn(); upd = {}
    try:
        for k, (lo, hi) in RULES.items():
            n = int(f[k])
            if not lo <= n <= hi:
                raise ValueError(f"{k} must be {lo}-{hi}")
            upd[k] = str(n)
        if int(upd["disk_warning_percent"]) >= int(upd["disk_critical_percent"]):
            raise ValueError("warning threshold must be below critical")
        if f["render_preset"] not in render.PRESETS:
            raise ValueError("bad preset")
        if f["timezone"] not in available_timezones():
            raise ValueError("unknown timezone")
        upd["render_preset"] = f["render_preset"]; upd["timezone"] = f["timezone"]; upd["capture_enabled"] = "1" if f.get("capture_enabled") == "on" else "0"
    except (ValueError, KeyError) as ex:
        return back("/settings", f"invalid: {ex}")
    for k, v in upd.items():
        c.execute("INSERT INTO settings(key,value,updated_utc) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_utc=excluded.updated_utc", (k, v, db.utcnow()))
    audit(c, request, "settings.save", json.dumps(upd))
    return back("/settings", "saved")


# ---------- archive (OneDrive) ----------
@app.get("/archive", response_class=HTMLResponse)
def archive_page(request: Request):
    c = conn(); tz = cfgmod.effective(cfg(), c)["timezone"]
    s = archive.get(c)
    pend = archive.pending_days(c, tz, datetime.now(ZoneInfo(tz)).date())
    tot = c.execute("SELECT COUNT(*) n, COALESCE(SUM(bytes),0) b FROM archive_items WHERE status='ok'").fetchone()
    return page(request, "archive.html", s=s, ready=archive.configured(s["remote"]), pend=pend, tot=tot, tz=tz,
                last=json.loads(db.get_setting(c, "archive_status") or "{}"),
                items=c.execute("SELECT * FROM archive_items ORDER BY id DESC LIMIT 40").fetchall())


@app.post("/archive/settings")
async def archive_save(request: Request):
    f = await form_of(request); c = conn()
    remote = (f.get("remote") or "").strip()
    if not archive.valid_remote(remote):
        return back("/archive", "invalid: the folder must look like tcarchive:TimeCanvas (letters, digits, space, - _ . /)")
    archive.put(c, "archive_remote", remote)
    archive.put(c, "archive_enabled", "1" if f.get("enabled") == "on" else "0")
    archive.put(c, "archive_hold", "1" if f.get("hold") == "on" else "0")
    audit(c, request, "archive.settings", f"enabled={f.get('enabled') == 'on'} hold={f.get('hold') == 'on'} remote={remote}")
    return back("/archive", "saved")


@app.post("/archive/run")
async def archive_run(request: Request):
    c = conn()
    ok, out = helper("archive-run")
    audit(c, request, "archive.run", "started" if ok else out[:200])
    return back("/archive", "archive run started" if ok else "could not start: " + out[:120])


# ---------- alerts ----------
@app.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request):
    c = conn(); tz = cfgmod.effective(cfg(), c)["timezone"]; sec = alerts.load_secrets()
    return page(request, "alerts.html", s=alerts.get_settings(c), rules=alerts.RULES, tz=tz, ranges=alerts.RANGES,
                states={r["key"]: r for r in c.execute("SELECT * FROM alert_state")}, has={"teams": bool(sec.get("teams_webhook")), "smtp": bool(sec.get("smtp_password")), "postal": bool(sec.get("postal_api_key")), "hb": bool(sec.get("heartbeat_url"))},
                log=c.execute("SELECT * FROM alert_log ORDER BY id DESC LIMIT 30").fetchall())


@app.post("/alerts/settings")
async def alerts_save(request: Request):
    f = await form_of(request); c = conn(); upd = {}; sec = {}
    try:
        upd["alerts_enabled"] = "1" if f.get("alerts_enabled") == "on" else "0"
        for k in alerts.RULES:
            upd[f"alert_on_{k}"] = "1" if f.get(f"alert_on_{k}") == "on" else "0"
        for k, (lo, hi) in alerts.RANGES.items():
            n = int(f[k])
            if not lo <= n <= hi:
                raise ValueError(f"{k.replace('alert_', '').replace('_', ' ')} must be {lo}-{hi}")
            upd[k] = str(n)
        upd["alert_teams_on"] = "1" if f.get("alert_teams_on") == "on" else "0"
        upd["alert_email_on"] = "1" if f.get("alert_email_on") == "on" else "0"
        method = f.get("alert_email_method", "postal")
        if method not in ("postal", "smtp"):
            raise ValueError("email method must be postal or smtp")
        upd["alert_email_method"] = method
        purl = f.get("alert_postal_url", "").strip().rstrip("/")
        if purl and not alerts.valid_public_https(purl, 300):
            raise ValueError("Postal server must be an https URL like https://app.example.com")
        upd["alert_postal_url"] = purl
        if f.get("alert_smtp_security") not in ("starttls", "ssl", "none"):
            raise ValueError("email security must be starttls, ssl or none")
        upd["alert_smtp_security"] = f["alert_smtp_security"]
        host = f.get("alert_smtp_host", "").strip()
        if host and not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
            raise ValueError("mail server must be a host name")
        upd["alert_smtp_host"] = host
        user = f.get("alert_smtp_user", "").strip()
        if len(user) > 200: raise ValueError("mail user too long")
        upd["alert_smtp_user"] = user
        frm = f.get("alert_mail_from", "").strip()
        if frm and not alerts.valid_email(frm): raise ValueError("'from' is not an email address")
        upd["alert_mail_from"] = frm
        to = [a.strip() for a in f.get("alert_mail_to", "").replace(";", ",").split(",") if a.strip()]
        if len(to) > 5 or not all(alerts.valid_email(a) for a in to): raise ValueError("'to' must be up to 5 valid email addresses")
        upd["alert_mail_to"] = ", ".join(to)
        if f.get("postal_api_key", "").strip():
            k = f["postal_api_key"].strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]{8,200}", k): raise ValueError("that does not look like a Postal API key")
            sec["postal_api_key"] = k
        elif f.get("clear_postal") == "on": sec["postal_api_key"] = ""
        have_pk = sec["postal_api_key"] if "postal_api_key" in sec else alerts.load_secrets().get("postal_api_key")
        if upd["alert_email_on"] == "1":
            if method == "postal" and not (purl and have_pk and frm and to): raise ValueError("email via Postal needs the server URL, an API key, a from address and at least one recipient")
            if method == "smtp" and not (host and frm and to): raise ValueError("email via SMTP needs a server, a from address and at least one recipient")
        if f.get("teams_webhook", "").strip():
            if not alerts.valid_webhook(f["teams_webhook"].strip()): raise ValueError("that is not a Power Automate / Teams workflow webhook URL (https://....logic.azure.com/...)")
            sec["teams_webhook"] = f["teams_webhook"].strip()
        elif f.get("clear_teams") == "on": sec["teams_webhook"] = ""
        if f.get("smtp_password"): sec["smtp_password"] = f["smtp_password"][:300]
        elif f.get("clear_smtp") == "on": sec["smtp_password"] = ""
        if f.get("heartbeat_url", "").strip():
            if not alerts.valid_heartbeat(f["heartbeat_url"].strip()): raise ValueError("heartbeat must be an http(s) URL (private and tailnet addresses are fine; localhost and link-local are not)")
            sec["heartbeat_url"] = f["heartbeat_url"].strip()
        elif f.get("clear_hb") == "on": sec["heartbeat_url"] = ""
        have_hook = sec["teams_webhook"] if "teams_webhook" in sec else alerts.load_secrets().get("teams_webhook")
        if upd["alert_teams_on"] == "1" and not have_hook:
            raise ValueError("Teams is on but no webhook URL is saved")
    except (ValueError, KeyError) as ex:
        return back("/alerts", f"invalid: {ex}")
    for k, v in upd.items():
        alerts.put(c, k, v)
    if sec: alerts.save_secrets(sec)
    audit(c, request, "alerts.settings", "; ".join(f"{k}={v}" for k, v in upd.items() if k not in ("alert_mail_to", "alert_mail_from", "alert_smtp_user")) + (f"; secrets updated: {','.join(sorted(sec))}" if sec else ""))
    return back("/alerts", "saved")


@app.post("/alerts/test")
async def alerts_test(request: Request):
    f = await form_of(request); c = conn(); tz = cfgmod.effective(cfg(), c)["timezone"]
    only = f.get("channel") if f.get("channel") in ("teams", "email", "heartbeat") else None
    res = alerts.send_test(c, tz, only=only)
    audit(c, request, "alerts.test", ", ".join(f"{ch}:{'ok' if ok else 'failed'}" for ch, ok, _ in res))
    return back("/alerts", "; ".join(f"{ch}: {'OK - ' + msg if ok else 'FAILED - ' + msg}" for ch, ok, msg in res))


# ---------- maintenance ----------
@app.get("/maintenance", response_class=HTMLResponse)
def maintenance(request: Request, unit: str = ""):
    c = conn(); import shutil
    root = cfg()["storage"]["root"]
    u = shutil.disk_usage(root)
    by = c.execute("SELECT media_type,status,COUNT(*) n,COALESCE(SUM(size_bytes),0) b FROM media_files GROUP BY 1,2").fetchall()
    plan = cleanup.plan(c, cfgmod.effective(cfg(), c)) if request.query_params.get("retention") else None
    log = helper("journal", unit=unit, lines=100)[1] if unit in ("ustreamer", "capture", "render", "web", "health", "cleanup", "archive") else None
    return page(request, "maintenance.html", disk=u, by=by, plan=plan, log=log, unit=unit, commit=(open("/opt/timecanvas/VERSION").read().split() if os.path.exists("/opt/timecanvas/VERSION") else ["dev"]),
                mounted=os.path.ismount(root), audits=grouped_audits(c))


def grouped_audits(c, limit=15):
    """One row per action: a bulk delete writes a row per file in the same second, so collapse those runs."""
    out = []
    for r in c.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT 400"):
        k = (r["ts_utc"][:19], r["actor"], r["action"])
        if out and out[-1]["k"] == k:
            out[-1]["n"] += 1
        else:
            out.append({"k": k, "ts": r["ts_utc"][:19], "actor": r["actor"], "action": r["action"], "detail": r["detail"], "n": 1})
        if len(out) > limit + 1: break
    return out[:limit]


@app.post("/maintenance/reconcile")
async def m_reconcile(request: Request):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = reconcile.run(cfg())
    return back("/maintenance", buf.getvalue().strip() or f"rc={rc}")


@app.post("/maintenance/thumbs")
async def m_thumbs(request: Request):
    root = cfg()["storage"]["root"]; d = os.path.join(root, "thumbnails"); n = 0
    for f in os.listdir(d):
        if re.fullmatch(r"m\d+\.jpg", f):
            os.unlink(os.path.join(d, f)); n += 1
    audit(conn(), request, "thumbs.clear", str(n))
    return back("/maintenance", f"{n} thumbnails cleared; they regenerate on demand")


@app.get("/maintenance/config.toml")
def export_config():
    return PlainTextResponse(open(cfgmod.PATH).read(), headers={"Content-Disposition": 'attachment; filename="timecanvas-config.toml"'})


@app.get("/maintenance/diagnostics.txt")
def diagnostics(request: Request):
    ok, out = helper("diag"); audit(conn(), request, "diag.download", f"ok={ok}")
    return PlainTextResponse(out, headers={"Content-Disposition": 'attachment; filename="timecanvas-diagnostics.txt"'})
