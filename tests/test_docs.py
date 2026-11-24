"""Documentation drift checks (stdlib only, so they run everywhere and are never skipped).
They enforce docs/DEVELOPMENT.md > Documentation standard: one owner file per volatile fact, immutable dated snapshots, UI text that matches the templates."""
import glob, os, re, sys, unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "app"))
os.environ.setdefault("TIMECANVAS_MIGRATIONS", os.path.join(ROOT, "migrations"))
from timecanvas import alerts   # noqa: E402


def read(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return f.read()


def rel(pattern):
    return sorted(os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, pattern)))


LIVE_DOCS = rel("docs/*.md") + ["README.md"]          # current-state documents
SNAPSHOTS = [p for p in rel("deploy-log/*.md") if not p.endswith("test-results.md")]


class Docs(unittest.TestCase):
    def test_every_referenced_repo_path_and_relative_link_exists(self):
        missing = []
        for d in LIVE_DOCS + ["CHANGELOG.md"]:
            t = read(d)
            for m in re.finditer(r"`((?:scripts|infra/proxmox|tests(?:/live)?|docs|app/timecanvas(?:/web)?(?:/templates|/static)?|systemd|nginx|migrations|config|deploy-log)/[A-Za-z0-9_./\-]+)`", t):
                p = m.group(1).rstrip(".,:;)")
                if any(x in p for x in ("*", "<", "YYYY", "vX")) or p.endswith("/"):
                    continue
                if not os.path.exists(os.path.join(ROOT, p)):
                    missing.append((d, p))
            for m in re.finditer(r"\]\(((?!https?:|mailto:|#)[^)#\s]+)", t):
                if not os.path.exists(os.path.normpath(os.path.join(ROOT, os.path.dirname(d), m.group(1)))):
                    missing.append((d, "link " + m.group(1)))
        self.assertEqual(missing, [])

    def test_architecture_names_every_unit_helper_action_and_migration(self):
        a = read("docs/ARCHITECTURE.md"); miss = []
        for f in rel("systemd/*.service") + rel("systemd/*.timer") + rel("systemd/*.socket"):
            base = os.path.basename(f).replace("timecanvas-", "").rsplit(".", 1)[0].replace("@", "")
            if base not in a:
                miss.append("unit " + base)
        for act in re.findall(r'"([a-z\-]+)": a_', read("scripts/helper.py")):
            if act not in a:
                miss.append("helper action " + act)
        for m in rel("migrations/*.sql"):
            if os.path.basename(m) not in a:
                miss.append("migration " + os.path.basename(m))
        self.assertEqual(miss, [])

    def test_configuration_lists_every_settings_key(self):
        c = read("docs/CONFIGURATION.md"); prefixes = set(re.findall(r"`?([a-z_]+_)\*`?", c)); miss = []
        rules = re.search(r"RULES = \{(.*?)\}\n", read("app/timecanvas/web/app.py"), re.S).group(1)
        keys = list(alerts.DEFAULTS) + ["archive_enabled", "archive_remote", "archive_hold"] + re.findall(r'"([a-z_]+)":', rules)
        for k in keys:
            if k not in c and not any(k.startswith(p) for p in prefixes):
                miss.append(k)
        self.assertEqual(miss, [])

    def test_no_test_counts_in_current_docs(self):
        hits = [(d, m.group(0)) for d in LIVE_DOCS for m in re.finditer(r"\b\d+\s+(?:unit/web\s+)?tests?\b", read(d))]
        self.assertEqual(hits, [], "test counts go stale; describe what is covered instead")

    def test_removed_ui_text_is_gone_and_button_labels_match_templates(self):
        for d in LIVE_DOCS:
            self.assertNotIn("Send a test alert", read(d), d)
        labels = re.findall(r">(Test [^<]+)</button>", read("app/timecanvas/web/templates/alerts.html"))
        self.assertTrue(labels)
        al = read("docs/ALERTS.md")
        for lab in labels:
            self.assertIn(lab, al, f"alerts.html has a '{lab}' button that docs/ALERTS.md does not name")
        tabs = re.search(r'\("/settings","General"\).*?\]', read("app/timecanvas/web/templates/base.html")).group(0)
        for name in re.findall(r'"/[a-z]+","([A-Za-z]+)"\)', tabs):
            self.assertIn(name, read("docs/USER_GUIDE.md"), f"Settings tab {name} missing from USER_GUIDE")

    def test_security_names_every_unit_that_runs_as_root(self):
        sec = read("docs/SECURITY.md"); self.assertIn("## What runs as root", sec)
        section = sec.split("## What runs as root", 1)[1].split("\n## ", 1)[0]; miss = []
        for f in rel("systemd/*.service"):
            if not re.search(r"^User=", read(f), re.M):
                base = os.path.basename(f).replace("timecanvas-", "").replace(".service", "")
                if base not in section:
                    miss.append(base)
        self.assertEqual(miss, [], "units without User= run as root and must be listed under '## What runs as root'")
        for token in ("alerts.json", "rclone.conf", "htpasswd"):
            self.assertIn(token, sec, f"SECURITY secrets inventory lacks {token}")

    def test_snapshots_carry_a_banner(self):
        bad = []
        for f in SNAPSHOTS:
            first = next((l for l in read(f).splitlines() if l.strip()), "")
            if not re.search(r"(?i)snapshot as of", read(f)[:600]):
                bad.append(f)
        self.assertEqual(bad, [], "dated snapshots need a 'Snapshot as of <tag>' banner pointing to the owner files")

    def test_test_results_has_current_status_for_every_acceptance_test(self):
        t = read("deploy-log/test-results.md")
        self.assertIn("## Current status", t); self.assertIn("## History", t)
        cur = t.split("## Current status", 1)[1].split("## History", 1)[0]
        missing = [n for n in range(1, 47) if not re.search(rf"^\| {n} \|", cur, re.M)]
        self.assertEqual(missing, [])
        self.assertRegex(cur, r"(?m)^\| 40 \|[^|]*\|\s*PASS \(with limits\).*Not verified")   # a pass states what it did not check

    def test_third_party_procedures_state_whether_they_were_verified(self):
        for d in ("docs/ALERTS.md", "docs/ARCHIVE.md"):
            self.assertRegex(read(d), r"(Not verified|Verified \d{4}-\d\d-\d\d)", d)

    def test_changelog_has_unreleased_or_latest_matches_a_tag_section(self):
        c = read("CHANGELOG.md")
        self.assertRegex(c, r"(?m)^## (Unreleased|v\d+\.\d+\.\d+)")


if __name__ == "__main__":
    unittest.main()
