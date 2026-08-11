#!/usr/bin/env python3
"""Regenerate tools/tokidex.html — the shareable TOKIDEX page: the whole
evolution line plus a live status-bar demo.

Reads evolution_data.json, so the page can never drift from the real sprites;
re-run it after any art change. The published version once sat a full sprite
redesign behind the engine because it had been hand-built from a copy.

    python3 tools/make_tokidex.py

Publishing the result updates the existing artifact only when its URL is passed
along — a bare publish of this file mints a new one:

    https://claude.ai/code/artifact/741f2998-e4c9-4388-ab56-349feac25956

Values mirrored from the engine (keep them in step by hand if they move):
SPRITE_FPS_IDLE, PRESTIGE_BOOST, SHINY_HUE_STEP, and the AGENT_STYLES roster,
all from digimon_sprites / digimon_lib.
"""
import json
import os
import pathlib

HERE = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
REPO = HERE.parent
OUT = HERE / "tokidex.html"

data = json.loads((REPO / "evolution_data.json").read_text())

# Only what the page draws — keeps the payload lean (the ASCII `art` fallback
# and the level curve are engine-side concerns).
slim = {
    "palette": data["palette"],
    "caps": data["cap_tiers"],
    "stages": [
        {k: s[k] for k in ("name", "stage", "emoji", "tagline", "min", "max", "sprite")}
        for s in data["stages"]
    ],
}
payload = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))

HTML = """<title>TOKIDEX — 8-bit Companion</title>
<style>
  :root{
    --ground:#0e1120; --panel:#161a2e; --panel-2:#1c2138; --edge:#2a3150;
    --ink:#dfe7f5; --muted:#8b9bb4;
    --cyan:#5fd3ff; --gold:#ffcc33; --indigo:#7b7bff; --green:#42e29b;
    --dim2:#5a678a;
    --mono:ui-monospace,"SFMono-Regular","Cascadia Code",Menlo,Consolas,monospace;
    --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{
    background:
      radial-gradient(1200px 700px at 50% -10%, #1a2140 0%, transparent 60%),
      var(--ground);
    color:var(--ink); font-family:var(--sans);
    line-height:1.5; -webkit-font-smoothing:antialiased;
    padding:clamp(16px,4vw,44px);
  }
  .wrap{max-width:1080px;margin:0 auto}

  /* ---- device header ---- */
  .device{
    border:1px solid var(--edge);
    background:linear-gradient(180deg,var(--panel-2),var(--panel));
    border-radius:18px; padding:clamp(18px,3vw,30px);
    box-shadow:0 20px 60px -30px #000, inset 0 1px 0 #ffffff12;
    position:relative; overflow:hidden;
  }
  .device::before{ /* scanlines */
    content:"";position:absolute;inset:0;pointer-events:none;opacity:.5;
    background:repeating-linear-gradient(0deg,#0000 0 2px,#0000000f 2px 3px);
  }
  .brandrow{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
  .brand{
    font-family:var(--mono);font-weight:700;letter-spacing:.32em;
    text-transform:uppercase;font-size:clamp(20px,3.4vw,30px);
    color:var(--ink);margin:0;
    text-shadow:0 0 18px #5fd3ff55;
  }
  .brand b{color:var(--cyan)}
  .subtitle{font-family:var(--mono);color:var(--muted);font-size:12px;letter-spacing:.18em;text-transform:uppercase}

  /* ---- status bar demo (the actual feature) ---- */
  .screen{
    margin-top:18px;border:1px solid #0c1024;border-radius:12px;
    background:#080a16;
    box-shadow:inset 0 0 40px #000a, inset 0 0 0 1px #ffffff08;
    padding:16px 18px;
  }
  .barlabel{font-family:var(--mono);font-size:10px;letter-spacing:.24em;text-transform:uppercase;color:var(--dim2);margin-bottom:8px}
  .statusline{
    font-family:var(--mono);font-size:clamp(13px,2.2vw,17px);
    white-space:pre;overflow-x:auto;color:#cfe8ff;
    text-shadow:0 0 10px #5fd3ff40;letter-spacing:.02em;
    padding-bottom:2px;
  }
  .statusline .fill{color:var(--cyan)}
  .statusline .edge{color:#bdecff}
  .statusline .empty{color:#26406b}
  .statusline .agent{color:var(--gold)}
  .controls{display:flex;gap:8px;margin-top:16px;flex-wrap:wrap;align-items:center}
  button.toggle{
    font-family:var(--mono);font-size:11px;letter-spacing:.14em;text-transform:uppercase;
    color:var(--muted);background:var(--panel);border:1px solid var(--edge);
    padding:8px 14px;border-radius:9px;cursor:pointer;transition:.15s;
  }
  button.toggle[aria-pressed="true"]{color:#08111e;background:var(--cyan);border-color:var(--cyan);font-weight:700}
  button.toggle:focus-visible{outline:2px solid var(--gold);outline-offset:2px}
  .hint{font-family:var(--mono);font-size:11px;color:var(--dim2);letter-spacing:.06em}

  /* ---- prestige rail ---- */
  .prestige{display:flex;align-items:center;gap:12px;margin-top:16px;flex-wrap:wrap}
  .plabel{font-family:var(--mono);font-size:10px;letter-spacing:.24em;text-transform:uppercase;color:var(--dim2)}
  .step{
    font-family:var(--mono);font-size:16px;line-height:1;width:30px;height:30px;
    color:var(--gold);background:var(--panel);border:1px solid var(--edge);
    border-radius:8px;cursor:pointer;transition:.15s;
  }
  .step:hover{border-color:var(--gold)}
  .step:focus-visible{outline:2px solid var(--gold);outline-offset:2px}
  .pbadge{
    font-family:var(--mono);font-weight:700;font-size:16px;color:var(--gold);
    min-width:56px;text-align:center;letter-spacing:.06em;
    text-shadow:0 0 12px #ffcc3355;
  }
  .pgrowth{font-family:var(--mono);font-size:11px;color:var(--green);letter-spacing:.06em}

  /* ---- surfaces strip ---- */
  .surfaces{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin-top:16px}
  .surface{border:1px solid var(--edge);background:#11142400;border-radius:11px;padding:11px 13px}
  .surface .st{font-family:var(--mono);font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--cyan)}
  .surface .sd{font-size:12.5px;color:var(--muted);margin-top:4px;line-height:1.4}

  /* ---- dex grid ---- */
  .sectionhead{display:flex;align-items:baseline;gap:12px;margin:36px 2px 16px}
  .sectionhead h2{font-family:var(--mono);text-transform:uppercase;letter-spacing:.2em;font-size:14px;margin:0;color:var(--muted)}
  .rule{flex:1;height:1px;background:linear-gradient(90deg,var(--edge),transparent)}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:14px}
  .card{
    position:relative;border:1px solid var(--edge);border-radius:14px;
    background:linear-gradient(180deg,var(--panel),#12162a);
    padding:16px 16px 15px;overflow:hidden;
    transition:transform .18s ease, border-color .18s ease;
  }
  .card:hover{transform:translateY(-3px);border-color:#3a4166}
  .no{position:absolute;top:12px;right:14px;font-family:var(--mono);font-size:11px;color:var(--dim2);font-variant-numeric:tabular-nums;letter-spacing:.08em}
  .spritebox{
    height:150px;display:flex;align-items:center;justify-content:center;
    position:relative;margin:2px 0 8px;
  }
  .glow{position:absolute;width:120px;height:120px;border-radius:50%;filter:blur(26px);opacity:.5}
  canvas{position:relative;image-rendering:pixelated;width:128px;height:128px}
  .bob{animation:bob 2.4s ease-in-out infinite}
  @keyframes bob{0%,100%{transform:translateY(2px)}50%{transform:translateY(-4px)}}
  .namerow{display:flex;align-items:center;gap:8px}
  .name{font-family:var(--mono);font-weight:700;font-size:15px;letter-spacing:.02em}
  .emoji{font-size:15px;filter:saturate(1.1)}
  .badge{
    display:inline-block;margin-top:7px;font-family:var(--mono);font-size:10px;
    letter-spacing:.14em;text-transform:uppercase;padding:3px 8px;border-radius:6px;
    border:1px solid #ffffff1c;color:#0b0e17;font-weight:700;
  }
  .lvl{font-family:var(--mono);font-size:11px;color:var(--muted);margin-top:8px;font-variant-numeric:tabular-nums;letter-spacing:.05em}
  .tag{font-size:12.5px;color:var(--muted);margin-top:6px;line-height:1.45}

  footer{margin-top:34px;color:var(--dim2);font-family:var(--mono);font-size:11px;letter-spacing:.05em;text-align:center;line-height:1.9}
  footer b{color:var(--muted)}
  @media (prefers-reduced-motion: reduce){ .bob{animation:none} }
</style>

<div class="wrap">
  <div class="device">
    <div class="brandrow">
      <h1 class="brand">TOKI<b>DEX</b></h1>
      <span class="subtitle">16 stages · two-frame 16×16 sprites · rebirth loop</span>
    </div>

    <div class="screen">
      <div class="barlabel">Status bar · live preview</div>
      <div class="statusline" id="statusline" aria-live="polite"></div>
      <div class="controls">
        <button class="toggle" id="mode-idle" aria-pressed="true">Idle</button>
        <button class="toggle" id="mode-train" aria-pressed="false">Training w/ agent</button>
        <button class="toggle" id="mode-rebirth" aria-pressed="false">Rebirth ✨</button>
        <span class="hint" id="modehint">the pet rests · XP bar charges</span>
      </div>
      <div class="prestige">
        <span class="plabel">Prestige</span>
        <button class="step" id="p-down" aria-label="Lower prestige">−</button>
        <span class="pbadge" id="p-badge">—</span>
        <button class="step" id="p-up" aria-label="Raise prestige">+</button>
        <span class="pgrowth" id="p-growth">no boost yet · sprites at their base palette</span>
      </div>
    </div>

    <div class="surfaces">
      <div class="surface"><div class="st">Status bar</div>
        <div class="sd">One line under the prompt — sprite glyph, stage, level, charging XP bar, tokens.</div></div>
      <div class="surface"><div class="st">Menu-bar app</div>
        <div class="sd">macOS AppKit companion: animated sprite + segmented XP bar, click for the detail panel.</div></div>
      <div class="surface"><div class="st">LAN feed</div>
        <div class="sd"><code>tokimon_serve.py</code> serves the JSON snapshot — stage, XP, frames, palette, live agents — to anything on the network.</div></div>
    </div>
  </div>

  <div class="sectionhead">
    <h2>Evolution line</h2>
    <div class="rule"></div>
  </div>
  <div class="grid" id="grid"></div>

  <footer>
    <div><b>Fuel:</b> real token usage per turn · <b>Detection:</b> reads the live transcript for the active agent</div>
    <div>Egg → Rookie → Champion → … → Sovereign → Celestial → Aeon (Lv.750 ceiling)</div>
    <div><b>Rebirth:</b> hit Lv.750 → reset to the Egg, bank a ★ prestige rank · +6% growth per star</div>
  </footer>
</div>

<script>
const DATA = __DATA__;

// The engine's real sub-agent roster (digimon_sprites.AGENT_STYLES), project agents only.
const AGENTS = [
  {emoji:"✍️", label:"Ekleberry"},
  {emoji:"🚀", label:"Cosmic Code"},
  {emoji:"🖨️", label:"Lumalith"},
  {emoji:"🖍️", label:"Coloring Books"},
  {emoji:"🛒", label:"ThriveMade"},
  {emoji:"🌿", label:"OAK Canna"},
  {emoji:"📈", label:"Trading"},
];

// ---------- sprite rendering ----------
// Sprites are a list of frames; the body loops at 2 fps idle, 4 fps sparring
// (digimon_sprites.SPRITE_FPS_IDLE / SPRITE_FPS_TRAINING).
const SPRITE_FPS_IDLE = 2, PRESTIGE_BOOST = 0.06;
function framesOf(stage){
  const s = stage.sprite;
  if(!s || !s.length) return [];
  return typeof s[0] === "string" ? [s] : s;   // a bare frame, or a list of frames
}
function domColor(frame, palette){
  const tally = {};
  for(const row of frame) for(const ch of row){
    const c = palette[ch]; if(!c) continue;
    if(c === "#0b0e17" || c === "#141a2b") continue; // ignore outline
    tally[c] = (tally[c]||0)+1;
  }
  let best="#5fd3ff", n=-1;
  for(const c in tally){ if(tally[c]>n){n=tally[c];best=c;} }
  return best;
}
function drawSprite(canvas, frame, palette){
  const rows = frame.length, cols = frame[0].length;
  const dpr = Math.max(1, Math.min(3, window.devicePixelRatio||1));
  const px = Math.round(128 / Math.max(rows, cols));
  const W = cols*px, H = rows*px;
  canvas.style.width = W+"px"; canvas.style.height = H+"px";
  canvas.width = W*dpr; canvas.height = H*dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr,0,0,dpr,0,0);
  ctx.clearRect(0,0,W,H);
  ctx.imageSmoothingEnabled = false;
  for(let y=0;y<rows;y++){
    const row = frame[y];
    for(let x=0;x<row.length;x++){
      const c = palette[row[x]];
      if(!c) continue;
      ctx.fillStyle = c;
      ctx.fillRect(x*px, y*px, px, px);
    }
  }
}

// ---------- shiny recolor (mirrors digimon_sprites.shiny_palette) ----------
const SHINY_STEP = 0.381966;
function hexToRgb(h){ h=h.replace("#",""); return [parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)]; }
function rgbToHls(r,g,b){
  r/=255; g/=255; b/=255;
  const mx=Math.max(r,g,b), mn=Math.min(r,g,b), l=(mx+mn)/2;
  if(mx===mn) return [0,l,0];
  const d=mx-mn, s = l>0.5 ? d/(2-mx-mn) : d/(mx+mn);
  let h; if(mx===r) h=(g-b)/d+(g<b?6:0); else if(mx===g) h=(b-r)/d+2; else h=(r-g)/d+4;
  return [h/6,l,s];
}
function hlsToRgb(h,l,s){
  if(s===0){ const v=Math.round(l*255); return [v,v,v]; }
  const q = l<0.5 ? l*(1+s) : l+s-l*s, p = 2*l-q;
  const hue = t => { if(t<0)t+=1; if(t>1)t-=1;
    if(t<1/6) return p+(q-p)*6*t; if(t<1/2) return q;
    if(t<2/3) return p+(q-p)*(2/3-t)*6; return p; };
  return [Math.round(hue(h+1/3)*255),Math.round(hue(h)*255),Math.round(hue(h-1/3)*255)];
}
function shinyPalette(pal, prestige){
  if(!prestige) return pal;
  const shift = (prestige*SHINY_STEP)%1;
  const out={};
  for(const k in pal){ const v=pal[k]; if(!v){ out[k]=v; continue; }
    let [h,l,s]=rgbToHls(...hexToRgb(v)); h=(h+shift)%1; s=Math.min(1,s*1.08);
    out[k]="#"+hlsToRgb(h,l,s).map(x=>x.toString(16).padStart(2,"0")).join(""); }
  return out;
}
function prestigeSymbol(n){ return n>=20?"❖":n>=10?"✧":n>=5?"✦":"★"; }
function prestigeBadge(n){ if(!n) return ""; const s=prestigeSymbol(n); return n<=3 ? s.repeat(n) : s+n; }

// ---------- build dex ----------
const grid = document.getElementById("grid");
const CARDS = [];
DATA.stages.forEach((s, i) => {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <span class="no">${String(i).padStart(2,"0")} / ${String(DATA.stages.length-1).padStart(2,"0")}</span>
    <div class="spritebox">
      <div class="glow"></div>
      <canvas class="bob" aria-label="${s.name} pixel sprite"></canvas>
    </div>
    <div class="namerow"><span class="emoji">${s.emoji}</span><span class="name">${s.name}</span></div>
    <span class="badge">${s.stage}</span>
    <div class="lvl">Lv. ${s.min}–${s.max}</div>
    <div class="tag">${s.tagline}</div>
  `;
  grid.appendChild(card);
  CARDS.push({ frames:framesOf(s), canvas:card.querySelector("canvas"),
               glow:card.querySelector(".glow"), badge:card.querySelector(".badge") });
});

let palNow = DATA.palette, frameNow = -1;
function paintAll(frame){
  for(const c of CARDS){
    if(!c.frames.length) continue;
    const f = c.frames[frame % c.frames.length];
    drawSprite(c.canvas, f, palNow);
    const accent = domColor(f, palNow);
    c.glow.style.background = accent;
    c.badge.style.background = accent;
  }
}

// ---------- animated status-bar demo ----------
const SHIMMER = ["▏","▎","▍","▌","▋","▊","▉","█"];
const AURA = ["·","˖","∘","˖"];
const CLASH = ["⚔️","💥","✨","🔥"];
const sovereign = DATA.stages.find(s => s.name === "Omniloadmon") || DATA.stages[10];
const egg = DATA.stages[0];
const DEMO = { name:"Tokimon", emoji:sovereign.emoji, stage:sovereign.name, level:456, cap:500, frac:0.42, tok:"1.5B", prestige:0 };
function stars(n){ return !n ? "" : (n<=3 ? "★".repeat(n) : "★"+n); }
let mode = "idle", agentIdx = 0, agentTimer = 0;

function shimmerBar(frac, width, t){
  const full = Math.floor(frac*width);
  if(full>=width) return {fill:"█".repeat(width), edge:"", empty:""};
  const edge = SHIMMER[Math.floor(t*2)%SHIMMER.length];
  return {fill:"█".repeat(full), edge, empty:"░".repeat(width-full-1)};
}
function bar(frac,width,t){
  const b = shimmerBar(frac,width,t);
  return `<span class="fill">${b.fill}</span><span class="edge">${b.edge}</span><span class="empty">${b.empty}</span>`;
}
function render(t){
  const el = document.getElementById("statusline");
  const star = `<span class="agent">${stars(DEMO.prestige)}</span>`;
  if(mode==="idle"){
    const aura = AURA[Math.floor(t*2)%AURA.length];
    el.innerHTML = `${DEMO.emoji}${star}${aura} ${DEMO.name} · ${DEMO.stage} Lv.${DEMO.level}/${DEMO.cap} [${bar(DEMO.frac,10,t)}] ${DEMO.tok} tok`;
  } else if(mode==="train"){
    const a = AGENTS[agentIdx];
    const clash = CLASH[Math.floor(t*2)%CLASH.length];
    const elapsed = Math.floor((t-agentTimer));
    const el2 = elapsed<60 ? elapsed+"s" : Math.floor(elapsed/60)+"m";
    el.innerHTML = `${DEMO.emoji}${star}${clash}<span class="agent">${a.emoji}</span> ${DEMO.name} training w/ <span class="agent">${a.label}</span> · Lv.${DEMO.level} [${bar(DEMO.frac,8,t)}] ⏱${el2}`;
  } else { // rebirth: ceiling -> egg, +1 star
    const phase = (t-agentTimer) % 4;
    const nextStar = DEMO.prestige + 1;
    if(phase < 1.6){
      el.innerHTML = `${DATA.stages[DATA.stages.length-1].emoji}<span class="agent">${stars(DEMO.prestige)}</span> ${DEMO.name} · Aeon Lv.750/750 [<span class="fill">${"█".repeat(10)}</span>] ✦ MAX`;
    } else if(phase < 2.4){
      el.innerHTML = `<span class="agent">✨✨✨  R E B I R T H  ✨✨✨</span>`;
    } else {
      const aura = AURA[Math.floor(t*2)%AURA.length];
      const pct = Math.round(nextStar * PRESTIGE_BOOST * 100);
      el.innerHTML = `${egg.emoji}<span class="agent">${stars(nextStar)}</span>${aura} ${DEMO.name} · Digitama Lv.1/${DATA.caps[0]} [${bar(0.05,10,t)}] +${pct}% growth`;
    }
  }
}
function setMode(m){
  mode = m;
  for(const id of ["idle","train","rebirth"])
    document.getElementById("mode-"+id).setAttribute("aria-pressed", m===id);
  document.getElementById("modehint").textContent =
    m==="idle" ? "the pet rests · XP bar charges" :
    m==="train" ? "sparring with the active subagent — cycles agents" :
    "loops the Lv.750 ceiling → reborn as the Egg, banks a ★ + growth";
  agentTimer = performance.now()/1000;
}
document.getElementById("mode-idle").onclick = ()=>setMode("idle");
document.getElementById("mode-train").onclick = ()=>setMode("train");
document.getElementById("mode-rebirth").onclick = ()=>setMode("rebirth");

function loop(){
  const t = performance.now()/1000;
  if(mode==="train" && t-agentTimer>4){ agentIdx=(agentIdx+1)%AGENTS.length; agentTimer=t; }
  render(t);
  const f = Math.floor(t*SPRITE_FPS_IDLE);
  if(f !== frameNow){ frameNow = f; paintAll(f); }
  requestAnimationFrame(loop);
}

// ---------- prestige stepper (recolor + badge) ----------
let pval = 0;
function applyPrestige(n){
  pval = Math.max(0, Math.min(30, n));
  DEMO.prestige = pval;
  document.getElementById("p-badge").textContent = pval ? prestigeBadge(pval) : "—";
  document.getElementById("p-growth").textContent = pval
    ? `+${Math.round(pval*PRESTIGE_BOOST*100)}% growth · shiny palette · life #${pval+1}`
    : "no boost yet · sprites at their base palette";
  palNow = shinyPalette(DATA.palette, pval);
  paintAll(frameNow < 0 ? 0 : frameNow);
}
document.getElementById("p-up").onclick = ()=>applyPrestige(pval+1);
document.getElementById("p-down").onclick = ()=>applyPrestige(pval-1);
applyPrestige(0);
setMode("idle");
loop();
</script>
"""

OUT.write_text(HTML.replace("__DATA__", payload))
print("wrote", OUT, OUT.stat().st_size, "bytes")
print("stages:", len(slim["stages"]),
      "· frames/stage:", len(slim["stages"][0]["sprite"]),
      "· sprite size:", len(slim["stages"][0]["sprite"][0]), "x",
      len(slim["stages"][0]["sprite"][0][0]))
