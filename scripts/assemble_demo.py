"""Assemble the complete demo_v2.html from CSS template + v2 data + scenarios + JS engine."""
import json
import re


def fix_mojibake(text: str) -> str:
    """Fix UTF-8 bytes that were decoded as Windows-1252/Latin-1."""
    # Match sequences of \u00c0-\u00ef followed by \u0080-\u00bf continuation bytes
    def _try_fix(m):
        try:
            return m.group().encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return m.group()
    # 3-byte sequences (e.g. em-dash \u00e2\u0080\u0094)
    text = re.sub(r"[\u00e0-\u00ef][\u0080-\u00bf]{1,2}", _try_fix, text)
    # 2-byte sequences (e.g. section sign \u00c2\u00a7)
    text = re.sub(r"[\u00c0-\u00df][\u0080-\u00bf]", _try_fix, text)
    return text


# Read generated data files
with open("data/v2/demo_data.js", encoding="utf-8") as f:
    data_js = fix_mojibake(f.read())

with open("data/v2/demo_scenarios.js", encoding="utf-8") as f:
    scenarios_js = fix_mojibake(f.read())

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
header h1{font-size:20px;font-weight:700;letter-spacing:.2px}
header h1 span{color:var(--accent)}
header .tag{font-size:8px;background:var(--accent);color:#000;padding:2px 8px;border-radius:10px;font-weight:700;letter-spacing:.5px;text-transform:uppercase}
header .stats{font-size:14px;color:var(--text2);display:flex;gap:14px;margin-left:auto}
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
#entity-card{position:absolute;top:14px;left:14px;z-index:20;width:340px;max-height:52%;background:rgba(20,27,45,.94);backdrop-filter:blur(8px);border:1px solid var(--border);border-radius:10px;padding:14px 16px;overflow-y:auto;opacity:0;transform:translateY(-8px);transition:opacity .3s,transform .3s;pointer-events:none;box-shadow:0 8px 32px rgba(0,0,0,.4)}
#entity-card.visible{opacity:1;transform:translateY(0);pointer-events:all}
#entity-card .ec-close{position:absolute;top:6px;right:8px;background:none;border:none;color:var(--text2);font-size:14px;cursor:pointer;padding:2px 6px;border-radius:4px;line-height:1}
#entity-card .ec-close:hover{color:var(--text);background:var(--panel2)}
#entity-card .ec-name{font-size:14px;font-weight:700;margin-bottom:2px;padding-right:24px}
#entity-card .ec-type{font-size:10px;color:var(--accent);margin-bottom:6px;display:flex;align-items:center;gap:6px}
#entity-card .ec-dot{width:7px;height:7px;border-radius:2px;flex-shrink:0}
#entity-card .ec-desc{font-size:10px;color:var(--text2);line-height:1.5;margin-bottom:8px}
#entity-card table{width:100%;font-size:10px;border-collapse:collapse}
#entity-card td{padding:3px 0;vertical-align:top}
#entity-card td:first-child{color:var(--text2);width:42%;padding-right:6px}
#entity-card td:last-child{color:var(--text);font-weight:500;word-break:break-word}
#entity-card tr{border-bottom:1px solid rgba(30,42,69,.6)}

/* ─── LEGEND ─── */
#legend{position:absolute;bottom:10px;left:10px;background:rgba(20,27,45,.92);border:1px solid var(--border);border-radius:8px;padding:8px 12px;display:flex;flex-wrap:wrap;gap:4px 12px;z-index:10;max-width:700px}
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
#panel-results{flex:1;display:none;flex-direction:column;padding:0;overflow:hidden}
#results-scroll{flex:1;overflow-y:auto;padding:20px 20px 10px}
#results-footer{flex-shrink:0;padding:10px 20px 20px;border-top:1px solid var(--border)}
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
.traversal-stats{margin-top:16px;padding-top:14px;border-top:1px solid var(--border);display:grid;grid-template-columns:1fr 1fr;gap:8px}
.tstat{text-align:center;font-size:12px;color:var(--text2);padding:10px;background:var(--panel2);border-radius:8px}
.tstat strong{color:var(--accent);display:block;font-size:18px;margin-bottom:2px}

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
.pdf-mock{width:120px;height:160px;margin:0 auto 24px;background:var(--panel2);border:1px solid var(--border);border-radius:6px;padding:14px 12px;position:relative;overflow:hidden}
.pdf-mock::before{content:'PDF';position:absolute;top:5px;right:7px;font-size:7px;font-weight:700;color:var(--red);letter-spacing:.5px;background:rgba(248,81,73,.1);padding:1px 5px;border-radius:3px}
.pdf-ln{height:3px;background:rgba(201,209,217,.06);border-radius:2px;margin-bottom:4px}
.pdf-ln:nth-child(2){width:85%}.pdf-ln:nth-child(3){width:92%}.pdf-ln:nth-child(4){width:78%}
.pdf-ln:nth-child(5){width:88%}.pdf-ln:nth-child(6){width:70%}.pdf-ln:nth-child(7){width:95%}
.pdf-ln:nth-child(8){width:80%}.pdf-ln:nth-child(9){width:65%}.pdf-ln:nth-child(10){width:90%}
.pdf-ln:nth-child(11){width:76%}.pdf-ln:nth-child(12){width:82%}.pdf-ln:nth-child(13){width:60%}

/* ─── PIPELINE OVERLAY ─── */
.pipeline-section{margin:36px auto;max-width:1100px}
.pipeline-section h3{font-size:14px;text-transform:uppercase;letter-spacing:1.5px;color:var(--text2);margin-bottom:22px;text-align:center;font-weight:600}
.pipeline{display:flex;align-items:center;justify-content:center;gap:0;flex-wrap:nowrap}
.stage{display:flex;flex-direction:column;align-items:center;padding:16px 14px;border-radius:12px;background:var(--panel2);border:1px solid var(--border);width:150px;flex-shrink:0;opacity:0;transform:translateY(12px);transition:all .4s}
.stage.visible{opacity:1;transform:translateY(0)}
.stage:hover{border-color:var(--accent);transform:translateY(-2px)}
.stage-num{font-size:10px;color:var(--accent);font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px}
.stage-icon{font-size:26px;margin-bottom:4px}
.stage-title{font-size:14px;font-weight:700;color:#fff;text-align:center;line-height:1.3}
.stage-desc{font-size:10px;color:var(--text2);text-align:center;margin-top:4px;line-height:1.4}
.pipe-arrow{color:var(--accent);font-size:16px;margin:0 5px;flex-shrink:0;opacity:0;transition:opacity .3s}
.pipe-arrow.visible{opacity:1}

/* ─── TOOLTIP ─── */
#graph-tooltip{position:absolute;top:14px;left:50%;transform:translateX(-50%);z-index:30;background:rgba(88,166,255,.12);border:1px solid rgba(88,166,255,.3);border-radius:10px;padding:12px 20px;color:var(--accent);font-size:13px;font-weight:600;pointer-events:none;opacity:0;transition:opacity .5s;text-align:center}
#graph-tooltip.visible{opacity:1}
</style>
</head>
<body>

<div id="progress-bar">
  <div class="seg" data-beat="1"></div>
  <div class="seg" data-beat="2"></div>
  <div class="seg" data-beat="3"></div>
  <div class="seg" data-beat="4"></div>
  <div class="seg" data-beat="5"></div>
</div>

<header>
  <h1><span>SHOGUN</span></h1>
  <div class="tag">Pipeline v2 Demo</div>
  <div class="stats">
    <span><b id="hdr-e">0</b> entities</span>
    <span><b id="hdr-r">0</b> relationships</span>
    <span><b id="hdr-t">0</b> types</span>
  </div>
</header>

<main>
  <div id="graph-wrap">
    <div id="graph-container"></div>
    <div class="zoom-controls">
      <button class="zoom-btn" onclick="zoomIn()" title="Zoom In">+</button>
      <div class="zoom-div"></div>
      <button class="zoom-btn" onclick="zoomOut()" title="Zoom Out">&minus;</button>
      <div class="zoom-div"></div>
      <button class="zoom-btn" onclick="zoomFit()" title="Fit">&#x25a3;</button>
    </div>
    <div id="entity-card">
      <button class="ec-close" onclick="hideEntityCard()">&times;</button>
      <div id="ec-content"></div>
    </div>
    <div id="legend"></div>
    <div id="graph-tooltip">Select a node to inspect &middot; Select a scenario to begin walkthrough &rarr;</div>
  </div>

  <div id="right-panel">
    <div id="panel-scenarios">
      <h2>Scenario Walkthroughs</h2>
      <div id="scenario-buttons"></div>
      <div class="scenario-empty" id="scenario-hint">Each scenario traces real edges in the knowledge graph built from a 44-page travel duty-of-care policy.<br><br>Select a scenario to watch the AI agent traverse the graph step by step.</div>
    </div>
    <div id="panel-active">
      <h2 id="active-scenario-name"></h2>
      <div id="step-counter"></div>
      <div id="step-progress"></div>
      <div id="step-title"></div>
      <div id="step-desc"></div>
      <div id="manual-annotation">
        <div class="m-label">&#x1f9d1;&#x200d;&#x1f4bc; Without Graph — Manual Process</div>
        <div class="m-text" id="manual-text"></div>
      </div>
      <div id="agent-log-wrap">
        <div id="agent-log-label">Agent Reasoning Trace</div>
        <div id="agent-log"></div>
      </div>
      <div id="controls">
        <button id="btn-prev" disabled>&laquo; Prev</button>
        <button id="btn-auto">Auto &#x25b6;&#x25b6;</button>
        <button id="btn-next">Next &#x25b6;</button>
      </div>
    </div>
    <div id="panel-results">
      <div id="results-scroll">
        <h2 style="font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:var(--text2);margin-bottom:14px;font-weight:600">Action Plan</h2>
        <div id="results-content"></div>
      </div>
      <div id="results-footer">
        <button onclick="showScenarioSelector();restoreFullGraph()" style="width:100%;background:var(--panel2);border:1px solid var(--border);color:var(--accent);padding:12px 24px;border-radius:8px;cursor:pointer;font-family:inherit;font-weight:600;font-size:13px">Back to Scenarios</button>
      </div>
    </div>
  </div>
</main>

<!-- BEAT 1: PROBLEM -->
<div id="overlay-problem" class="overlay">
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

<script>
// ======================================================================
//  GRAPH DATA (149 entities, 352 relationships from pipeline v2)
// ======================================================================
''' + data_js + '''

// ======================================================================
//  SCENARIOS
// ======================================================================
''' + scenarios_js + '''

// ======================================================================
//  TYPE CONFIG
// ======================================================================
const TYPE_SHAPES = {
  Agreement:'hexagon',Obligation:'hexagon',Regulation:'hexagon',
  Organization:'triangle',ContactRole:'triangle',Traveler:'triangle',
  Service:'square',Platform:'square',BookingChannel:'square',Booking:'square',
  Incident:'star',SeverityLevel:'diamond',RiskCategory:'diamond',
  Alert:'triangleDown',TravelerResponseStatus:'triangleDown',DataElement:'dot',
  Workflow:'box',
};
const TYPE_LABELS = {
  Agreement:'Agreement',Obligation:'Obligation',Regulation:'Regulation',
  Organization:'Organization',ContactRole:'Contact Role',Traveler:'Traveler',
  Service:'Service',Platform:'Platform',BookingChannel:'Booking Channel',Booking:'Booking',
  Incident:'Incident',SeverityLevel:'Severity Level',RiskCategory:'Risk Category',
  Alert:'Alert',TravelerResponseStatus:'Response Status',DataElement:'Data Element',
  Workflow:'Workflow',
};

// ======================================================================
//  VIS-NETWORK SETUP
// ======================================================================
const impMap = {};
GRAPH_ENTITIES.forEach(n => { impMap[n.id] = n.importance || 0; });

function buildVisNode(n) {
  const imp = n.importance || 0;
  return {
    id: n.id, label: n.name.replace(/_/g, ' '),
    title: n.name + ' [' + n.type + ']',
    shape: TYPE_SHAPES[n.type] || 'dot',
    widthConstraint: { maximum: 140 },
    color: { background: n.color, border: n.color,
      highlight: { background: n.color, border: '#f59e0b' },
      hover: { background: n.color, border: '#818cf8' } },
    size: 10 + imp * 30,
    font: { color: 'transparent', size: 1,
      face: "'DM Sans', system-ui, sans-serif",
      strokeWidth: 3, strokeColor: '#0b0f1a', vadjust: -2 },
    scaling: { label: { enabled: true, min: 10, max: 16, drawThreshold: 8 } },
    borderWidth: 1.5 + imp * 2, borderWidthSelected: 3,
    opacity: 0.4 + imp * 0.6,
    shadow: imp > 0.5 ? { enabled: true, color: n.color + '50', size: 6 + imp * 20, x: 0, y: 0 } : { enabled: false },
    _type: n.type, _importance: imp,
  };
}

function buildVisEdge(r) {
  const avgImp = ((impMap[r.src] || 0) + (impMap[r.tgt] || 0)) / 2;
  return {
    id: r.id, from: r.src, to: r.tgt, label: '',
    arrows: { to: { enabled: true, scaleFactor: 0.5 } },
    color: { color: 'rgba(58,58,92,0.12)', highlight: '#f59e0b', hover: 'rgba(58,58,92,0.25)' },
    font: { size: 0, color: 'transparent' },
    smooth: { enabled: true, type: 'curvedCW', roundness: 0.15 },
    width: 0.4, hoverWidth: 0.3,
    _origWidth: 0.8 + avgImp * 2.5,
  };
}

// Build lookup maps once (avoids O(n) .find() scans)
const edgeById = {};
GRAPH_RELATIONSHIPS.forEach(r => { edgeById[r.id] = r; });
const entityById = {};
GRAPH_ENTITIES.forEach(n => { entityById[n.id] = n; });
const nodeEdgeMap = {};
GRAPH_RELATIONSHIPS.forEach(r => {
  if (!nodeEdgeMap[r.src]) nodeEdgeMap[r.src] = [];
  if (!nodeEdgeMap[r.tgt]) nodeEdgeMap[r.tgt] = [];
  nodeEdgeMap[r.src].push(r.id);
  nodeEdgeMap[r.tgt].push(r.id);
});
let focusedNodeEdges = new Set();
let focusedNeighborIds = new Set();

function showEdgesForNode(nodeId) {
  // Reset previous edges to faint (single batch)
  if (focusedNodeEdges.size > 0 && !scenarioMode) {
    visEdges.update([...focusedNodeEdges].map(eid => ({
      id: eid, label: '', width: 0.4,
      color: { color: 'rgba(58,58,92,0.12)', highlight: '#f59e0b', hover: 'rgba(58,58,92,0.25)' },
      font: { size: 0, color: 'transparent' },
    })));
  }
  focusedNodeEdges = new Set();
  if (!nodeId || scenarioMode) { focusedNeighborIds = new Set(); return; }

  // Find neighbors
  const eids = nodeEdgeMap[nodeId] || [];
  focusedNodeEdges = new Set(eids);
  const newNeighbors = new Set([nodeId]);
  eids.forEach(eid => {
    const r = edgeById[eid];
    if (r) { newNeighbors.add(r.src); newNeighbors.add(r.tgt); }
  });

  // Batch all node updates into a single array
  const nodeUpdates = GRAPH_ENTITIES.map(n => {
    const imp = n.importance || 0;
    if (newNeighbors.has(n.id)) {
      return { id: n.id, font: { color: '#e8e6e3', size: 16 + imp * 6,
        face: "'DM Sans', system-ui, sans-serif", strokeWidth: 3, strokeColor: '#0b0f1a', vadjust: -2 },
        opacity: 1 };
    } else {
      return { id: n.id, font: { color: 'transparent', size: 1 }, opacity: 0.15 };
    }
  });
  visNodes.update(nodeUpdates);
  focusedNeighborIds = newNeighbors;

  // Highlight focused edges (single batch)
  visEdges.update(eids.map(eid => {
    const r = edgeById[eid];
    return {
      id: eid, label: r ? r.type : '',
      color: { color: '#58a6ff', highlight: '#f59e0b', hover: '#58a6ff' },
      width: 2.5,
      font: { size: 12, color: '#8bb8e8', face: "'DM Sans', system-ui, sans-serif",
        align: 'middle', strokeWidth: 2, strokeColor: '#0b0f1a', background: '#0b0f1a' },
    };
  }));
}

function hideAllFocusEdges() {
  if (focusedNodeEdges.size > 0) {
    visEdges.update([...focusedNodeEdges].map(eid => ({
      id: eid, label: '', width: 0.4,
      color: { color: 'rgba(58,58,92,0.12)', highlight: '#f59e0b', hover: 'rgba(58,58,92,0.25)' },
      font: { size: 0, color: 'transparent' },
    })));
    focusedNodeEdges = new Set();
  }
  // Restore all nodes to default (hidden labels) — single batch
  if (focusedNeighborIds.size > 0) {
    visNodes.update(GRAPH_ENTITIES.map(n => {
      const imp = n.importance || 0;
      return { id: n.id,
        font: { color: 'transparent', size: 1, face: "'DM Sans', system-ui, sans-serif",
          strokeWidth: 3, strokeColor: '#0b0f1a', vadjust: -2 },
        opacity: 0.4 + imp * 0.6 };
    }));
    focusedNeighborIds = new Set();
  }
}

const visNodes = new vis.DataSet(GRAPH_ENTITIES.map(buildVisNode));
const visEdges = new vis.DataSet(GRAPH_RELATIONSHIPS.map(buildVisEdge));

const network = new vis.Network(
  document.getElementById('graph-container'),
  { nodes: visNodes, edges: visEdges },
  {
    physics: { solver: 'forceAtlas2Based',
      forceAtlas2Based: { gravitationalConstant: -120, centralGravity: 0.005,
        springLength: 200, springConstant: 0.06, damping: 0.4, avoidOverlap: 0.8 },
      stabilization: { iterations: 300, updateInterval: 25 },
      maxVelocity: 50, minVelocity: 0.75 },
    interaction: { hover: true, tooltipDelay: 200, navigationButtons: false,
      keyboard: { enabled: false }, zoomView: true, dragView: true },
    layout: { hierarchical: false },
  }
);
network.on('stabilizationIterationsDone', () => {
  network.setOptions({ physics: { enabled: false } });

  // Pull orphan nodes (0 connections) into the main cluster bounds
  const connectedIds = new Set();
  GRAPH_RELATIONSHIPS.forEach(r => { connectedIds.add(r.src); connectedIds.add(r.tgt); });
  const positions = network.getPositions();
  const connectedPos = Object.entries(positions).filter(([id]) => connectedIds.has(id)).map(([,p]) => p);
  if (connectedPos.length > 0) {
    const cxs = connectedPos.map(p => p.x);
    const cys = connectedPos.map(p => p.y);
    const cx = (Math.min(...cxs) + Math.max(...cxs)) / 2;
    const cy = (Math.min(...cys) + Math.max(...cys)) / 2;
    const radius = Math.max(Math.max(...cxs) - Math.min(...cxs), Math.max(...cys) - Math.min(...cys)) / 2 * 0.8;
    GRAPH_ENTITIES.forEach(n => {
      if (!connectedIds.has(n.id)) {
        const angle = Math.random() * Math.PI * 2;
        const r = radius * (0.6 + Math.random() * 0.4);
        network.moveNode(n.id, cx + Math.cos(angle) * r, cy + Math.sin(angle) * r);
      }
    });
  }

  network.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
});

// ======================================================================
//  ZOOM
// ======================================================================
function zoomIn() { network.moveTo({ scale: network.getScale() * 1.3, animation: { duration: 200, easingFunction: 'easeInOutQuad' } }); }
function zoomOut() { network.moveTo({ scale: network.getScale() / 1.3, animation: { duration: 200, easingFunction: 'easeInOutQuad' } }); }
function zoomFit() {
  if (scenarioMode && revealedNodes.size > 0) {
    network.fit({ nodes: [...revealedNodes], animation: { duration: 400, easingFunction: 'easeInOutQuad' } });
  } else {
    network.fit({ animation: { duration: 400, easingFunction: 'easeInOutQuad' } });
  }
}

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
//  ENTITY CARD (with full attributes)
// ======================================================================
const entityCard = document.getElementById('entity-card');
const ecContent = document.getElementById('ec-content');

function showEntityCard(nodeId) {
  const n = entityById[nodeId];
  if (!n) return;
  let rows = '';
  if (n.attrs && Object.keys(n.attrs).length > 0)
    Object.entries(n.attrs).forEach(([k,v]) => {
      if (v === null || v === '' || (Array.isArray(v) && v.length === 0)) return;
      let d;
      if (typeof v === 'boolean') d = v ? '\u2705 true' : '\u274c false';
      else if (Array.isArray(v)) d = v.join(', ');
      else if (typeof v === 'number') d = String(v);
      else d = String(v).length > 200 ? String(v).substring(0, 200) + '\u2026' : String(v);
      rows += '<tr><td>'+k.replace(/_/g,' ')+'</td><td>'+d+'</td></tr>';
    });
  ecContent.innerHTML =
    '<div class="ec-name">'+n.name+'</div>' +
    '<div class="ec-type"><span class="ec-dot" style="background:'+n.color+'"></span>'+n.type+'</div>' +
    (n.desc ? '<div class="ec-desc">'+n.desc+'</div>' : '') +
    (rows ? '<table>'+rows+'</table>' : '');
  entityCard.classList.add('visible');
}
function hideEntityCard() { entityCard.classList.remove('visible'); }

function dismissTooltip() { document.getElementById('graph-tooltip').classList.remove('visible'); }

// Cancel any in-flight animation when user interacts
function cancelAnimation() {
  network.moveTo({ position: network.getViewPosition(), scale: network.getScale(), animation: false });
}
network.on('zoom', cancelAnimation);

// Track dragging to suppress click-after-drag
let isDragging = false;
network.on('dragStart', () => { isDragging = true; cancelAnimation(); });
network.on('dragEnd', () => { setTimeout(() => { isDragging = false; }, 50); });

network.on('click', p => {
  if (isDragging) return;
  dismissTooltip();
  if (p.nodes.length > 0) {
    const nodeId = p.nodes[0];
    showEntityCard(nodeId);
    if (!scenarioMode) {
      // Compute camera target FIRST
      const nbrIds = new Set([nodeId]);
      (nodeEdgeMap[nodeId] || []).forEach(eid => {
        const r = edgeById[eid];
        if (r) { nbrIds.add(r.src); nbrIds.add(r.tgt); }
      });
      const pos = network.getPositions([...nbrIds]);
      const pts = Object.values(pos);
      if (pts.length > 0) {
        const cx = pts.reduce((s,p) => s+p.x, 0) / pts.length;
        const cy = pts.reduce((s,p) => s+p.y, 0) / pts.length;
        const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
        const span = Math.max(Math.max(...xs)-Math.min(...xs), Math.max(...ys)-Math.min(...ys), 150);
        const canvasH = document.getElementById('graph-container').clientHeight;
        const scale = Math.min(canvasH / (span * 1.1), 2.5);
        // Start camera animation immediately
        network.moveTo({ position: {x: cx, y: cy}, scale: scale,
          animation: { duration: 600, easingFunction: 'easeInOutQuad' } });
      }
      // Defer heavy styling updates so animation isn't blocked
      requestAnimationFrame(() => showEdgesForNode(nodeId));
    }
  } else if (p.edges && p.edges.length > 0) {
    // Clicked an edge — do nothing, don't zoom out
  } else {
    hideEntityCard();
    if (!scenarioMode) {
      // Start camera animation immediately
      network.fit({ animation: { duration: 600, easingFunction: 'easeInOutQuad' } });
      // Defer styling reset
      requestAnimationFrame(() => hideAllFocusEdges());
    }
  }
});
network.on('doubleClick', p => {
  if (p.nodes.length === 0 && !scenarioMode) zoomFit();
});

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
  visNodes.update(GRAPH_ENTITIES.map(n => ({ id: n.id, hidden: true })));
  visEdges.update(GRAPH_RELATIONSHIPS.map(r => ({ id: r.id, hidden: true })));
}

function revealItems(nodeIds, edgeIds, skipCamera) {
  // Batch node reveals
  const nodeUpdates = [];
  (nodeIds || []).forEach(nid => {
    if (revealedNodes.has(nid)) return;
    revealedNodes.add(nid);
    const n = entityById[nid];
    if (!n) return;
    const imp = n.importance || 0;
    nodeUpdates.push({ id: nid, hidden: false, opacity: 1,
      borderWidth: 3, borderWidthSelected: 4,
      color: { background: n.color, border: '#58a6ff',
        highlight: { background: n.color, border: '#f59e0b' },
        hover: { background: n.color, border: '#818cf8' } },
      font: { color: '#e8e6e3', size: 14 + imp * 6,
        face: "'DM Sans', system-ui, sans-serif",
        strokeWidth: 3, strokeColor: '#0b0f1a', vadjust: -2 },
      shadow: { enabled: true, color: '#58a6ff40', size: 16, x: 0, y: 0 },
    });
  });
  if (nodeUpdates.length) visNodes.update(nodeUpdates);
  // Batch edge reveals
  const edgeUpdates = [];
  (edgeIds || []).forEach(eid => {
    if (revealedEdges.has(eid)) return;
    revealedEdges.add(eid);
    const r = edgeById[eid];
    edgeUpdates.push({ id: eid, hidden: false, label: r ? r.type : '',
      color: { color: '#58a6ff', highlight: '#f59e0b', hover: '#58a6ff' },
      font: { size: 12, color: '#8bb8e8', face: "'DM Sans', system-ui, sans-serif",
        align: 'middle', strokeWidth: 2, strokeColor: '#0b0f1a', background: '#0b0f1a' },
      width: 2.5, arrows: { to: { enabled: true, scaleFactor: 0.7 } },
    });
  });
  if (edgeUpdates.length) visEdges.update(edgeUpdates);
  // Only move camera if we actually revealed new content and not suppressed
  if (!skipCamera && (nodeUpdates.length > 0 || edgeUpdates.length > 0)) {
    const fitNodes = new Set(nodeIds || []);
    (edgeIds || []).forEach(eid => {
      const r = edgeById[eid];
      if (r) { fitNodes.add(r.src); fitNodes.add(r.tgt); }
    });
    if (fitNodes.size > 0) {
      const pos = network.getPositions([...fitNodes]);
      const pts = Object.values(pos);
      const cx = pts.reduce((s,p)=>s+p.x,0)/pts.length;
      const cy = pts.reduce((s,p)=>s+p.y,0)/pts.length;
      const xs = pts.map(p=>p.x), ys = pts.map(p=>p.y);
      const span = Math.max(Math.max(...xs)-Math.min(...xs), Math.max(...ys)-Math.min(...ys), 120);
      const scale = Math.min(document.getElementById('graph-container').clientHeight / (span * 1.3), 2.0);
      // Offset center to account for entity card (340px) covering left side
      const cardOffset = entityCard.classList.contains('visible') ? 170 / scale : 0;
      network.moveTo({ position: {x: cx - cardOffset, y: cy}, scale: scale,
        animation: { duration: 600, easingFunction: 'easeInOutQuad' } });
    }
  }
}

function restoreFullGraph() {
  scenarioMode = false;
  focusedNodeEdges = new Set();
  focusedNeighborIds = new Set();
  visNodes.update(GRAPH_ENTITIES.map(n => { const v = buildVisNode(n); v.hidden = false; return v; }));
  visEdges.update(GRAPH_RELATIONSHIPS.map(r => { const v = buildVisEdge(r); v.hidden = false; return v; }));
  network.fit({ animation: { duration: 400, easingFunction: 'easeInOutQuad' } });
}

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

// Click overlays to advance
document.getElementById('overlay-problem').addEventListener('click', (e) => { if (e.target.tagName !== 'BUTTON') goToBeat(2); });
document.getElementById('overlay-pipeline').addEventListener('click', (e) => { if (e.target.tagName !== 'BUTTON') goToBeat(3); });

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
  dismissTooltip();
  currentScenario = s;
  currentStep = -1;
  document.getElementById('active-scenario-name').textContent = s.name;
  document.getElementById('agent-log').innerHTML = '';
  hideAllGraph();
  showActivePanel();
  goStep(0);
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
    d.onclick = () => { clearInterval(autoTimer); goStep(i); };
    el.appendChild(d);
  }
}

function goStep(idx) {
  if (!currentScenario) return;
  const steps = currentScenario.steps;
  if (idx < 0 || idx >= steps.length) return;

  if (idx < currentStep) {
    hideAllGraph();
    // Rebuild without camera movement, then move camera once at the end
    for (let i = 0; i <= idx; i++) {
      revealItems(steps[i].nodes, steps[i].edges, true);
    }
    // Single camera move to the target step's nodes
    const targetNodes = new Set(steps[idx].nodes || []);
    (steps[idx].edges || []).forEach(eid => {
      const r = edgeById[eid];
      if (r) { targetNodes.add(r.src); targetNodes.add(r.tgt); }
    });
    if (targetNodes.size > 0) {
      const pos = network.getPositions([...targetNodes]);
      const pts = Object.values(pos);
      const cx = pts.reduce((s,p)=>s+p.x,0)/pts.length;
      const cy = pts.reduce((s,p)=>s+p.y,0)/pts.length;
      const xs = pts.map(p=>p.x), ys = pts.map(p=>p.y);
      const span = Math.max(Math.max(...xs)-Math.min(...xs), Math.max(...ys)-Math.min(...ys), 120);
      const scale = Math.min(document.getElementById('graph-container').clientHeight / (span * 1.3), 2.0);
      const cardOff = entityCard.classList.contains('visible') ? 170 / scale : 0;
      network.moveTo({ position: {x: cx - cardOff, y: cy}, scale: scale,
        animation: { duration: 600, easingFunction: 'easeInOutQuad' } });
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
  btnNext.textContent = idx === steps.length - 1 ? 'See Results \u25b6' : 'Next \u25b6';
  btnAuto.disabled = false;

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
  if (autoTimer) { clearInterval(autoTimer); autoTimer = null; btnAuto.textContent = 'Auto \u25b6\u25b6'; return; }
  btnAuto.textContent = 'Pause \u23f8';
  autoTimer = setInterval(() => {
    if (!currentScenario || currentStep >= currentScenario.steps.length - 1) {
      clearInterval(autoTimer); autoTimer = null; btnAuto.textContent = 'Auto \u25b6\u25b6';
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

  // Zoom out to show the full traversed graph
  if (revealedNodes.size > 0) {
    network.fit({ nodes: [...revealedNodes],
      animation: { duration: 800, easingFunction: 'easeInOutQuad' } });
  }

  const s = currentScenario;
  const sevClass = s.severity;
  let html = '<div class="plan-header">' +
    '<div class="plan-incident">'+s.incidentLabel+'</div>' +
    '<div class="plan-severity '+sevClass+'">'+s.sevLabel+'</div></div>';

  s.actions.forEach((a, i) => {
    html += '<div class="action-item" style="animation-delay:'+i*0.08+'s">' +
      '<div class="action-name">'+(i+1)+'. '+a.name+'</div>' +
      '<div class="action-meta">' +
        '<span class="action-time">\u23f1 '+a.time+'</span>' +
        '<span class="action-who">&#128100; '+a.who+'</span>' +
      '</div></div>';
  });

  html += '<div class="traversal-stats">' +
    '<div class="tstat"><strong>'+revealedNodes.size+'</strong> nodes traversed</div>' +
    '<div class="tstat"><strong>'+revealedEdges.size+'</strong> edges followed</div>' +
    '<div class="tstat"><strong>'+s.actions.length+'</strong> actions identified</div>' +
    '<div class="tstat"><strong>&lt; 1ms</strong> traversal time</div></div>';

  document.getElementById('results-content').innerHTML = html;
}

// ======================================================================
//  INIT
// ======================================================================
goToBeat(1);
</script>
</body>
</html>'''

with open("demo_v2.html", "w", encoding="utf-8") as f:
    f.write(html)

import os
size_kb = os.path.getsize("demo_v2.html") / 1024
print(f"Written demo_v2.html ({size_kb:.0f} KB)")
