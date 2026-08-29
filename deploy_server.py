#!/usr/bin/env python3
"""
Arena Deploy Server for NASDAQ EOD Momentum Scanner
Serves dashboard + API + health checks
"""
import os, json, subprocess, sys
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = ROOT / "output"

app = FastAPI(title="NASDAQ EOD Momentum Scanner - Deploy")

# Serve output as static at /output
if OUT.exists():
    app.mount("/output", StaticFiles(directory=str(OUT)), name="output")

@app.get("/health")
def health():
    return {
        "status": "ok",
        "time": datetime.utcnow().isoformat(),
        "universe": len(pd.read_csv(DATA / "nasdaq_universe.csv")) if (DATA / "nasdaq_universe.csv").exists() else 0,
        "has_scan": (OUT / "scan_results.csv").exists(),
        "has_dashboard": (OUT / "index.html").exists(),
        "has_featured_panel": (DATA / "featured_panel.parquet").exists(),
        "has_oos": (DATA / "oos_predictions.parquet").exists(),
        "hist_files": len(list(DATA.glob("hist_*.csv"))),
        "last_scan": json.load(open(OUT / "meta.json")).get("last_scan") if (OUT / "meta.json").exists() else None
    }

@app.get("/api/results")
def api_results():
    if not (OUT / "scan_results.csv").exists():
        return JSONResponse({"error": "no scan_results.csv"}, status_code=404)
    df = pd.read_csv(OUT / "scan_results.csv")
    return JSONResponse(df.head(100).to_dict(orient="records"))

@app.get("/api/meta")
def api_meta():
    if (OUT / "meta.json").exists():
        return JSONResponse(json.load(open(OUT / "meta.json")))
    return JSONResponse({"error": "no meta"}, status_code=404)

@app.get("/api/universe")
def api_universe():
    if not (DATA / "nasdaq_universe.csv").exists():
        return JSONResponse({"error": "no universe"}, status_code=404)
    df = pd.read_csv(DATA / "nasdaq_universe.csv")
    return {"count": len(df), "sample": df.head(20).to_dict(orient="records")}

def run_cmd(cmd, env_extra=None):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(cmd, shell=True, cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=600)
    return {"code": proc.returncode, "stdout": proc.stdout[-5000:], "stderr": proc.stderr[-5000:]}

@app.post("/api/update_universe")
def update_universe():
    res = run_cmd(f"{sys.executable} src/update_universe.py")
    return res

@app.post("/api/download_history")
def download_history(background_tasks: BackgroundTasks, incremental: bool = False):
    # Run in background if full download
    def task():
        env = {"INCREMENTAL": "1"} if incremental else {}
        run_cmd(f"{sys.executable} src/download_history.py", env_extra=env)
    if not incremental:
        background_tasks.add_task(task)
        return {"status": "started in background", "mode": "full 2y"}
    else:
        return run_cmd(f"{sys.executable} src/download_history.py", env_extra={"INCREMENTAL":"1"})

@app.post("/api/prep_panel")
def prep_panel():
    return run_cmd(f"{sys.executable} src/prep_panel.py")

@app.post("/api/backtest")
def backtest():
    return run_cmd(f"{sys.executable} src/backtest.py")

@app.post("/api/scan")
def scan():
    return run_cmd(f"{sys.executable} src/scan.py")

@app.post("/api/build_dashboard")
def build_dashboard():
    return run_cmd(f"{sys.executable} src/build_dashboard.py")

@app.get("/", response_class=HTMLResponse)
def index():
    # Serve the built dashboard if exists, else a deploy UI
    if (OUT / "index.html").exists():
        return FileResponse(OUT / "index.html")
    return HTMLResponse(f"""
    <html><body style="font-family: sans-serif; background:#0d1117; color:#e6edf3; padding:30px">
    <h1>NASDAQ EOD Scanner - Deploy Server</h1>
    <p>Dashboard not built yet. Output files missing.</p>
    <ul>
      <li><a href="/health" style="color:#58a6ff">/health</a> - check status</li>
      <li><a href="/output/" style="color:#58a6ff">/output/</a> - static files</li>
    </ul>
    <p>Run pipeline via API:</p>
    <pre>
POST /api/update_universe
POST /api/download_history?incremental=false
POST /api/prep_panel
POST /api/backtest
POST /api/scan
POST /api/build_dashboard
    </pre>
    </body></html>
    """)

@app.get("/deploy", response_class=HTMLResponse)
def deploy_ui():
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deploy Control - EOD Scanner</title>
<style>
body{margin:0;background:#0d1117;color:#e6edf3;font-family:system-ui,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:24px}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:18px;margin:12px 0}
.btn{background:#238636;color:#fff;border:none;border-radius:8px;padding:10px 16px;font-weight:700;cursor:pointer;margin:4px}
.btn.blue{background:#1f6feb}
.btn.gray{background:#21262d}
pre{background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:12px;overflow:auto;max-height:400px;white-space:pre-wrap}
a{color:#58a6ff}
</style></head><body>
<div class="wrap">
<h1>🚀 EOD Scanner Deploy Panel</h1>
<div class="card">
<h3>Статус</h3>
<pre id="health">loading...</pre>
<button class="btn gray" onclick="loadHealth()">Refresh</button>
<a class="btn blue" href="/" style="text-decoration:none;display:inline-block">Открыть Дашборд</a>
<a class="btn gray" href="/output/scan_results.csv" style="text-decoration:none;display:inline-block">CSV</a>
</div>
<div class="card">
<h3>Пайплайн (по порядку)</h3>
<button class="btn" onclick="run('/api/update_universe')">1. Update Universe</button>
<button class="btn" onclick="run('/api/download_history?incremental=true')">2a. Download Incremental</button>
<button class="btn" onclick="run('/api/download_history?incremental=false')">2b. Download Full (2y) - долго</button>
<button class="btn" onclick="run('/api/prep_panel')">3. Prep Panel</button>
<button class="btn" onclick="run('/api/backtest')">4. Backtest</button>
<button class="btn" onclick="run('/api/scan')">5. Scan (15:30 ET)</button>
<button class="btn blue" onclick="run('/api/build_dashboard')">6. Build Dashboard</button>
<pre id="log">Лог выполнения появится тут...</pre>
</div>
<div class="card">
<h3>Результаты последнего скана</h3>
<pre id="results">loading...</pre>
</div>
</div>
<script>
async function loadHealth(){
  let r = await fetch('/health'); let j = await r.json();
  document.getElementById('health').textContent = JSON.stringify(j,null,2);
  let r2 = await fetch('/api/results'); 
  if(r2.ok){ let j2 = await r2.json(); document.getElementById('results').textContent = JSON.stringify(j2.slice(0,5),null,2); }
  else { document.getElementById('results').textContent = 'no results yet'; }
}
async function run(url){
  document.getElementById('log').textContent = '⏳ Running '+url+' ...';
  let r = await fetch(url,{method:'POST'});
  let j = await r.json();
  document.getElementById('log').textContent = JSON.stringify(j,null,2);
  loadHealth();
}
loadHealth();
</script>
</body></html>
    """)
