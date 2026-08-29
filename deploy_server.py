#!/usr/bin/env python3
"""
Production Deploy Server for NASDAQ EOD Momentum Scanner
Serves dashboard + API + health checks + full pipeline control
"""
import os, json, subprocess, sys, glob, time
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = ROOT / "output"

app = FastAPI(
    title="NASDAQ EOD Momentum Scanner - Deploy",
    version="2.0",
    description="EOD Momentum Scanner: signal 15:30 ET → entry close → target +2..5% in 24-48h"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve output as static at /output
if OUT.exists():
    app.mount("/output", StaticFiles(directory=str(OUT)), name="output")

# Global state for background jobs
JOBS = {}

def run_cmd(cmd, env_extra=None, timeout=1800):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(cmd, shell=True, cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=timeout)
        return {"code": proc.returncode, "stdout": proc.stdout[-8000:], "stderr": proc.stderr[-4000:], "cmd": cmd}
    except subprocess.TimeoutExpired as e:
        return {"code": -1, "stdout": (e.stdout or "")[-8000:] if hasattr(e,'stdout') else "", "stderr": f"TIMEOUT after {timeout}s", "cmd": cmd}

@app.get("/health")
def health():
    try:
        uni_count = len(pd.read_csv(DATA / "nasdaq_universe.csv")) if (DATA / "nasdaq_universe.csv").exists() else 0
    except:
        uni_count = 0
    meta = {}
    if (OUT / "meta.json").exists():
        try:
            meta = json.load(open(OUT / "meta.json"))
        except:
            meta = {}
    # last runs from git log
    try:
        runs = subprocess.check_output(f"cd {ROOT} && git log --oneline -n 5", shell=True, text=True, timeout=5)
    except:
        runs = ""
    return {
        "status": "ok",
        "version": "2.0",
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "time_et": datetime.now().astimezone().isoformat(),
        "universe": uni_count,
        "has_scan": (OUT / "scan_results.csv").exists(),
        "has_dashboard": (OUT / "index.html").exists(),
        "has_featured_panel": (DATA / "featured_panel.parquet").exists(),
        "has_oos": (DATA / "oos_predictions.parquet").exists(),
        "hist_files": len(list(DATA.glob("hist_*.csv"))),
        "last_scan": meta.get("last_scan"),
        "scanned": meta.get("scanned"),
        "generated_utc": meta.get("generated_utc"),
        "git_last_5": runs,
        "disk_data_mb": round(sum(f.stat().st_size for f in DATA.glob("*") if f.is_file()) / 1024 / 1024, 1) if DATA.exists() else 0,
        "disk_output_mb": round(sum(f.stat().st_size for f in OUT.glob("*") if f.is_file()) / 1024 / 1024, 1) if OUT.exists() else 0,
    }

@app.get("/api/results")
def api_results(limit: int = 100):
    if not (OUT / "scan_results.csv").exists():
        return JSONResponse({"error": "no scan_results.csv"}, status_code=404)
    df = pd.read_csv(OUT / "scan_results.csv")
    return JSONResponse(df.head(limit).to_dict(orient="records"))

@app.get("/api/top")
def api_top():
    if not (OUT / "scan_results.csv").exists():
        return JSONResponse({"error": "no scan_results.csv"}, status_code=404)
    df = pd.read_csv(OUT / "scan_results.csv").sort_values("prob", ascending=False)
    return {
        "last_scan": df['date'].iloc[0] if len(df) else None,
        "count": len(df),
        "top_10": df.head(10)[["ticker","close","prob","hit","avg_best","gap_sig_p","ret_1","rsi14","vol_ratio"]].to_dict(orient="records"),
        "picks": df.head(2)['ticker'].tolist()
    }

@app.get("/api/meta")
def api_meta():
    if (OUT / "meta.json").exists():
        return JSONResponse(json.load(open(OUT / "meta.json")))
    return JSONResponse({"error": "no meta"}, status_code=404)

@app.get("/api/universe")
def api_universe(limit: int = 50):
    if not (DATA / "nasdaq_universe.csv").exists():
        return JSONResponse({"error": "no universe"}, status_code=404)
    df = pd.read_csv(DATA / "nasdaq_universe.csv")
    return {"count": len(df), "sample": df.head(limit).to_dict(orient="records")}

@app.get("/api/backtest_summary")
def api_backtest():
    if not (DATA / "oos_predictions.parquet").exists():
        return JSONResponse({"error": "no oos_predictions.parquet - run backtest"}, status_code=404)
    try:
        oos = pd.read_parquet(DATA / "oos_predictions.parquet")
        oos["selected"] = oos.groupby("model_idx")["prob"].rank(pct=True) >= 0.90
        sel = oos[oos["selected"]]
        return {
            "total_rows": len(oos),
            "selected_rows": len(sel),
            "base_hit": float(oos["target_2pct"].mean()),
            "strategy_hit": float(sel["target_2pct"].mean()),
            "base_best": float(oos["best_fwd"].mean()),
            "strategy_best": float(sel["best_fwd"].mean()),
            "months": int(oos["model_idx"].nunique()),
            "tickers": int(oos["ticker"].nunique()),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/update_universe")
def update_universe():
    return run_cmd(f"{sys.executable} src/update_universe.py", timeout=120)

@app.post("/api/download_history")
def download_history(background_tasks: BackgroundTasks, incremental: bool = False, tickers: int = 0):
    # tickers param: if >0, download only top N from universe
    def task_full():
        JOBS['download'] = {"status": "running", "started": datetime.utcnow().isoformat()}
        env = {}
        if incremental:
            env["INCREMENTAL"] = "1"
        res = run_cmd(f"{sys.executable} src/download_history.py", env_extra=env, timeout=3600)
        JOBS['download'] = {"status": "done", "result": res, "finished": datetime.utcnow().isoformat()}
    
    if tickers > 0:
        # custom download for top N
        return run_cmd(f"{sys.executable} -c \"import pandas as pd, yfinance as yf; uni=pd.read_csv('data/nasdaq_universe.csv'); t=uni['symbol'].tolist()[:{tickers}]; print(f'Downloading {{len(t)}}'); import src.download_history as dh; dh.DATA_DIR='data'; dh.main()\" ", timeout=600)
    
    if not incremental:
        background_tasks.add_task(task_full)
        return {"status": "started in background", "mode": "full 2y", "job": "download", "check": "/api/jobs"}
    else:
        return run_cmd(f"{sys.executable} src/download_history.py", env_extra={"INCREMENTAL":"1"}, timeout=1800)

@app.post("/api/prep_panel")
def prep_panel():
    return run_cmd(f"{sys.executable} src/prep_panel.py", timeout=600)

@app.post("/api/backtest")
def backtest(background_tasks: BackgroundTasks):
    def task():
        JOBS['backtest'] = {"status": "running", "started": datetime.utcnow().isoformat()}
        res = run_cmd(f"{sys.executable} src/backtest.py", timeout=1800)
        JOBS['backtest'] = {"status": "done", "result": res, "finished": datetime.utcnow().isoformat()}
    background_tasks.add_task(task)
    return {"status": "started in background", "job": "backtest", "check": "/api/jobs"}

@app.post("/api/scan")
def scan():
    return run_cmd(f"{sys.executable} src/scan.py", timeout=600)

@app.post("/api/build_dashboard")
def build_dashboard():
    # Auto-update PICKS to top 2 before build
    try:
        if (OUT / "scan_results.csv").exists():
            df = pd.read_csv(OUT / "scan_results.csv").sort_values("prob", ascending=False)
            top2 = df.head(2)['ticker'].tolist()
            # update build_dashboard.py PICKS
            path = ROOT / "src" / "build_dashboard.py"
            content = path.read_text()
            import re
            new_content = re.sub(r'PICKS\s*=\s*\[.*?\]', f'PICKS = {top2}', content)
            if new_content != content:
                path.write_text(new_content)
    except Exception as e:
        print(f"PICKS auto-update failed: {e}")
    return run_cmd(f"{sys.executable} src/build_dashboard.py", timeout=120)

@app.post("/api/full_pipeline")
def full_pipeline(background_tasks: BackgroundTasks, fast: bool = False):
    """
    Full pipeline in background: update_universe -> download (incremental) -> prep_panel -> scan -> dashboard
    fast=True skips backtest and uses incremental download
    """
    def task():
        JOBS['full_pipeline'] = {"status": "running", "started": datetime.utcnow().isoformat(), "steps": []}
        steps = [
            ("update_universe", f"{sys.executable} src/update_universe.py", {}, 120),
            ("download", f"{sys.executable} src/download_history.py", {"INCREMENTAL": "1"}, 1800),
            ("prep_panel", f"{sys.executable} src/prep_panel.py", {}, 600),
            ("scan", f"{sys.executable} src/scan.py", {}, 600),
            ("dashboard", f"{sys.executable} src/build_dashboard.py", {}, 120),
        ]
        if not fast:
            steps.insert(3, ("backtest", f"{sys.executable} src/backtest.py", {}, 1800))
        
        results = {}
        for name, cmd, env, to in steps:
            JOBS['full_pipeline']["current"] = name
            res = run_cmd(cmd, env_extra=env, timeout=to)
            results[name] = res
            JOBS['full_pipeline']["steps"].append({name: res["code"]})
            if res["code"] != 0:
                JOBS['full_pipeline']["status"] = f"failed at {name}"
                JOBS['full_pipeline']["results"] = results
                return
        JOBS['full_pipeline']["status"] = "done"
        JOBS['full_pipeline']["results"] = results
        JOBS['full_pipeline']["finished"] = datetime.utcnow().isoformat()
    
    background_tasks.add_task(task)
    return {"status": "full pipeline started in background", "fast": fast, "job": "full_pipeline", "check": "/api/jobs"}

@app.get("/api/jobs")
def jobs():
    return JOBS

@app.get("/api/logs")
def logs():
    # tail of output files
    out = {}
    if (OUT / "scan_results.csv").exists():
        try:
            df = pd.read_csv(OUT / "scan_results.csv")
            out["scan_top5"] = df.head(5).to_dict(orient="records")
        except:
            pass
    return out

@app.get("/", response_class=HTMLResponse)
def index():
    if (OUT / "index.html").exists():
        return FileResponse(OUT / "index.html")
    return HTMLResponse("""
    <html><body style="font-family:sans-serif;background:#0d1117;color:#e6edf3;padding:30px">
    <h1>NASDAQ EOD Scanner - Deploy Server v2.0</h1>
    <p>Dashboard not built yet.</p>
    <a href="/deploy" style="color:#58a6ff">Go to Deploy Panel</a> | <a href="/health" style="color:#58a6ff">Health</a>
    </body></html>
    """)

@app.get("/deploy", response_class=HTMLResponse)
def deploy_ui():
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deploy Control v2 - EOD Scanner</title>
<style>
body{margin:0;background:#0d1117;color:#e6edf3;font-family:system-ui,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:18px;margin:12px 0}
.btn{background:#238636;color:#fff;border:none;border-radius:8px;padding:10px 16px;font-weight:700;cursor:pointer;margin:4px}
.btn.blue{background:#1f6feb}
.btn.orange{background:#d29922;color:#000}
.btn.gray{background:#21262d}
.btn.red{background:#da3633}
pre{background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:12px;overflow:auto;max-height:500px;white-space:pre-wrap;font-size:12px}
a{color:#58a6ff;text-decoration:none}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
h1{margin:0 0 6px}
small{color:#8b949e}
</style></head><body>
<div class="wrap">
<h1>🚀 EOD Scanner Deploy v2.0</h1>
<small>Full control panel - NASDAQ EOD Momentum Scanner (signal 15:30 ET)</small>

<div class="card">
<h3>📊 Статус</h3>
<pre id="health">loading...</pre>
<div>
<button class="btn gray" onclick="loadHealth()">🔄 Refresh</button>
<a class="btn blue" href="/" style="display:inline-block">📈 Открыть Дашборд</a>
<a class="btn gray" href="/output/scan_results.csv" style="display:inline-block">📄 CSV</a>
<a class="btn gray" href="/api/top" style="display:inline-block">🔝 Top API</a>
<a class="btn gray" href="/health" style="display:inline-block">❤️ Health JSON</a>
</div>
</div>

<div class="grid">
<div class="card">
<h3>⚡ Быстрый пайплайн</h3>
<button class="btn" onclick="run('/api/full_pipeline?fast=true')">🚀 Fast Pipeline (без бэктеста)</button>
<button class="btn orange" onclick="run('/api/full_pipeline?fast=false')">🐢 Full Pipeline (с бэктестом)</button>
<p><small>Fast: universe → incremental → panel → scan → dashboard (~2-3 мин)<br>Full: + backtest (~10 мин)</small></p>
</div>
<div class="card">
<h3>🔧 Пошагово</h3>
<button class="btn gray" onclick="run('/api/update_universe')">1. Update Universe</button><br>
<button class="btn gray" onclick="run('/api/download_history?incremental=true')">2a. Download Incremental</button>
<button class="btn gray" onclick="run('/api/download_history?incremental=false')">2b. Download Full (долго)</button><br>
<button class="btn gray" onclick="run('/api/prep_panel')">3. Prep Panel</button>
<button class="btn gray" onclick="run('/api/backtest')">4. Backtest</button><br>
<button class="btn" onclick="run('/api/scan')">5. Scan (15:30 ET)</button>
<button class="btn blue" onclick="run('/api/build_dashboard')">6. Build Dashboard</button>
</div>
</div>

<div class="card">
<h3>📝 Лог выполнения</h3>
<pre id="log">Лог появится тут...</pre>
</div>

<div class="grid">
<div class="card">
<h3>📈 Топ скана</h3>
<pre id="top">loading...</pre>
</div>
<div class="card">
<h3>🧪 Бэктест</h3>
<pre id="bt">loading...</pre>
<button class="btn gray" onclick="loadBT()">Load Backtest</button>
</div>
</div>

<div class="card">
<h3>📋 Jobs (фоновые задачи)</h3>
<pre id="jobs">-</pre>
<button class="btn gray" onclick="loadJobs()">Refresh Jobs</button>
</div>

<div class="card">
<h3>ℹ️ Инфо</h3>
<ul style="color:#c9d1d9;font-size:13px;line-height:1.6">
<li><b>Deploy Key:</b> <code>deploy/keys/id_ed25519_algotrade</code> - для <code>./deploy/push.sh</code></li>
<li><b>GitHub Pages:</b> Settings → Pages → Source: GitHub Actions (одноразово)</li>
<li><b>Автоскан:</b> workflow <code>daily_scan.yml</code> - будни 15:30 ET (19:30 UTC летом)</li>
<li><b>Ручной скан:</b> Actions → Run workflow или кнопка на дашборде (нужен SCAN_TRIGGER_TOKEN)</li>
<li><b>Docker:</b> <code>docker-compose up -d</code> - поднимет scanner + scheduler</li>
<li><b>Локально:</b> <code>make all</code> - полный пайплайн</li>
</ul>
</div>

</div>
<script>
async function loadHealth(){
  let r = await fetch('/health'); let j = await r.json();
  document.getElementById('health').textContent = JSON.stringify(j,null,2);
  let r2 = await fetch('/api/top');
  if(r2.ok){ let j2 = await r2.json(); document.getElementById('top').textContent = JSON.stringify(j2,null,2); }
}
async function loadBT(){
  let r = await fetch('/api/backtest_summary');
  let t = await r.text();
  document.getElementById('bt').textContent = t;
}
async function loadJobs(){
  let r = await fetch('/api/jobs'); let j = await r.json();
  document.getElementById('jobs').textContent = JSON.stringify(j,null,2);
}
async function run(url){
  document.getElementById('log').textContent = '⏳ Running '+url+' ...';
  let r = await fetch(url,{method:'POST'});
  let txt = await r.text();
  try{ let j = JSON.parse(txt); document.getElementById('log').textContent = JSON.stringify(j,null,2); }
  catch{ document.getElementById('log').textContent = txt.slice(0,8000); }
  setTimeout(()=>{loadHealth(); loadJobs();}, 1000);
}
loadHealth(); loadBT(); loadJobs();
setInterval(loadJobs, 5000);
</script>
</body></html>
    """)
