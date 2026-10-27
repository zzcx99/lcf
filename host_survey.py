# -*- coding: utf-8 -*-
"""
LCF Survey — hosted collection server (ONE survey, ONE dataset).

Serves the survey, receives submissions, shows a live dashboard,
exports one CSV. Runs locally or on any Python host
(Render / PythonAnywhere / VPS).

Endpoints
  GET  /                      the survey
  POST /api/submit            receive one submission
  GET  /admin?token=TOKEN     live dashboard
  GET  /export.csv?token=TOK  download everything as CSV
  GET  /count                 {"submissions":N,"items":M}
  GET  /health                uptime ping target

Environment variables
  LCF_TOKEN   admin / export password   (default: lcf2025 — CHANGE IT)
  LCF_DATA    data folder               (default: ./data)
"""
import csv
import io
import json
import os
import socket
from datetime import datetime

from flask import Flask, Response, jsonify, request

APP = Flask(__name__)

BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ.get("LCF_TOKEN", "lcf2025")
DATA_DIR = os.environ.get("LCF_DATA", os.path.join(BASE, "data"))
os.makedirs(DATA_DIR, exist_ok=True)
JSONL = os.path.join(DATA_DIR, "submissions.jsonl")
MIRROR = os.path.join(DATA_DIR, "all_submissions.csv")
PAGE = os.path.join(BASE, "LCF_Feedback_Survey.html")

NA = "(not given)"

# Must match the header the HTML writes and lcf_loader expects.
CSV_HEAD = ["Timestamp", "Programme", "Year", "Admin class", "Wants reply",
            "Contact (WeChat / email)", "Category", "Module", "Class type",
            "Instructor", "Session / when / where", "Issue category",
            "Description", "Scope", "Urgency", "Suggested change",
            "To meeting", "Top priority", "Positive feedback", "Other comments"]


def rows_from(p):
    r = p.get("respondent", {})
    base = [r.get("timestamp", ""),
            r.get("program", "") or NA,
            r.get("year", "") or "Y1",
            r.get("admin_class", "") or NA,
            r.get("wants_reply", "No"),
            r.get("contact", "")]
    tail = [r.get("top_priority", ""), r.get("praise", ""), r.get("extra", "")]
    items = p.get("items") or []
    out = []
    if not items:
        out.append(base + ["", "", "", "", "", "",
                           "(only overall comments were given)", "", "", "", ""]
                   + tail)
    for i in items:
        out.append(base + [
            i.get("category", ""),
            i.get("module", ""),
            i.get("sub_type", "") or NA,
            i.get("teacher", "") or NA,
            i.get("target", "") or NA,
            i.get("issue_type", ""),
            i.get("description", ""),
            i.get("scope", "") or NA,
            i.get("urgency", "") or NA,
            i.get("suggestion", ""),
            i.get("to_meeting", "") or NA,
        ] + tail)
    return out


def load_all():
    recs = []
    if os.path.exists(JSONL):
        with open(JSONL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        recs.append(json.loads(line))
                    except Exception:
                        pass
    return recs


def append_payload(p):
    p["_received"] = datetime.now().isoformat(timespec="seconds")
    with open(JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(p, ensure_ascii=False) + "\n")
    # mirror to CSV so data survives a host disk reset
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEAD)
    for rec in load_all():
        for row in rows_from(rec):
            w.writerow(row)
    with open(MIRROR, "w", encoding="utf-8") as f:
        f.write("\ufeff" + buf.getvalue())


def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp


@APP.route("/")
def index():
    try:
        with open(PAGE, encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        return "Survey page missing next to this script.", 500
    html = html.replace('SUBMIT_ENDPOINT: ""', 'SUBMIT_ENDPOINT: "/api/submit"')
    return Response(html, mimetype="text/html;charset=utf-8")


@APP.route("/api/submit", methods=["POST", "OPTIONS"])
def submit():
    if request.method == "OPTIONS":
        return _cors(Response(""))
    p = request.get_json(force=True, silent=True)
    if not p:
        return _cors(jsonify(ok=False, msg="invalid json")), 400
    append_payload(p)
    return _cors(jsonify(ok=True))


@APP.route("/health")
def health():
    return jsonify(ok=True, count=len(load_all()))


@APP.route("/count")
def count():
    recs = load_all()
    return jsonify(submissions=len(recs),
                   items=sum(len(r.get("items") or []) for r in recs))


@APP.route("/export.csv")
def export_csv():
    if request.args.get("token") != TOKEN:
        return "wrong token", 403
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEAD)
    for rec in load_all():
        for row in rows_from(rec):
            w.writerow(row)
    body = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return Response(body, mimetype="text/csv;charset=utf-8",
                    headers={"Content-Disposition":
                             "attachment; filename=LCF_all.csv"})


@APP.route("/admin")
def admin():
    if request.args.get("token") != TOKEN:
        return "wrong token", 403
    rows = []
    for rec in load_all():
        rows.extend(rows_from(rec))
    rows = [r for r in rows if r[6] != "(only overall comments were given)"]
    prio = {"High": 0, "Medium": 1, "Low": 2}
    rows.sort(key=lambda r: (prio.get(r[14], 3), r[7]))
    head = "".join(
        "<th>%s</th>" % h for h in
        ["#", "Category", "Module", "Class type", "Instructor", "Session",
         "Issue", "Description", "Scope", "Urgency", "Suggested change",
         "Meeting", "Reply-to"])
    body = ""
    for n, r in enumerate(rows, 1):
        cells = [n, r[6], r[7], r[8], r[9], r[10], r[11], r[12],
                 r[13], r[14], r[15], r[16],
                 (r[5] if r[4] == "Yes" else "")]
        body += ("<tr>" + "".join("<td>%s</td>" % (c if c is not None else "")
                                  for c in cells) + "</tr>")
    return """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>body{font:14px -apple-system,Segoe UI,Roboto,Arial;margin:16px}
table{border-collapse:collapse;width:100%%}
th,td{border:1px solid #dde3e9;padding:6px;text-align:left;vertical-align:top;font-size:12.5px}
th{background:#eef4fa;position:sticky;top:0}tr:nth-child(even){background:#fafbfc}
.hd{background:#0b3d6b;color:#fff;padding:14px;border-radius:10px;margin-bottom:12px}
.hd a{color:#cfe3f5;margin-right:14px}</style>
<div class=hd><b>LCF Live Dashboard</b> &nbsp; %d submissions / %d items
<br><br><a href="/export.csv?token=%s">Export all CSV</a>
<a href="/admin?token=%s">Refresh</a>
<a href="/count">Count</a></div>
<table><tr>%s</tr>%s</table>""" % (len(load_all()), len(rows), TOKEN, TOKEN,
                                   head, body)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "127.0.0.1"
    print("\n" + "=" * 62)
    print("  LCF survey server")
    print("  Students (same Wi-Fi) :  http://%s:%d" % (ip, port))
    print("  Dashboard             :  http://localhost:%d/admin?token=%s" % (port, TOKEN))
    print("  Export                :  http://localhost:%d/export.csv?token=%s" % (port, TOKEN))
    print("=" * 62 + "\n")
    APP.run(host="0.0.0.0", port=port, debug=False)
