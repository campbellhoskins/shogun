"""Build demo.html with real pipeline graph data, vis-network, importance-based sizing,
progressive traversal reveal, and action plan results."""
import json
import networkx as nx
from pathlib import Path

GRAPH_PATH = Path('data/final_graphs/shogun_pipeline_v1.json')

with open(GRAPH_PATH, encoding='utf-8') as f:
    g = json.load(f)

# ── Compute centrality metrics ──
G = nx.DiGraph()
for e in g['entities']:
    G.add_node(e['id'])
for r in g['relationships']:
    G.add_edge(r['source_id'], r['target_id'])

undirected = G.to_undirected()
betweenness_raw = nx.betweenness_centrality(undirected)
pagerank_raw = nx.pagerank(G, max_iter=200)
degree_raw = nx.degree_centrality(G)

def _min_max_normalize(values):
    vals = list(values.values())
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return {k: 0.5 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}

betweenness_norm = _min_max_normalize(betweenness_raw)
pagerank_norm = _min_max_normalize(pagerank_raw)
degree_norm = _min_max_normalize(degree_raw)

metrics = {}
for node_id in G.nodes:
    b = betweenness_norm[node_id]
    p = pagerank_norm[node_id]
    d = degree_norm[node_id]
    metrics[node_id] = round(0.40 * b + 0.35 * p + 0.25 * d, 4)

TYPE_COLORS = {
    "Agreement": "#818cf8", "Obligation": "#a78bfa", "Regulation": "#6366f1",
    "Organization": "#f97316", "ContactRole": "#fb923c", "Traveler": "#fbbf24",
    "Service": "#3b82f6", "Platform": "#22d3ee", "BookingChannel": "#2dd4bf", "Booking": "#34d399",
    "Incident": "#f43f5e", "SeverityLevel": "#ef4444", "RiskCategory": "#e879f9",
    "Alert": "#fbbf24", "TravelerResponseStatus": "#34d399", "DataElement": "#818cf8",
}

# ── Generate JS data ──
entity_lines = []
for e in g['entities']:
    skip = {'id','type','name','description','source_anchor','source_anchors','appears_in'}
    attrs = {}
    for k, v in e.items():
        if k in skip: continue
        if v is None or v == '' or v == [] or v == {}: continue
        if isinstance(v, bool) and not v: continue
        attrs[k] = v
    desc = e.get('description', '')[:300]
    imp = metrics.get(e['id'], 0)
    color = TYPE_COLORS.get(e['type'], '#6b7280')
    obj = {"id": e["id"], "type": e["type"], "name": e["name"], "desc": desc, "attrs": attrs, "importance": imp, "color": color}
    entity_lines.append('    ' + json.dumps(obj, ensure_ascii=False))

entities_js = 'const GRAPH_ENTITIES = [\n' + ',\n'.join(entity_lines) + '\n];\n'

rel_lines = []
for i, r in enumerate(g['relationships']):
    desc = r.get('description', '')[:200]
    obj = {"id": f"r{i}", "src": r["source_id"], "tgt": r["target_id"], "type": r["type"], "desc": desc}
    rel_lines.append('    ' + json.dumps(obj, ensure_ascii=False))

rels_js = 'const GRAPH_RELATIONSHIPS = [\n' + ',\n'.join(rel_lines) + '\n];\n'

# ── HTML Template ──
html = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Shogun — Duty of Care Knowledge Graph Demo</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800;1,9..40,400&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0b0f1a;--panel:#141b2d;--panel2:#1a2238;--border:#1e2a45;
  --text:#c9d1d9;--text2:#8b949e;--accent:#58a6ff;
  --red:#f85149;--amber:#d29922;--green:#3fb950;--purple:#bc8cff;
  --pink:#f778ba;--orange:#f0883e;--cyan:#39d2c0;
}
body{font-family:'DM Sans',system-ui,sans-serif;background:var(--bg);color:var(--text);height:100vh;display:flex;flex-direction:column;overflow:hidden}

/* ─── PROGRESS BAR ─── */
#progress-bar{position:fixed;top:0;left:0;right:0;height:3px;z-index:10000;display:flex;background:rgba(30,42,69,.5)}
#progress-bar .seg{flex:1;height:100%;transition:background .4s;background:transparent}
#progress-bar .seg.active{background:var(--accent)}
#progress-bar .seg.done{background:rgba(88,166,255,.3)}

/* ─── HEADER ─── */
header{padding:10px 20px;background:var(--panel);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:14px;flex-shrink:0;z-index:5}
header h1{font-size:14px;font-weight:700;letter-spacing:.2px}
header h1 span{color:var(--accent)}
header .tag{font-size:8px;background:var(--accent);color:#000;padding:2px 8px;border-radius:10px;font-weight:700;letter-spacing:.5px;text-transform:uppercase}
header .stats{font-size:10px;color:var(--text2);display:flex;gap:10px;margin-left:auto}
header .stats b{color:var(--accent)}

/* ─── MAIN LAYOUT ─── */
main{display:flex;flex:1;min-height:0}
#graph-wrap{flex:1;position:relative;background:var(--bg)}
#graph-container{width:100%;height:100%}
#graph-container::after{content:'';position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,transparent 0px,transparent 2px,rgba(255,255,255,.006) 2px,rgba(255,255,255,.006) 4px)}
#right-panel{width:420px;flex-shrink:0;border-left:1px solid var(--border);display:flex;flex-direction:column;background:var(--panel)}

/* ─── ZOOM ─── */
.zoom-controls{position:absolute;top:14px;right:14px;z-index:10;display:flex;flex-direction:column;gap:2px;background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:4px;box-shadow:0 4px 12px rgba(0,0,0,.3)}
.zoom-btn{width:30px;height:30px;border:none;background:transparent;color:var(--text2);font-size:15px;cursor:pointer;border-radius:6px;display:flex;align-items:center;justify-content:center;transition:all .15s;font-family:inherit}
.zoom-btn:hover{background:var(--panel2);color:var(--text)}
.zoom-div{height:1px;background:var(--border);margin:2px 4px}

/* ─── FLOATING ENTITY CARD ─── */
#entity-card{position:absolute;top:14px;left:14px;z-index:20;width:310px;max-height:48%;background:rgba(20,27,45,.94);backdrop-filter:blur(8px);border:1px solid var(--border);border-radius:10px;padding:14px 16px;overflow-y:auto;opacity:0;transform:translateY(-8px);transition:opacity .3s,transform .3s;pointer-events:none;box-shadow:0 8px 32px rgba(0,0,0,.4)}
#entity-card.visible{opacity:1;transform:translateY(0);pointer-events:all}
#entity-card .ec-close{position:absolute;top:6px;right:8px;background:none;border:none;color:var(--text2);font-size:14px;cursor:pointer;padding:2px 6px;border-radius:4px;line-height:1}
#entity-card .ec-close:hover{color:var(--text);background:var(--panel2)}
#entity-card .ec-name{font-size:14px;font-weight:700;margin-bottom:2px;padding-right:24px}
#entity-card .ec-type{font-size:10px;color:var(--accent);margin-bottom:6px;display:flex;align-items:center;gap:6px}
#entity-card .ec-dot{width:7px;height:7px;border-radius:2px;flex-shrink:0}
#entity-card .ec-desc{font-size:10px;color:var(--text2);line-height:1.5;margin-bottom:8px}
#entity-card table{width:100%;font-size:10px;border-collapse:collapse}
#entity-card td{padding:2px 0;vertical-align:top}
#entity-card td:first-child{color:var(--text2);width:42%;padding-right:6px}
#entity-card td:last-child{color:var(--text);font-weight:500}
#entity-card tr{border-bottom:1px solid rgba(30,42,69,.6)}

/* ─── LEGEND ─── */
#legend{position:absolute;bottom:10px;left:10px;background:rgba(20,27,45,.92);border:1px solid var(--border);border-radius:8px;padding:8px 12px;display:flex;flex-wrap:wrap;gap:4px 12px;z-index:10;max-width:600px}
#legend .item{display:flex;align-items:center;gap:4px;font-size:9px;color:var(--text2)}
#legend .dot{width:8px;height:8px;border-radius:2px;flex-shrink:0}

/* ─── RIGHT PANEL: SCENARIO SELECTOR ─── */
#panel-scenarios{flex:1;display:flex;flex-direction:column;padding:20px;overflow-y:auto}
#panel-scenarios h2{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:var(--text2);margin-bottom:14px;font-weight:600}
.scenario-btn{background:var(--panel2);border:1px solid var(--border);color:var(--text);padding:12px 14px;border-radius:10px;cursor:pointer;text-align:left;transition:all .2s;font-size:13px;margin-bottom:8px;font-family:inherit;width:100%;display:block}
.scenario-btn:hover{border-color:var(--accent);background:rgba(88,166,255,.06)}
.scenario-btn.active{border-color:var(--accent);background:rgba(88,166,255,.1);box-shadow:0 0 12px rgba(88,166,255,.12)}
.scenario-btn .sc-title{font-weight:700;color:#fff;display:block;margin-bottom:3px;font-size:13px}
.scenario-btn .sc-desc{color:var(--text2);font-size:11px;line-height:1.4}
.scenario-empty{color:var(--text2);font-size:12px;text-align:center;padding:40px 20px;line-height:1.6;font-style:italic}

/* ─── RIGHT PANEL: ACTIVE SCENARIO ─── */
#panel-active{flex:1;display:none;flex-direction:column;padding:20px;overflow-y:auto}
#panel-active h2{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:var(--text2);margin-bottom:14px;font-weight:600}
#step-progress{display:flex;gap:5px;margin-bottom:14px}
#step-progress .dot{width:10px;height:10px;border-radius:50%;background:var(--border);transition:background .3s;cursor:pointer}
#step-progress .dot.active{background:var(--accent);box-shadow:0 0 6px rgba(88,166,255,.4)}
#step-progress .dot.done{background:rgba(88,166,255,.4)}
#step-title{font-size:17px;font-weight:700;margin-bottom:6px;letter-spacing:-.2px}
#step-counter{font-size:11px;color:var(--accent);font-weight:600;margin-bottom:10px}
#step-desc{font-size:13px;color:var(--text2);line-height:1.6;margin-bottom:14px}
#manual-annotation{background:rgba(210,153,34,.06);border:1px solid rgba(210,153,34,.25);border-radius:8px;padding:12px;margin-bottom:14px;display:none}
#manual-annotation .m-label{font-size:9px;text-transform:uppercase;letter-spacing:.8px;color:var(--amber);font-weight:700;margin-bottom:4px}
#manual-annotation .m-text{font-size:12px;color:var(--amber);line-height:1.5;font-style:italic;opacity:.8}
#agent-log-wrap{flex:1;min-height:0;overflow:hidden;display:flex;flex-direction:column}
#agent-log-label{font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:var(--text2);margin-bottom:8px;font-weight:600}
#agent-log{flex:1;overflow-y:auto;background:#080a12;border:1px solid var(--border);border-radius:8px;padding:12px;font-family:'JetBrains Mono',monospace;font-size:11px;line-height:1.8}
#agent-log .log-line{opacity:0;animation:fadeIn .3s forwards}
#agent-log .qry{color:var(--cyan)}
#agent-log .trv{color:var(--purple)}
#agent-log .atr{color:var(--amber)}
#agent-log .dec{color:var(--green)}
#agent-log .wrn{color:var(--red)}
#agent-log .dim{color:var(--text2)}
@keyframes fadeIn{to{opacity:1}}
#controls{display:flex;gap:8px;margin-top:14px;flex-shrink:0}
#controls button{flex:1;padding:10px;background:var(--panel2);border:1px solid var(--border);color:var(--text);border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;transition:all .15s;font-family:inherit}
#controls button:hover{background:var(--accent);border-color:var(--accent);color:#000}
#controls button:disabled{opacity:.25;cursor:default;background:var(--panel2);border-color:var(--border);color:var(--text)}

/* ─── RIGHT PANEL: RESULTS ─── */
#panel-results{flex:1;display:none;flex-direction:column;padding:20px;overflow-y:auto}
#panel-results h2{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:var(--text2);margin-bottom:14px;font-weight:600}
.plan-header{padding:10px 0;border-bottom:1px solid var(--border);margin-bottom:12px}
.plan-incident{font-size:14px;color:#fff;font-weight:700}
.plan-severity{font-size:13px;font-weight:700;display:inline-block;padding:3px 12px;border-radius:6px;margin-top:6px}
.plan-severity.critical{background:rgba(248,81,73,.15);color:var(--red)}
.plan-severity.high{background:rgba(210,153,34,.15);color:var(--amber)}
.plan-severity.moderate{background:rgba(88,166,255,.15);color:var(--accent)}
.action-item{padding:10px 0;border-bottom:1px solid rgba(30,42,69,.6);animation:fadeSlide .4s ease both}
.action-item:last-child{border-bottom:none}
.action-name{font-size:13px;font-weight:600;color:#fff}
.action-meta{font-size:11px;color:var(--text2);margin-top:4px;line-height:1.6}
.action-meta span{display:inline-block;margin-right:10px}
.action-time{color:var(--purple)!important;font-weight:600}
.action-who{color:var(--green)!important}
@keyframes fadeSlide{from{opacity:0;transform:translateX(-10px)}to{opacity:1;transform:translateX(0)}}
.traversal-stats{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px;padding-top:12px;border-top:1px solid var(--border)}
.tstat{font-size:11px;color:var(--text2)}
.tstat strong{color:var(--cyan)}
.results-actions{margin-top:16px;display:flex;gap:8px}
.results-actions button{flex:1;padding:10px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;font-family:inherit;transition:all .15s}
.btn-another{background:var(--panel2);border:1px solid var(--border);color:var(--text)}
.btn-another:hover{border-color:var(--accent);color:var(--accent)}
.btn-restart{background:rgba(88,166,255,.1);border:1px solid rgba(88,166,255,.3);color:var(--accent)}
.btn-restart:hover{background:rgba(88,166,255,.2)}

/* ─── OVERLAYS ─── */
.overlay{position:fixed;inset:0;z-index:9000;background:rgba(8,10,18,.95);backdrop-filter:blur(12px);display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .5s}
.overlay.visible{opacity:1;pointer-events:all}
.ov-card{max-width:780px;width:92%;text-align:center;animation:slideUp .5s ease .1s both}
@keyframes slideUp{from{transform:translateY(24px);opacity:0}to{transform:translateY(0);opacity:1}}
.ov-card h2{font-size:38px;font-weight:800;line-height:1.15;margin-bottom:20px;letter-spacing:-.5px}
.ov-card h2 .hl{color:var(--accent)}
.ov-card p{font-size:15px;color:var(--text2);line-height:1.7;margin-bottom:16px;max-width:620px;margin-left:auto;margin-right:auto}
.ov-callout{font-size:13px;color:var(--amber);font-weight:600;padding:12px 20px;border:1px solid rgba(210,153,34,.2);border-radius:8px;background:rgba(210,153,34,.06);display:inline-block;margin:10px 0 24px}
.ov-btn{display:inline-block;padding:14px 36px;background:var(--accent);color:#000;border:none;border-radius:8px;font-size:15px;font-weight:700;cursor:pointer;transition:all .2s;font-family:inherit;letter-spacing:.2px}
.ov-btn:hover{background:#79bbff;transform:translateY(-1px)}
/* PDF mockup */
.pdf-mock{width:120px;height:160px;margin:0 auto 24px;background:var(--panel2);border:1px solid var(--border);border-radius:6px;padding:14px 12px;position:relative;overflow:hidden}
.pdf-mock::before{content:'PDF';position:absolute;top:5px;right:7px;font-size:7px;font-weight:700;color:var(--red);letter-spacing:.5px;background:rgba(248,81,73,.1);padding:1px 5px;border-radius:3px}
.pdf-ln{height:3px;background:rgba(201,209,217,.06);border-radius:2px;margin-bottom:4px}
.pdf-ln:nth-child(2){width:85%}.pdf-ln:nth-child(3){width:92%}.pdf-ln:nth-child(4){width:78%}
.pdf-ln:nth-child(5){width:88%}.pdf-ln:nth-child(6){width:70%}.pdf-ln:nth-child(7){width:95%}
.pdf-ln:nth-child(8){width:80%}.pdf-ln:nth-child(9){width:65%}.pdf-ln:nth-child(10){width:90%}
.pdf-ln:nth-child(11){width:76%}.pdf-ln:nth-child(12){width:82%}.pdf-ln:nth-child(13){width:60%}

/* ─── PIPELINE OVERLAY ─── */
.pipeline-section{margin:32px auto;max-width:720px}
.pipeline-section h3{font-size:12px;text-transform:uppercase;letter-spacing:1.5px;color:var(--text2);margin-bottom:18px;text-align:center;font-weight:600}
.pipeline{display:flex;align-items:center;justify-content:center;gap:0;flex-wrap:wrap}
.stage{display:flex;flex-direction:column;align-items:center;padding:12px 14px;border-radius:10px;background:var(--panel2);border:1px solid var(--border);min-width:105px;opacity:0;transform:translateY(12px);transition:all .4s}
.stage.visible{opacity:1;transform:translateY(0)}
.stage:hover{border-color:var(--accent);transform:translateY(-2px)}
.stage-num{font-size:9px;color:var(--accent);font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px}
.stage-icon{font-size:20px;margin-bottom:3px}
.stage-title{font-size:11px;font-weight:600;color:#fff;text-align:center;line-height:1.3}
.stage-desc{font-size:9px;color:var(--text2);text-align:center;margin-top:3px;line-height:1.3}
.pipe-arrow{color:var(--accent);font-size:14px;margin:0 5px;flex-shrink:0;opacity:0;transition:opacity .3s}
.pipe-arrow.visible{opacity:1}

/* ─── TOOLTIP ─── */
#graph-tooltip{position:absolute;top:14px;left:50%;transform:translateX(-50%);background:rgba(20,27,45,.95);border:1px solid var(--border);border-radius:8px;padding:10px 18px;z-index:15;font-size:11px;color:var(--text2);text-align:center;opacity:0;transition:opacity .4s;pointer-events:none;max-width:520px}
#graph-tooltip.visible{opacity:1}

.nav-hint{position:fixed;bottom:16px;right:16px;z-index:9999;font-size:10px;color:var(--text2);opacity:.5;padding:5px 10px;background:rgba(20,27,45,.8);border:1px solid var(--border);border-radius:6px}
</style>
</head>
<body>

<div id="progress-bar">
  <div class="seg" data-beat="1"></div>
  <div class="seg" data-beat="2"></div>
  <div class="seg" data-beat="3"></div>
</div>

<!-- BEAT 1: PROBLEM -->
<div id="overlay-problem" class="overlay visible">
  <div class="ov-card">
    <div class="pdf-mock">
      <div class="pdf-ln"></div><div class="pdf-ln"></div><div class="pdf-ln"></div>
      <div class="pdf-ln"></div><div class="pdf-ln"></div><div class="pdf-ln"></div>
      <div class="pdf-ln"></div><div class="pdf-ln"></div><div class="pdf-ln"></div>
      <div class="pdf-ln"></div><div class="pdf-ln"></div><div class="pdf-ln"></div>
      <div class="pdf-ln"></div>
    </div>
    <h2>Complex service obligations.<br><span class="hl">Buried in documents.</span></h2>
    <p>Duty of care policies define severity tiers, escalation chains, authorization gates, and service activation rules across dozens of interlocking clauses. TMC agents navigate this under time pressure &mdash; when every minute counts.</p>
    <div class="ov-callout">PNRs are touched 50+ times per trip. When disruptions hit, agents make cascading compliance decisions from documents like this.</div>
    <p style="font-size:13px">What if every obligation was a traversable graph an AI agent could reason over?</p>
    <br>
    <button class="ov-btn" onclick="goToBeat(2)">See the Pipeline</button>
  </div>
</div>

<!-- BEAT 2: PIPELINE -->
<div id="overlay-pipeline" class="overlay">
  <div class="ov-card">
    <h2>From PDF to <span class="hl">Knowledge Graph</span></h2>
    <p>A six-stage AI pipeline extracts structured entities, typed relationships, and operational rules &mdash; fully automated.</p>
    <div class="pipeline-section">
      <h3>Six-Stage Extraction Pipeline</h3>
      <div class="pipeline" id="pipeline-stages">
        <div class="stage" data-delay="0">
          <div class="stage-num">Stage 0</div>
          <div class="stage-icon">&#128196;</div>
          <div class="stage-title">First Pass</div>
          <div class="stage-desc">Document-level analysis &amp; section inventory</div>
        </div>
        <div class="pipe-arrow" data-delay="300">&rarr;</div>
        <div class="stage" data-delay="400">
          <div class="stage-num">Stage 1</div>
          <div class="stage-icon">&#9988;</div>
          <div class="stage-title">Semantic Splitting</div>
          <div class="stage-desc">Deterministic section boundary detection</div>
        </div>
        <div class="pipe-arrow" data-delay="700">&rarr;</div>
        <div class="stage" data-delay="800">
          <div class="stage-num">Stage 2</div>
          <div class="stage-icon">&#128269;</div>
          <div class="stage-title">Extraction</div>
          <div class="stage-desc">Per-section entity &amp; relationship identification</div>
        </div>
        <div class="pipe-arrow" data-delay="1100">&rarr;</div>
        <div class="stage" data-delay="1200">
          <div class="stage-num">Stage 3</div>
          <div class="stage-icon">&#128279;</div>
          <div class="stage-title">Semantic Merge</div>
          <div class="stage-desc">Cross-section entity deduplication &amp; resolution</div>
        </div>
        <div class="pipe-arrow" data-delay="1500">&rarr;</div>
        <div class="stage" data-delay="1600">
          <div class="stage-num">Stage 4</div>
          <div class="stage-icon">&#127760;</div>
          <div class="stage-title">Global Relations</div>
          <div class="stage-desc">Document-wide relationship inference</div>
        </div>
        <div class="pipe-arrow" data-delay="1900">&rarr;</div>
        <div class="stage" data-delay="2000">
          <div class="stage-num">Final</div>
          <div class="stage-icon">&#129504;</div>
          <div class="stage-title">Ontology Graph</div>
          <div class="stage-desc">Structured graph ready for agent traversal</div>
        </div>
      </div>
    </div>
    <button class="ov-btn" onclick="goToBeat(3)">Explore the Graph</button>
  </div>
</div>

<header>
  <h1>Duty of Care <span>Knowledge Graph</span></h1>
  <div class="tag">Live Extraction</div>
  <div class="stats">
    <span><b id="hdr-e">101</b> entities</span>
    <span><b id="hdr-r">148</b> relationships</span>
    <span><b id="hdr-t">15</b> types</span>
  </div>
</header>

<main>
  <div id="graph-wrap">
    <div id="graph-container"></div>
    <div class="zoom-controls">
      <button class="zoom-btn" onclick="zoomIn()" title="Zoom in">+</button>
      <button class="zoom-btn" onclick="zoomOut()" title="Zoom out">&minus;</button>
      <div class="zoom-div"></div>
      <button class="zoom-btn" onclick="zoomFit()" title="Fit to screen">&#x2302;</button>
    </div>
    <div id="entity-card">
      <button class="ec-close" onclick="hideEntityCard()">&times;</button>
      <div id="ec-content"></div>
    </div>
    <div id="legend"></div>
    <div id="graph-tooltip">101 entities from the real policy. Node size = graph importance. Click any node to inspect.</div>
  </div>

  <div id="right-panel">
    <!-- State 1: Scenario selector -->
    <div id="panel-scenarios">
      <h2>Scenario Simulator</h2>
      <div class="scenario-empty">Select a scenario to watch the AI agent traverse the knowledge graph in real-time, building a complete response plan from structured policy data.</div>
      <div id="scenario-buttons"></div>
    </div>
    <!-- State 2: Active scenario -->
    <div id="panel-active">
      <h2 id="active-scenario-name"></h2>
      <div id="step-progress"></div>
      <div id="step-counter"></div>
      <div id="step-title"></div>
      <div id="step-desc"></div>
      <div id="manual-annotation">
        <div class="m-label">Manual Process Comparison</div>
        <div class="m-text" id="manual-text"></div>
      </div>
      <div id="agent-log-wrap">
        <div id="agent-log-label">Agent Reasoning Trace</div>
        <div id="agent-log"></div>
      </div>
      <div id="controls">
        <button id="btn-prev" disabled>&#9664; Prev</button>
        <button id="btn-next" disabled>Next &#9654;</button>
        <button id="btn-auto" disabled>Auto &#9654;&#9654;</button>
      </div>
    </div>
    <!-- State 3: Results -->
    <div id="panel-results">
      <h2>Incident Response Plan</h2>
      <div id="results-content"></div>
      <div class="results-actions">
        <button class="btn-another" onclick="showScenarioSelector()">Choose Another</button>
        <button class="btn-restart" onclick="restartCurrentScenario()">Replay Scenario</button>
      </div>
    </div>
  </div>
</main>

<div class="nav-hint">&#8592; &#8594; Arrow keys to navigate</div>

<script>
// ======================================================================
//  GRAPH DATA
// ======================================================================
''' + entities_js + '\n' + rels_js + r'''

// ======================================================================
//  TYPE CONFIG
// ======================================================================
const TYPE_SHAPES = {
  Agreement:'hexagon',Obligation:'hexagon',Regulation:'hexagon',
  Organization:'triangle',ContactRole:'triangle',Traveler:'triangle',
  Service:'square',Platform:'square',BookingChannel:'square',Booking:'square',
  Incident:'star',SeverityLevel:'diamond',RiskCategory:'diamond',
  Alert:'triangleDown',TravelerResponseStatus:'triangleDown',DataElement:'dot',
};
const TYPE_LABELS = {
  Agreement:'Agreement',Obligation:'Obligation',Regulation:'Regulation',
  Organization:'Organization',ContactRole:'Contact Role',Traveler:'Traveler',
  Service:'Service',Platform:'Platform',BookingChannel:'Booking Channel',Booking:'Booking',
  Incident:'Incident',SeverityLevel:'Severity Level',RiskCategory:'Risk Category',
  Alert:'Alert',TravelerResponseStatus:'Response Status',DataElement:'Data Element',
};

// ======================================================================
//  VIS-NETWORK SETUP
// ======================================================================
const impMap = {};
GRAPH_ENTITIES.forEach(n => { impMap[n.id] = n.importance || 0; });

function buildVisNode(n) {
  const imp = n.importance || 0;
  return {
    id: n.id, label: n.name, title: n.name + ' [' + n.type + ']',
    shape: TYPE_SHAPES[n.type] || 'dot',
    color: { background: n.color, border: n.color,
      highlight: { background: n.color, border: '#f59e0b' },
      hover: { background: n.color, border: '#818cf8' } },
    size: 10 + imp * 30,
    font: { color: '#e8e6e3', size: 10 + imp * 8,
      face: "'DM Sans', system-ui, sans-serif",
      strokeWidth: 3, strokeColor: '#0b0f1a', vadjust: -2 },
    scaling: { label: { enabled: true, min: 10, max: 16, drawThreshold: 8 } },
    borderWidth: 1.5 + imp * 2, borderWidthSelected: 3,
    opacity: 0.4 + imp * 0.6,
    shadow: { enabled: true, color: n.color + (imp > 0.6 ? '60' : '20'), size: 6 + imp * 20, x: 0, y: 0 },
    _type: n.type, _importance: imp,
  };
}

function buildVisEdge(r) {
  const avgImp = ((impMap[r.src] || 0) + (impMap[r.tgt] || 0)) / 2;
  return {
    id: r.id, from: r.src, to: r.tgt, label: r.type,
    arrows: { to: { enabled: true, scaleFactor: 0.7 } },
    color: { color: '#3a3a5c', highlight: '#f59e0b', hover: '#555580' },
    font: { size: 10, color: '#6a6a8a', face: "'DM Sans', system-ui, sans-serif",
      align: 'middle', strokeWidth: 2, strokeColor: '#0b0f1a', background: '#0b0f1a' },
    smooth: { enabled: true, type: 'curvedCW', roundness: 0.15 },
    width: 0.8 + avgImp * 2.5, hoverWidth: 0.5,
  };
}

const visNodes = new vis.DataSet(GRAPH_ENTITIES.map(buildVisNode));
const visEdges = new vis.DataSet(GRAPH_RELATIONSHIPS.map(buildVisEdge));

const network = new vis.Network(
  document.getElementById('graph-container'),
  { nodes: visNodes, edges: visEdges },
  {
    physics: { solver: 'forceAtlas2Based',
      forceAtlas2Based: { gravitationalConstant: -80, centralGravity: 0.01,
        springLength: 160, springConstant: 0.08, damping: 0.4, avoidOverlap: 0.8 },
      stabilization: { iterations: 300, updateInterval: 25 },
      maxVelocity: 50, minVelocity: 0.75 },
    interaction: { hover: true, tooltipDelay: 200, navigationButtons: false,
      keyboard: { enabled: false }, zoomView: true, dragView: true },
    layout: { hierarchical: false },
  }
);
network.on('stabilizationIterationsDone', () => {
  network.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
});

// ======================================================================
//  ZOOM
// ======================================================================
function zoomIn() { network.moveTo({ scale: network.getScale() * 1.4, animation: { duration: 200, easingFunction: 'easeInOutQuad' } }); }
function zoomOut() { network.moveTo({ scale: network.getScale() / 1.4, animation: { duration: 200, easingFunction: 'easeInOutQuad' } }); }
function zoomFit() { network.fit({ animation: { duration: 400, easingFunction: 'easeInOutQuad' } }); }

// ======================================================================
//  LEGEND + STATS
// ======================================================================
(function(){
  const el = document.getElementById('legend');
  const seen = new Set();
  GRAPH_ENTITIES.forEach(e => { if (seen.has(e.type)) return; seen.add(e.type);
    el.innerHTML += '<div class="item"><div class="dot" style="background:'+e.color+'"></div>'+(TYPE_LABELS[e.type]||e.type)+'</div>'; });
  document.getElementById('hdr-e').textContent = GRAPH_ENTITIES.length;
  document.getElementById('hdr-r').textContent = GRAPH_RELATIONSHIPS.length;
  document.getElementById('hdr-t').textContent = seen.size;
})();

// ======================================================================
//  ENTITY CARD
// ======================================================================
const entityCard = document.getElementById('entity-card');
const ecContent = document.getElementById('ec-content');

function showEntityCard(nodeId) {
  const n = GRAPH_ENTITIES.find(x => x.id === nodeId);
  if (!n) return;
  let rows = '';
  if (n.attrs && Object.keys(n.attrs).length > 0)
    Object.entries(n.attrs).forEach(([k,v]) => {
      const d = typeof v === 'boolean' ? (v ? '\u2705 true' : '\u274C false') : Array.isArray(v) ? v.join(', ') : String(v);
      rows += '<tr><td>'+k.replace(/_/g,' ')+'</td><td>'+d+'</td></tr>'; });
  ecContent.innerHTML =
    '<div class="ec-name">'+n.name+'</div>' +
    '<div class="ec-type"><span class="ec-dot" style="background:'+n.color+'"></span>'+n.type+'</div>' +
    (n.desc ? '<div class="ec-desc">'+n.desc+'</div>' : '') +
    (rows ? '<table>'+rows+'</table>' : '');
  entityCard.classList.add('visible');
}
function hideEntityCard() { entityCard.classList.remove('visible'); }

network.on('click', p => { if (p.nodes.length > 0) showEntityCard(p.nodes[0]); else hideEntityCard(); });
network.on('doubleClick', p => { if (p.nodes.length === 0) zoomFit(); });

// ======================================================================
//  GRAPH VISIBILITY CONTROL (progressive reveal)
// ======================================================================
let revealedNodes = new Set();
let revealedEdges = new Set();
let scenarioMode = false;

function hideAllGraph() {
  scenarioMode = true;
  revealedNodes = new Set();
  revealedEdges = new Set();
  visNodes.update(GRAPH_ENTITIES.map(n => ({ id: n.id, opacity: 0, font: { color: 'transparent', strokeColor: 'transparent' } })));
  visEdges.update(GRAPH_RELATIONSHIPS.map(r => ({ id: r.id, color: { color: 'transparent' }, font: { color: 'transparent' }, width: 0, arrows: { to: { enabled: false } } })));
}

function revealItems(nodeIds, edgeIds) {
  (nodeIds || []).forEach(nid => {
    if (revealedNodes.has(nid)) return;
    revealedNodes.add(nid);
    const n = GRAPH_ENTITIES.find(x => x.id === nid);
    if (!n) return;
    const imp = n.importance || 0;
    visNodes.update({ id: nid, opacity: 1,
      borderWidth: 3, borderWidthSelected: 4,
      color: { background: n.color, border: '#58a6ff',
        highlight: { background: n.color, border: '#f59e0b' },
        hover: { background: n.color, border: '#818cf8' } },
      font: { color: '#e8e6e3', size: 10 + imp * 8,
        face: "'DM Sans', system-ui, sans-serif",
        strokeWidth: 3, strokeColor: '#0b0f1a', vadjust: -2 },
      shadow: { enabled: true, color: '#58a6ff40', size: 16, x: 0, y: 0 },
    });
  });
  (edgeIds || []).forEach(eid => {
    if (revealedEdges.has(eid)) return;
    revealedEdges.add(eid);
    visEdges.update({ id: eid,
      color: { color: '#58a6ff', highlight: '#f59e0b', hover: '#58a6ff' },
      font: { size: 9, color: '#8bb8e8', face: "'DM Sans', system-ui, sans-serif",
        align: 'middle', strokeWidth: 2, strokeColor: '#0b0f1a', background: '#0b0f1a' },
      width: 2.5, arrows: { to: { enabled: true, scaleFactor: 0.7 } },
    });
  });
  // Fit to revealed nodes
  if (revealedNodes.size > 0) {
    network.fit({ nodes: [...revealedNodes], animation: { duration: 400, easingFunction: 'easeInOutQuad' } });
  }
}

function restoreFullGraph() {
  scenarioMode = false;
  visNodes.update(GRAPH_ENTITIES.map(buildVisNode));
  visEdges.update(GRAPH_RELATIONSHIPS.map(buildVisEdge));
  network.fit({ animation: { duration: 400, easingFunction: 'easeInOutQuad' } });
}

// ======================================================================
//  SCENARIOS
// ======================================================================
const scenarios = [
{
  id: 'full_response',
  name: '\u26A1 Level 3 Earthquake \u2014 Full Response',
  desc: '9-step response chain: severity classification, service activation, welfare check, escalation',
  severity: 'high', sevLabel: 'Level 3 \u2014 Action Required',
  incidentLabel: 'Earthquake \u2014 Tokyo',
  actions: [
    { name: 'Welfare Check Outreach', time: '< 60 min (SLO)', who: 'Direct Travel' },
    { name: 'Live Voice Contact', time: '< 15 min after response', who: 'Direct Travel' },
    { name: 'Incident Response Activation', time: 'Immediate', who: 'Direct Travel' },
    { name: 'Client Escalation Notification', time: '< 60 min', who: 'Primary Program Owner' },
    { name: 'HR Welfare Notification', time: '< 60 min', who: 'HR Duty Contact' },
    { name: 'Extraordinary Measures Authorization', time: 'As needed', who: 'Client' },
    { name: 'Status Updates', time: 'Every 2 hours', who: 'Direct Travel' },
  ],
  steps: [
    { title: 'Incident Detected',
      desc: 'Risk Intelligence Platform detects a magnitude 6.1 earthquake near Tokyo.',
      nodes: ['incident','risk_intelligence_platform'], edges: [],
      log: [
        { cls:'qry', text:'QUERY  get_entity("incident")' },
        { cls:'atr', text:'READ   type=Incident' },
        { cls:'trv', text:'TRAVERSE  incident \u2190 risk_intelligence_platform' },
      ]},
    { title: 'Severity Classification',
      desc: 'Agent traverses CLASSIFIED_AS edge to severity framework.',
      nodes: ['severity_level'], edges: ['r19'],
      focus: 'severity_level',
      manual: 'Agent opens PDF, searches for severity table, reads timing columns, cross-references crisis bridge section. 3\u20135 min.',
      log: [
        { cls:'trv', text:'TRAVERSE  incident \u2500\u2500CLASSIFIED_AS\u2500\u2500\u25B6 severity_level' },
        { cls:'dec', text:'DECISION  Level 3: outreach within 60 min' },
        { cls:'dec', text:'DECISION  Crisis Bridge NOT required (Level 4 only)' },
      ]},
    { title: 'Identify Impacted Travelers',
      desc: 'Agent follows IMPACTS edge to find travelers in the impact zone.',
      nodes: ['traveler','pnr'], edges: ['r6'],
      focus: 'traveler',
      log: [
        { cls:'trv', text:'TRAVERSE  incident \u2500\u2500IMPACTS\u2500\u2500\u25B6 traveler' },
        { cls:'trv', text:'TRAVERSE  traveler \u2500\u2500HAS_BOOKING\u2500\u2500\u25B6 pnr' },
        { cls:'dec', text:'RESULT  1 traveler in impact zone' },
      ]},
    { title: 'Determine Activated Services',
      desc: 'Agent queries services with ACTIVATED_AT edges to severity level.',
      nodes: ['incident_response_and_traveler_assistance','welfare_checks_service','crisis_bridge'], edges: ['r10','r132','r8'],
      manual: 'Agent scans service descriptions, mentally maps which apply. Risk of missing authorization gates.',
      log: [
        { cls:'trv', text:'TRAVERSE  * \u2500\u2500ACTIVATED_AT\u2500\u2500\u25B6 severity_level' },
        { cls:'atr', text:'FOUND  Incident Response \u2713  Welfare Checks \u2713  Crisis Bridge (L4)' },
        { cls:'dec', text:'DECISION  Incident Response needs Client auth for extraordinary measures' },
      ]},
    { title: 'Verify Booking Visibility',
      desc: 'Approved Channels provide ENABLES_COVERAGE paths to services.',
      nodes: ['approved_channels','alerts_service','disruption_assistance_service','itinerary_visibility_and_traveler_locate'], edges: ['r124','r123','r125','r27'],
      manual: 'Agent checks booking system, may not think to verify channel coverage.',
      log: [
        { cls:'trv', text:'TRAVERSE  approved_channels \u2500\u2500ENABLES_COVERAGE\u2500\u2500\u25B6 [7 services]' },
        { cls:'dec', text:'RESULT  Approved Channel \u2014 full coverage confirmed \u2713' },
      ]},
    { title: 'Initiate Welfare Check',
      desc: 'Welfare check service activated. Agent reads required data elements.',
      nodes: ['full_legal_name_data_element','mobile_phone_number_data_element','email_address_data_element'], edges: ['r132'],
      log: [
        { cls:'qry', text:'ACTION  Initiate welfare check outreach' },
        { cls:'atr', text:'REQUIRED  Full Legal Name, Mobile Phone, Email' },
        { cls:'dec', text:'SENT   SMS at T+8 min (SLO: 60 min \u2713)' },
      ]},
    { title: 'Traveler Responds: NEED ASSISTANCE',
      desc: 'Agent reads TMC action from response status entity.',
      nodes: ['need_assistance'], edges: ['r42'],
      focus: 'need_assistance',
      log: [
        { cls:'trv', text:'TRAVERSE  traveler \u2500\u2500RESPONDS_WITH\u2500\u2500\u25B6 NEED_ASSISTANCE' },
        { cls:'dec', text:'DECISION  Live voice contact within 15 min' },
      ]},
    { title: 'Trigger Incident Response',
      desc: 'NEED ASSISTANCE triggers incident response. Authorization chain to Client.',
      nodes: ['client'], edges: ['r45','r40'],
      focus: 'incident_response_and_traveler_assistance',
      log: [
        { cls:'trv', text:'TRAVERSE  NEED_ASSISTANCE \u2500\u2500TRIGGERS_ACTION\u2500\u2500\u25B6 incident_response' },
        { cls:'trv', text:'TRAVERSE  incident_response \u2500\u2500REQUIRES_AUTH\u2500\u2500\u25B6 client' },
        { cls:'dec', text:'DECISION  Standard rebooking: proceed. Extraordinary: request Client auth.' },
      ]},
    { title: 'Escalate to Client Contacts',
      desc: 'Agent follows ESCALATED_TO edges to determine who to notify.',
      nodes: ['primary_travel_program_owner','corporate_security','human_resources_duty_contact','senior_leadership_contact'], edges: ['r66','r67','r68','r69'],
      manual: 'Agent pulls up contact roster, reads role descriptions. Under pressure, may over- or under-notify.',
      log: [
        { cls:'trv', text:'TRAVERSE  severity_level \u2500\u2500ESCALATED_TO\u2500\u2500\u25B6 [6 contacts]' },
        { cls:'dec', text:'NOTIFY  Primary Program Owner (mandatory)' },
        { cls:'dec', text:'NOTIFY  HR Duty Contact (welfare concern)' },
        { cls:'dec', text:'SKIP   Corporate Security (not security-related)' },
      ]},
  ]
},
{
  id: 'non_responsive',
  name: '\uD83D\uDD07 Non-Responsive Traveler \u2014 Escalation',
  desc: '5-step escalation: threshold check, authorization chain, specialist engagement',
  severity: 'high', sevLabel: 'Level 3 \u2014 Escalation Required',
  incidentLabel: 'Non-Responsive Traveler',
  actions: [
    { name: 'Outreach Threshold Check', time: '90 min window', who: 'Direct Travel' },
    { name: 'Client Escalation', time: 'Immediate after threshold', who: 'Primary Program Owner' },
    { name: 'HR Notification', time: '< 30 min', who: 'HR Duty Contact' },
    { name: 'Specialist Provider Engagement', time: 'Upon Client auth', who: 'Specialist Provider' },
    { name: 'Status Updates', time: 'Every 2 hours', who: 'Direct Travel' },
  ],
  steps: [
    { title: 'Welfare Check \u2014 No Response',
      desc: 'Traveler has not responded after outreach attempts.',
      nodes: ['traveler','no_response'], edges: ['r44'],
      focus: 'no_response',
      manual: 'Agent must remember the 3-attempt / 2-channel / 90-min threshold from training.',
      log: [
        { cls:'trv', text:'TRAVERSE  traveler \u2500\u2500RESPONDS_WITH\u2500\u2500\u25B6 NO_RESPONSE' },
        { cls:'atr', text:'READ   Escalate after 3 attempts / 2 channels / 90 min' },
        { cls:'dec', text:'CHECK  Threshold met? YES' },
      ]},
    { title: 'Escalation Triggered',
      desc: 'NO RESPONSE triggers incident response. Authorization chain to Client.',
      nodes: ['incident_response_and_traveler_assistance','client'], edges: ['r46','r40'],
      log: [
        { cls:'trv', text:'TRAVERSE  NO_RESPONSE \u2500\u2500TRIGGERS_ACTION\u2500\u2500\u25B6 incident_response' },
        { cls:'trv', text:'TRAVERSE  incident_response \u2500\u2500REQUIRES_AUTH\u2500\u2500\u25B6 client' },
        { cls:'dec', text:'DECISION  Escalate to Client for locate authorization' },
      ]},
    { title: 'Identify Escalation Contacts',
      desc: 'Agent queries contact roles via ESCALATED_TO edges.',
      nodes: ['severity_level','primary_travel_program_owner','human_resources_duty_contact','corporate_security'], edges: ['r66','r67','r69'],
      log: [
        { cls:'trv', text:'TRAVERSE  severity_level \u2500\u2500ESCALATED_TO\u2500\u2500\u25B6 [contacts]' },
        { cls:'dec', text:'NOTIFY  Primary + HR (welfare concern)' },
        { cls:'dec', text:'SKIP   Corporate Security (not security-related)' },
      ]},
    { title: 'Engage Specialist Provider',
      desc: 'Client authorizes on-ground locate.',
      nodes: ['specialist_provider','direct_travel_inc'], edges: ['r28'],
      log: [
        { cls:'qry', text:'REQUEST  Client authorization for on-ground locate' },
        { cls:'trv', text:'TRAVERSE  direct_travel \u2500\u2500ENGAGES\u2500\u2500\u25B6 specialist_provider' },
        { cls:'dec', text:'AUTHORIZED  Specialist Provider engaged' },
      ]},
  ]
},
{
  id: 'offchannel',
  name: '\u26A0\uFE0F Off-Channel Booking \u2014 Coverage Gap',
  desc: '5-step gap analysis: booking check, coverage failure, structural risk identification',
  severity: 'critical', sevLabel: 'Level 4 \u2014 Critical Gap',
  incidentLabel: 'Off-Channel Coverage Failure',
  actions: [
    { name: 'Crisis Bridge Activation', time: '< 30 min', who: 'Direct Travel' },
    { name: 'Coverage Gap Flagged', time: 'Immediate', who: 'Agent' },
    { name: 'Client Incident Report', time: '< 4 hours', who: 'Direct Travel' },
    { name: 'Itinerary Capture Recommendation', time: 'In report', who: 'Direct Travel' },
    { name: 'Quarterly Business Review Item', time: 'Next QBR', who: 'Client + Direct Travel' },
  ],
  steps: [
    { title: 'Level 4 Crisis \u2014 Terrorist Attack',
      desc: 'Critical incident. Agent identifies crisis bridge requirement.',
      nodes: ['incident','severity_level','crisis_bridge'], edges: ['r19','r8'],
      log: [
        { cls:'qry', text:'ALERT  Level 4 Crisis \u2014 London' },
        { cls:'trv', text:'TRAVERSE  incident \u2500\u2500CLASSIFIED_AS\u2500\u2500\u25B6 severity_level' },
        { cls:'dec', text:'DECISION  Crisis Bridge + Immediate outreach' },
      ]},
    { title: 'Check Traveler Booking Channel',
      desc: 'Traveler booked off-channel. Checks for ENABLES_COVERAGE paths.',
      nodes: ['off_channel_booking','traveler'], edges: [],
      log: [
        { cls:'trv', text:'TRAVERSE  traveler \u2500\u2500HAS_BOOKING\u2500\u2500\u25B6 off_channel_booking' },
        { cls:'wrn', text:'RESULT  \u26A0 NO ENABLES_COVERAGE edges from Off-Channel' },
      ]},
    { title: 'Coverage Gap Identified',
      desc: 'No coverage path. Services requiring booking visibility are blocked.',
      nodes: ['welfare_checks_service','alerts_service','disruption_assistance_service','itinerary_visibility_and_traveler_locate'], edges: [],
      manual: 'This gap is invisible in manual processes. Agents assume all travelers are covered.',
      log: [
        { cls:'wrn', text:'GAP  Welfare Checks \u2192 BLOCKED' },
        { cls:'wrn', text:'GAP  Alerts \u2192 BLOCKED' },
        { cls:'wrn', text:'GAP  Disruption Assistance \u2192 BLOCKED' },
        { cls:'dec', text:'ACTION  Flag gap to Client' },
      ]},
    { title: 'Contrast: Approved Channel',
      desc: 'Approved Channel has 7 ENABLES_COVERAGE paths \u2014 full access.',
      nodes: ['approved_channels','in_trip_monitoring_and_alerts','incident_response_and_traveler_assistance','duty_of_care_services'], edges: ['r4','r27','r121','r122','r123','r124','r125'],
      log: [
        { cls:'trv', text:'TRAVERSE  approved_channels \u2500\u2500ENABLES_COVERAGE\u2500\u2500\u25B6 [7 services]' },
        { cls:'dec', text:'INSIGHT  Booking channel = single gate for coverage' },
        { cls:'dec', text:'INSIGHT  ~30% off-channel \u2192 material risk' },
      ]},
  ]
}
];

// ======================================================================
//  PRESENTATION STATE
// ======================================================================
let currentBeat = 1;
let currentScenario = null;
let currentStep = -1;
let autoTimer = null;

function goToBeat(beat) {
  currentBeat = beat;
  document.querySelectorAll('.overlay').forEach(o => o.classList.remove('visible'));
  document.querySelectorAll('#progress-bar .seg').forEach(s => {
    const b = parseInt(s.dataset.beat);
    s.classList.remove('active','done');
    if (b === beat) s.classList.add('active');
    else if (b < beat) s.classList.add('done');
  });
  if (beat === 1) document.getElementById('overlay-problem').classList.add('visible');
  else if (beat === 2) { document.getElementById('overlay-pipeline').classList.add('visible'); animPipeline(); }
  else if (beat === 3) {
    const tt = document.getElementById('graph-tooltip');
    tt.classList.add('visible');
    setTimeout(() => tt.classList.remove('visible'), 4000);
    if (scenarioMode) restoreFullGraph();
    showScenarioSelector();
  }
}

function animPipeline() {
  document.querySelectorAll('.stage, .pipe-arrow').forEach(el => el.classList.remove('visible'));
  document.querySelectorAll('.stage, .pipe-arrow').forEach(el => {
    const d = parseInt(el.dataset.delay) || 0;
    setTimeout(() => el.classList.add('visible'), d + 200);
  });
}

document.addEventListener('keydown', e => {
  if (e.key === 'ArrowRight') {
    e.preventDefault();
    if (currentBeat < 3) goToBeat(currentBeat + 1);
    else if (currentScenario && currentStep < currentScenario.steps.length - 1) {
      clearInterval(autoTimer); goStep(currentStep + 1);
    } else if (currentScenario && currentStep >= currentScenario.steps.length - 1) {
      showResults();
    }
  } else if (e.key === 'ArrowLeft') {
    e.preventDefault();
    if (currentBeat > 1 && !currentScenario) goToBeat(currentBeat - 1);
    else if (currentScenario && currentStep > 0) { clearInterval(autoTimer); goStep(currentStep - 1); }
  } else if (e.key === 'Escape') {
    if (currentScenario) { showScenarioSelector(); restoreFullGraph(); }
  }
});

// ======================================================================
//  PANEL STATE
// ======================================================================
function showScenarioSelector() {
  currentScenario = null; currentStep = -1;
  if (autoTimer) clearInterval(autoTimer);
  hideEntityCard();
  document.getElementById('panel-scenarios').style.display = 'flex';
  document.getElementById('panel-active').style.display = 'none';
  document.getElementById('panel-results').style.display = 'none';
  if (scenarioMode) restoreFullGraph();
}

function showActivePanel() {
  document.getElementById('panel-scenarios').style.display = 'none';
  document.getElementById('panel-active').style.display = 'flex';
  document.getElementById('panel-results').style.display = 'none';
}

function showResultsPanel() {
  document.getElementById('panel-scenarios').style.display = 'none';
  document.getElementById('panel-active').style.display = 'none';
  document.getElementById('panel-results').style.display = 'flex';
}

// ======================================================================
//  SCENARIO BUTTONS
// ======================================================================
(function(){
  const container = document.getElementById('scenario-buttons');
  scenarios.forEach(s => {
    const btn = document.createElement('button');
    btn.className = 'scenario-btn';
    btn.innerHTML = '<span class="sc-title">'+s.name+'</span><span class="sc-desc">'+s.desc+'</span>';
    btn.onclick = () => startScenario(s);
    container.appendChild(btn);
  });
})();

function startScenario(s) {
  currentScenario = s;
  currentStep = -1;
  document.getElementById('active-scenario-name').textContent = s.name;
  document.getElementById('agent-log').innerHTML = '';
  hideAllGraph();
  showActivePanel();
  goStep(0);
}

function restartCurrentScenario() {
  if (currentScenario) startScenario(currentScenario);
}

// ======================================================================
//  STEP ENGINE (progressive reveal)
// ======================================================================
const logEl = document.getElementById('agent-log');
const btnPrev = document.getElementById('btn-prev');
const btnNext = document.getElementById('btn-next');
const btnAuto = document.getElementById('btn-auto');

function buildDots(total, current) {
  const el = document.getElementById('step-progress');
  el.innerHTML = '';
  for (let i = 0; i < total; i++) {
    const d = document.createElement('div');
    d.className = 'dot' + (i === current ? ' active' : i < current ? ' done' : '');
    el.appendChild(d);
  }
}

function goStep(idx) {
  if (!currentScenario) return;
  const steps = currentScenario.steps;
  if (idx < 0 || idx >= steps.length) return;

  // If going backward, we need to rebuild from scratch
  if (idx < currentStep) {
    hideAllGraph();
    for (let i = 0; i <= idx; i++) {
      const s = steps[i];
      revealItems(s.nodes, s.edges);
    }
  }

  currentStep = idx;
  const step = steps[idx];

  document.getElementById('step-counter').textContent = 'Step ' + (idx+1) + ' of ' + steps.length;
  document.getElementById('step-title').textContent = step.title;
  document.getElementById('step-desc').textContent = step.desc;
  buildDots(steps.length, idx);

  const manualEl = document.getElementById('manual-annotation');
  if (step.manual) {
    document.getElementById('manual-text').textContent = step.manual;
    manualEl.style.display = 'block';
  } else manualEl.style.display = 'none';

  btnPrev.disabled = idx === 0;
  btnNext.disabled = false;
  btnNext.textContent = idx === steps.length - 1 ? 'See Results \u25B6' : 'Next \u25B6';
  btnAuto.disabled = false;

  // Progressive reveal
  revealItems(step.nodes, step.edges);

  if (step.focus) showEntityCard(step.focus);
  else hideEntityCard();

  if (step.log) {
    step.log.forEach((line, i) => {
      setTimeout(() => {
        const div = document.createElement('div');
        div.className = 'log-line ' + line.cls;
        div.textContent = line.text;
        logEl.appendChild(div);
        logEl.scrollTop = logEl.scrollHeight;
      }, i * 100);
    });
  }
}

btnPrev.addEventListener('click', () => { clearInterval(autoTimer); goStep(currentStep - 1); });
btnNext.addEventListener('click', () => {
  clearInterval(autoTimer);
  if (currentStep >= currentScenario.steps.length - 1) showResults();
  else goStep(currentStep + 1);
});
btnAuto.addEventListener('click', () => {
  if (autoTimer) { clearInterval(autoTimer); autoTimer = null; btnAuto.textContent = 'Auto \u25B6\u25B6'; return; }
  btnAuto.textContent = 'Pause \u23F8';
  autoTimer = setInterval(() => {
    if (!currentScenario || currentStep >= currentScenario.steps.length - 1) {
      clearInterval(autoTimer); autoTimer = null; btnAuto.textContent = 'Auto \u25B6\u25B6';
      if (currentScenario) showResults();
      return;
    }
    goStep(currentStep + 1);
  }, 3500);
});

// ======================================================================
//  RESULTS
// ======================================================================
function showResults() {
  if (autoTimer) clearInterval(autoTimer);
  showResultsPanel();

  const s = currentScenario;
  const sevClass = s.severity;
  let html = '<div class="plan-header">' +
    '<div class="plan-incident">'+s.incidentLabel+'</div>' +
    '<div class="plan-severity '+sevClass+'">'+s.sevLabel+'</div></div>';

  s.actions.forEach((a, i) => {
    html += '<div class="action-item" style="animation-delay:'+i*0.08+'s">' +
      '<div class="action-name">'+(i+1)+'. '+a.name+'</div>' +
      '<div class="action-meta">' +
        '<span class="action-time">\u23F1 '+a.time+'</span>' +
        '<span class="action-who">\uD83D\uDC64 '+a.who+'</span>' +
      '</div></div>';
  });

  html += '<div class="traversal-stats">' +
    '<div class="tstat"><strong>'+revealedNodes.size+'</strong> nodes traversed</div>' +
    '<div class="tstat"><strong>'+revealedEdges.size+'</strong> edges followed</div>' +
    '<div class="tstat"><strong>'+s.actions.length+'</strong> actions identified</div>' +
    '<div class="tstat"><strong>< 1ms</strong> traversal time</div></div>';

  document.getElementById('results-content').innerHTML = html;
}

// ======================================================================
//  INIT
// ======================================================================
goToBeat(1);
</script>
</body>
</html>
'''

with open('demo.html', 'w', encoding='utf-8') as f:
    f.write(html)

print(f'demo.html written: {len(html):,} chars')
print(f'  {len(g["entities"])} entities, {len(g["relationships"])} relationships')
