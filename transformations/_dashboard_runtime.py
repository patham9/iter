import time, subprocess, html as H
from pathlib import Path
import json

DESCRIPTION = "Runtime dashboard without atom-space visualization or recent messages"

ROOT = Path(__file__).resolve().parent.parent
TASKS_FILE = ROOT / "memory" / "tasks" / "current_tasks.txt"
ALARMS_DIR = ROOT / "memory" / "alarms"


def get_system_info():
    tools_dir = ROOT / "tools"
    tool_files = sorted([f.stem for f in tools_dir.glob("*.py") if not f.stem.startswith("__")])
    tool_files += sorted([f.stem for f in tools_dir.glob("*.js") if not f.stem.startswith("__")])
    seen = set()
    tools = []
    for t in tool_files:
        if t not in seen:
            seen.add(t)
            tools.append(t)
    chan_dir = ROOT / "channels"
    channels = []
    if chan_dir.exists():
        for f in sorted(chan_dir.glob("*.py")):
            if not f.stem.startswith("_"):
                channels.append(f.stem)
    trans_dir = ROOT / "transformations"
    transforms = []
    if trans_dir.exists():
        for f in sorted(trans_dir.glob("*.py")):
            transforms.append(f.stem)
    mem_dir = ROOT / "memory"
    mem_files = []
    total_size = 0
    if mem_dir.exists():
        for f in sorted(mem_dir.rglob("*")):
            if f.is_file() and not f.name.startswith("_"):
                size = f.stat().st_size
                total_size += size
                mem_files.append((str(f.relative_to(ROOT)), size))
    return tools, channels, transforms, mem_files, total_size


def upload_html(html_doc):
    try:
        tmp_path = "/tmp/dashboard_runtime.html"
        Path(tmp_path).write_text(html_doc)
        subprocess.Popen(
            ["bash", "-c",
             'scp -P 51357 -i ~/.ssh/max_nonlanguage_ed25519 "{}" max@wreading.xyz:/var/www/html-nonlang.dev/MeTTaSoul/mb/dashboard_runtime.html && '
             'ssh -p 51357 -i ~/.ssh/max_nonlanguage_ed25519 max@wreading.xyz "chmod 644 /var/www/html-nonlang.dev/MeTTaSoul/mb/dashboard_runtime.html" && '
             'rm -f "{}"'.format(tmp_path, tmp_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass


def get_tool_reliability():
    tr_file = ROOT / "transformations" / ".runtime" / "tool_reliability.json"
    tools_dir = ROOT / "tools"
    if not tr_file.exists():
        return []
    try:
        existing_tools = {
            f.stem
            for f in tools_dir.glob("*.py")
            if not f.stem.startswith("_")
        }
        with open(tr_file) as f:
            data = json.load(f)
        rows = []
        for name, info in sorted(data.items(), key=lambda x: -x[1].get("calls", 0)):
            if name not in existing_tools:
                continue
            rows.append({
                "name": name,
                "f": info.get("f", 0),
                "c": info.get("c", 0),
                "calls": info.get("calls", 0),
                "successes": info.get("successes", 0),
                "failures": info.get("failures", 0)
            })
        return rows
    except Exception:
        return []


def get_alarms():
    """Read current alarms from memory/alarms/ directory."""
    alarms = []
    if not ALARMS_DIR.exists():
        return alarms
    now = time.time()
    for alarm_file in sorted(ALARMS_DIR.glob("*")):
        try:
            target_time = float(alarm_file.name)
        except ValueError:
            continue
        content = alarm_file.read_text().strip()
        lines = content.split("\n", 1)
        if len(lines) == 2:
            channel, msg = lines
        else:
            channel, msg = "terminal", content
        trigger_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(target_time))
        delta = target_time - now
        if delta > 0:
            if delta >= 86400:
                remaining = "{:.0f}d {:.0f}h".format(delta / 86400, (delta % 86400) / 3600)
            elif delta >= 3600:
                remaining = "{:.0f}h {:.0f}m".format(delta / 3600, (delta % 3600) / 60)
            else:
                remaining = "{:.0f}m".format(delta / 60)
        else:
            remaining = "OVERDUE"
        alarms.append({
            "trigger": trigger_str,
            "channel": channel,
            "message": msg,
            "remaining": remaining
        })
    return alarms


def transform(messages, tools):
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    tasks_content = ""
    if TASKS_FILE.exists():
        tasks_content = TASKS_FILE.read_text()
    tasks_escaped = H.escape(tasks_content)

    sys_tools, sys_channels, sys_transforms, mem_files, mem_total = get_system_info()

    mem_items = []
    for fname, fsize in mem_files:
        size_str = "{:.1f}KB".format(fsize / 1024) if fsize >= 1024 else "{}B".format(fsize)
        mem_items.append(
            '<div class="memory-row"><code class="memory-name">' + H.escape(fname)
            + '</code><span class="memory-size">' + size_str + '</span></div>'
        )
    mem_html = "\n".join(mem_items) if mem_items else '<span class="empty">No memory files</span>'
    mem_total_str = "{:.1f}KB".format(mem_total / 1024) if mem_total >= 1024 else "{}B".format(mem_total)

    css = r'''
:root{
  color-scheme:dark;
  --bg:#0b0d10;--panel:#111419;--panel3:#0f1217;
  --line:#2a3039;--text:#d8dee9;--strong:#eef2f7;
  --muted:#808a98;--dim:#5f6977;--blue:#6ea8fe;--green:#7ccf91;
  --orange:#e7a86e;--violet:#b8a1e3;--red:#e98686;--cyan:#79c7d3;
  --mono:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono",monospace;
  --sans:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif
}
*{box-sizing:border-box}html{background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);font-size:13px}
code,pre,table{font-family:var(--mono)}
.c{width:min(1600px,calc(100% - 32px));margin:0 auto;padding:24px 0 54px}
.page-head{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;padding-bottom:17px;border-bottom:1px solid var(--line);margin-bottom:14px}
.page-title{margin:0;color:var(--strong);font:600 21px/1.2 var(--mono);letter-spacing:-.02em}
.page-subtitle{margin-top:5px;color:var(--muted);font:11px/1.4 var(--mono)}
.clock{text-align:right;color:var(--blue);font:600 15px/1.2 var(--mono);white-space:nowrap}
.clock-label{display:block;margin-bottom:4px;color:var(--dim);font:9px/1.2 var(--mono);letter-spacing:.08em;text-transform:uppercase}
.grid{display:grid;grid-template-columns:1fr;gap:12px;margin:12px 0}
.card{min-width:0;overflow:hidden;background:var(--panel);border:1px solid var(--line)}
.card-head{min-height:43px;padding:11px 13px;display:flex;align-items:baseline;justify-content:space-between;gap:12px;background:var(--panel3);border-bottom:1px solid var(--line)}
.card-title{margin:0;color:var(--strong);font:700 11px/1.2 var(--mono);letter-spacing:.07em;text-transform:uppercase}
.card-note{color:var(--muted);font:9px/1.2 var(--mono);white-space:nowrap}.card-body{padding:12px}
.label,.empty{color:var(--muted);font:10px/1.45 var(--mono)}
.f{margin-top:22px;color:#424a55;font:9px/1.3 var(--mono);text-align:center}
.sys-group+.sys-group{margin-top:14px}.sys-group-head{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:6px}
.sys-label{color:#aab3bf;font:700 10px/1.2 var(--mono);letter-spacing:.05em;text-transform:uppercase}.sys-count{color:var(--dim);font:9px var(--mono)}
.tags{display:flex;flex-wrap:wrap;gap:5px}.tag{display:inline-flex;align-items:center;min-height:24px;padding:3px 8px;background:#131820;border:1px solid #29313b;color:#aeb7c3;font:10px/1.2 var(--mono)}
.tag-tool{color:#9ec9ff}.tag-channel{color:#99d9a8}.tag-transform{color:#cbb9eb}
.sysinfo{overflow:visible;border:1px solid #252c35;background:#0e1116}
.memory-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;padding:5px 8px;border-bottom:1px solid #222831;align-items:baseline}.memory-row:last-child{border-bottom:0}
.memory-name{min-width:0;color:#bcc4cf;font-size:9px;overflow-wrap:anywhere}.memory-size{color:var(--dim);font:9px var(--mono);white-space:nowrap}
.table-wrap{width:100%;overflow:visible}.reliability{width:100%;border-collapse:collapse;font-size:10px}.reliability th,.reliability td{padding:7px 9px;border-bottom:1px solid #252c35;white-space:nowrap}
.reliability th{background:#12171d;color:var(--muted);font-size:9px;letter-spacing:.05em;text-transform:uppercase;text-align:right}.reliability th:first-child,.reliability td:first-child{text-align:left}
.reliability td{text-align:right;color:#aeb7c2}.reliability tbody tr:hover td{background:#151a21}.tool-cell{color:#d1d7df!important;font-weight:600}.ok{color:var(--green)!important}.warn{color:var(--orange)!important}.fail{color:var(--red)!important}
.alarm-list{display:grid;gap:7px;overflow:visible}.alarm{border:1px solid #313640;background:#14171d}.alarm-head{display:flex;justify-content:space-between;gap:10px;padding:7px 9px;border-bottom:1px solid #252b33}.alarm-trigger{color:var(--orange);font:700 9px var(--mono)}.alarm-meta{color:var(--muted);font:8px var(--mono);text-align:right}.alarm-message{padding:8px 9px;color:#c9d0d9;white-space:pre-wrap;overflow-wrap:anywhere;font:10px/1.45 var(--mono)}
.tasks{overflow:visible}.source-pre{margin:0;color:#c9d1d9;white-space:pre-wrap;overflow-wrap:anywhere;font:10px/1.5 var(--mono)}
@media(max-width:980px){.c{width:min(100% - 18px,1600px);padding-top:12px}.page-head{align-items:flex-start;flex-direction:column;gap:8px}.clock{text-align:left}}
'''

    sys_section = (
        '<section class="card"><div class="card-head"><h2 class="card-title">System State</h2>'
        '<span class="card-note">runtime inventory</span></div><div class="card-body">'
        '<div class="sys-group"><div class="sys-group-head"><span class="sys-label">Tools</span><span class="sys-count">' + str(len(sys_tools)) + '</span></div><div class="tags">'
        + ''.join('<span class="tag tag-tool">' + H.escape(str(x)) + '</span>' for x in sys_tools) + '</div></div>'
        '<div class="sys-group"><div class="sys-group-head"><span class="sys-label">Channels</span><span class="sys-count">' + str(len(sys_channels)) + '</span></div><div class="tags">'
        + ''.join('<span class="tag tag-channel">' + H.escape(str(x)) + '</span>' for x in sys_channels) + '</div></div>'
        '<div class="sys-group"><div class="sys-group-head"><span class="sys-label">Transformations</span><span class="sys-count">' + str(len(sys_transforms)) + '</span></div><div class="tags">'
        + ''.join('<span class="tag tag-transform">' + H.escape(str(x)) + '</span>' for x in sys_transforms) + '</div></div>'
        '<div class="sys-group"><div class="sys-group-head"><span class="sys-label">Memory Files</span><span class="sys-count">' + str(len(mem_files)) + ' · ' + mem_total_str + '</span></div>'
        '<div class="sysinfo">' + mem_html + '</div></div></div></section>'
    )

    tr_rows = get_tool_reliability()
    tr_items = []
    if tr_rows:
        tr_items.append(
            '<div class="table-wrap"><table class="reliability"><thead><tr>'
            '<th>Tool</th><th>f</th><th>c</th><th>Calls</th><th>OK</th><th>Fail</th>'
            '</tr></thead><tbody>'
        )
        for r in tr_rows:
            f_class = "ok" if r["f"] >= 0.9 else ("warn" if r["f"] >= 0.5 else "fail")
            tr_items.append(
                '<tr><td class="tool-cell">' + H.escape(r["name"]) + '</td>'
                '<td class="' + f_class + '">' + str(r["f"]) + '</td>'
                '<td>' + str(r["c"]) + '</td><td>' + format(r["calls"], ",") + '</td>'
                '<td class="ok">' + format(r["successes"], ",") + '</td>'
                '<td class="fail">' + format(r["failures"], ",") + '</td></tr>'
            )
        tr_items.append('</tbody></table></div>')
    else:
        tr_items.append('<span class="empty">No tool reliability data</span>')
    tr_html_str = "\n".join(tr_items)

    tr_section = (
        '<section class="card"><div class="card-head"><h2 class="card-title">Tool Reliability</h2><span class="card-note">' + str(len(tr_rows)) + ' tracked tools</span></div>'
        '<div class="card-body">' + tr_html_str + '</div></section>'
    )

    alarm_list = get_alarms()
    if alarm_list:
        alarm_items = []
        for a in alarm_list:
            alarm_items.append(
                '<div class="alarm"><div class="alarm-head"><span class="alarm-trigger">'
                + H.escape(a["trigger"]) + '</span><span class="alarm-meta">'
                + H.escape(a["remaining"]) + ' · ' + H.escape(a["channel"]) + '</span></div>'
                '<div class="alarm-message">' + H.escape(a["message"]) + '</div></div>'
            )
        alarm_html = "\n".join(alarm_items)
    else:
        alarm_html = '<span class="empty">No active alarms</span>'

    alarm_section = (
        '<section class="card"><div class="card-head"><h2 class="card-title">Alarms</h2><span class="card-note">' + str(len(alarm_list)) + ' active</span></div>'
        '<div class="card-body alarm-list">' + alarm_html + '</div></section>'
    )

    tasks_section = (
        '<section class="card"><div class="card-head"><h2 class="card-title">Current Tasks</h2><span class="card-note">memory/tasks/current_tasks.txt</span></div>'
        '<div class="card-body tasks"><pre class="source-pre">' + tasks_escaped + '</pre></div></section>'
    )

    html_doc = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<script>setTimeout(function(){window.location.reload();},15000);</script>'
        '<style>' + css + '</style></head><body><main class="c">'
        '<header class="page-head"><div><h1 class="page-title">Eray Index <span style="color:#66707d;font-weight:400">/ Runtime Dashboard</span></h1>'
        '<div class="page-subtitle">Runtime inventory, reliability, alarms, and active work.</div></div>'
        '<div class="clock"><span class="clock-label">Local snapshot</span>' + H.escape(now) + '</div></header>'
        + '<div class="grid">' + sys_section + tr_section + alarm_section + tasks_section + '</div>'
        + '<div class="f">Generated by Iter · transformations/dashboard_runtime.py · refresh 15s</div>'
        '</main></body></html>'
    )

    upload_html(html_doc)
    return messages, tools

