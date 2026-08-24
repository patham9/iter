import subprocess, tempfile

DESCRIPTION = "Gallery wrapper for context, runtime, and atomspace dashboards"

HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Eray Index / Dashboard Gallery</title>
<style>
:root{
  color-scheme:dark;
  --bg:#0b0d10;
  --panel:#111419;
  --panel2:#0f1217;
  --line:#2a3039;
  --text:#d8dee9;
  --strong:#eef2f7;
  --muted:#808a98;
  --dim:#5f6977;
  --blue:#6ea8fe;
  --mono:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono",monospace;
  --sans:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}
*{box-sizing:border-box}
html,body{margin:0;width:100%;height:100%;background:var(--bg);color:var(--text);font-family:var(--sans)}
body{overflow:hidden}
.shell{height:100vh;display:grid;grid-template-rows:auto minmax(0,1fr)}
.topbar{
  display:flex;align-items:center;justify-content:space-between;gap:16px;
  min-height:58px;padding:9px 16px;background:var(--panel2);border-bottom:1px solid var(--line)
}
.brand{display:flex;align-items:baseline;gap:9px;min-width:0;white-space:nowrap}
.brand-title{color:var(--strong);font:700 14px/1.2 var(--mono)}
.brand-sub{color:var(--dim);font:10px/1.2 var(--mono)}
.tabs{display:flex;align-items:center;gap:6px;min-width:0}
.tab{
  appearance:none;border:1px solid var(--line);background:#12161c;color:#9aa4b1;
  padding:8px 13px;font:700 10px/1 var(--mono);letter-spacing:.04em;
  text-transform:uppercase;cursor:pointer
}
.tab:hover{border-color:#4a5564;color:#d2d8e1;background:#171c23}
.tab.active{border-color:#506b8f;background:#172231;color:#9ec9ff}
.actions{display:flex;align-items:center;gap:6px;white-space:nowrap}
.action{
  appearance:none;border:1px solid var(--line);background:#12161c;color:var(--muted);
  width:30px;height:30px;font:800 14px/1 var(--mono);cursor:pointer
}
.action:hover{color:var(--strong);border-color:#4a5564}
.stage{position:relative;min-width:0;min-height:0;background:#080a0d}

.frame{
  position:absolute;
  inset:0;
  width:100%;
  height:100%;
  border:0;
  display:block;
  visibility:hidden;
  pointer-events:none;
  background:var(--bg);
}
.frame.active{
  visibility:visible;
  pointer-events:auto;
}

@media(max-width:760px){
  .topbar{align-items:flex-start;flex-wrap:wrap;padding:8px}
  .brand{width:100%}
  .tabs{flex:1;overflow-x:auto;padding-bottom:1px}
  .tab{padding:8px 10px}
}
</style>
</head>
<body>
<div class="shell">
  <header class="topbar">
    <div class="brand">
      <span class="brand-title">Eray Index</span>
      <span class="brand-sub">/ Dashboard Gallery</span>
    </div>

    <nav class="tabs" aria-label="Dashboard selection">
      <button class="tab active" data-view="runtime">Runtime</button>
      <button class="tab" data-view="context">Context</button>
      <button class="tab" data-view="atomspace">Atomspace</button>
    </nav>

    <div class="actions">
      <button class="action" id="prev" title="Previous dashboard">‹</button>
      <button class="action" id="next" title="Next dashboard">›</button>
    </div>
  </header>

  <main class="stage">
    <iframe class="frame active" id="frame-runtime" src="dashboard_runtime.html" title="Runtime Dashboard"></iframe>
    <iframe class="frame" id="frame-context" src="dashboard_context.html" title="Context Dashboard"></iframe>
    <iframe class="frame" id="frame-atomspace" src="dashboard_atomspace.html" title="Atomspace Dashboard"></iframe>
  </main>
</div>

<script>
(function(){
  var views=["context","runtime","atomspace"];
  var current=0;

  function show(name, updateHash){
    var index=views.indexOf(name);
    if(index<0) index=0;
    current=index;

    document.querySelectorAll(".tab").forEach(function(el){
      el.classList.toggle("active", el.dataset.view===views[current]);
    });
    document.querySelectorAll(".frame").forEach(function(el){
      el.classList.toggle("active", el.id==="frame-"+views[current]);
    });

    if(updateHash!==false){
      history.replaceState(null,"","#"+views[current]);
    }
  }

  document.querySelectorAll(".tab").forEach(function(el){
    el.addEventListener("click",function(){ show(el.dataset.view,true); });
  });

  document.getElementById("prev").addEventListener("click",function(){
    show(views[(current-1+views.length)%views.length],true);
  });

  document.getElementById("next").addEventListener("click",function(){
    show(views[(current+1)%views.length],true);
  });

  document.addEventListener("keydown",function(e){
    if(e.key==="ArrowLeft") document.getElementById("prev").click();
    if(e.key==="ArrowRight") document.getElementById("next").click();
  });

  var initial=(location.hash||"").replace("#","");
  show(views.indexOf(initial)>=0 ? initial : "runtime", false);
})();
</script>
</body>
</html>
"""

def upload_html(html_doc):
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".html",
            delete=False,
            dir="/tmp",
            prefix="dashboard_gallery_"
        ) as f:
            f.write(html_doc)
            f.flush()
            tmp_path = f.name

        subprocess.Popen(
            [
                "bash", "-c",
                'scp -P 51357 -i ~/.ssh/max_nonlanguage_ed25519 "{}" '
                'max@wreading.xyz:/var/www/html-nonlang.dev/MeTTaSoul/mb/dashboard_gallery.html && '
                'ssh -p 51357 -i ~/.ssh/max_nonlanguage_ed25519 max@wreading.xyz '
                '"chmod 644 /var/www/html-nonlang.dev/MeTTaSoul/mb/dashboard_gallery.html" && '
                'rm -f "{}"'.format(tmp_path, tmp_path)
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception:
        pass

def transform(messages, tools):
    upload_html(HTML)
    return messages, tools

