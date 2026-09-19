/* pakka — one board, four columns, driven by /state → /run → /decide → /autopilot. No framework.

   Every chain the agent attempts (a root write plus the writes that depend on it) is one card. The layer's
   decisions move the card: Not started → In progress → Needs human approval (held) or Complete (sent). The
   demo buttons replay the agent's runs; the board animates each write as it is replayed, at the same pace
   the feed used to. Clicking a card opens the full record. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ state
  const COLS = ["not_started", "in_progress", "needs_approval", "complete"];
  const COL_TITLE = { not_started: "Not started", in_progress: "In progress", needs_approval: "Needs human approval", complete: "Complete" };
  const S = {
    view: null,          // StateView from GET /state or POST /reset
    screen: "opening",
    busy: false,
    review: freshReview(),   // the demo's review run
    live: freshReview(),     // a run the real agent produced just now (Q&A)
    scenario: null,          // GET /scenario, fetched once the rule form needs it
    montage: { done: false, running: false },
    auto: { running: false, played: [] },
    phase: { name: "", mode: "review", totals: zeroCounts() },
    cards: new Map(),        // key -> card (see makeChainCard / makeRuleCard / makeQueuedCard)
    hero: { label: "", line: "", running: false, after: "" },
    latest: null,            // the learn event the bar is showing
    colBanner: "",           // the approval column's banner while a montage runs
    rail: false,             // the learned panel beside the board (Play 5 Fridays)
    applying: undefined,     // true while Approve lands, null once it has, undefined otherwise
    opened: null,            // key of the card in the dialog
  };
  let R = S.review; // the review target on screen
  const REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const NARROW = () => window.matchMedia && window.matchMedia("(max-width: 1100px)").matches;
  const EASE = "cubic-bezier(0.2, 0.7, 0.2, 1)";
  const MOVE_MS = 320;

  const $ = (id) => document.getElementById(id);
  const main = $("main");
  const dlg = $("detail");

  function freshReview(run, banner) {
    return { run: run || null, banner: banner || "", discards: [], rules: [], later: [], cascade: {}, decided: false, response: null };
  }
  function zeroCounts() {
    return { fridays: 0, checked: 0, through: 0, held: 0, caught: 0, wrongly_held: 0, volume: 0, anomalies: 0 };
  }

  // ------------------------------------------------------------------ api
  async function api(method, path, body) {
    const r = await fetch(path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) {
      let detail = r.statusText;
      try { detail = (await r.json()).detail || detail; } catch (e) { /* ignore */ }
      if (Array.isArray(detail)) detail = detail.map((d) => `${(d.loc || []).filter((p) => p !== "body").join(".")}: ${d.msg}`).join("; ");
      const err = new Error(`${method} ${path} → ${r.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
      err.status = r.status; err.detail = typeof detail === "string" ? detail : JSON.stringify(detail);
      throw err;
    }
    return r.json();
  }
  const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

  // ------------------------------------------------------------------ helpers
  const REF_TOKEN = /\b[A-Z]{2,6}-\d{3,}\b/;
  const PH_RE = /ph_[0-9a-f]{12}/g;
  function shape(v) {
    if (v === null || v === undefined || v === "") return "empty";
    if (typeof v === "boolean") return "bool";
    if (typeof v === "number") return "number";
    if (typeof v !== "string") return "text";
    const s = v.trim();
    if (/^ph_[0-9a-f]{12}$/.test(s)) return "placeholder";
    if (/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(s)) return "email";
    if (/^\d{2}-\d{2}-\d{2}\s?\d{6,8}$/.test(s)) return "account";
    if (/^[A-Z]{2,6}-\d{3,}$/.test(s)) return "ref";
    if (/^[a-z]{2,4}_[A-Za-z0-9]{4,}$/.test(s)) return "id";
    if (s.length <= 40 && s.split(/\s+/).length <= 5 && !s.includes("\n")) return "name";
    return "text";
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function unit() { return (S.view && S.view.volume_unit) || ""; }
  function money(n) {
    if (typeof n !== "number") return "";
    return unit() + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function money0(n) { return unit() + Math.round(n).toLocaleString("en-GB"); }
  function label() { return (S.view && S.view.run_label) || "Run"; }
  function fri(n) { return `${label().slice(0, 3)} ${n}`; }
  function args(w) { return w.edited_args || w.args; }
  function firstOf(a, shapes) {
    for (const [k, v] of Object.entries(a)) if (shapes.includes(shape(v))) return [k, v];
    return [null, null];
  }
  function shortTool(name) { const parts = String(name).split("_"); return parts.length >= 2 ? parts.slice(1).join("_") : name; } // the verb is in the chip's title
  function el(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }
  function setScreen(name) { S.screen = name; main.dataset.screen = name; const strip = main.querySelector(".strip"); if (strip) strip.classList.toggle("opening", name === "opening"); } // video/record.py waits on [data-screen=…]
  function firstReviewRun() { return (S.view && S.view.review_runs && S.view.review_runs[0]) || 1; }
  function runOf(n) { return S.view && S.view.runs[String(n)]; }
  function reviewRun() { return R.run || firstReviewRun(); }
  function released(tool) { const l = (S.view.learned.ladder || []).find((x) => x.tool === tool); return !!l && l.level === "released"; }
  function summary(w) {
    const a = args(w);
    const [, email] = firstOf(a, ["email"]);
    const [, name] = firstOf(a, ["name"]);
    const [, ident] = firstOf(a, ["ref", "account", "id"]);
    const [, num] = firstOf(a, ["number"]);
    const bits = [];
    if (name) bits.push(name);
    if (email) bits.push(email);
    if (typeof num === "number" && !email) bits.push(money(num));
    if (ident && !email) bits.push(ident);
    return bits.join(" · ");
  }

  // chains: one card per root write (no depends_on); dependents follow the placeholders
  function chains(rr) {
    const roots = rr.writes.filter((w) => !w.depends_on.length);
    return roots.map((root) => {
      const deps = [];
      const dead = new Set([root.placeholder]);
      let changed = true;
      while (changed) {
        changed = false;
        for (const w of rr.writes) {
          if (w !== root && !deps.includes(w) && w.depends_on.some((p) => dead.has(p))) { deps.push(w); dead.add(w.placeholder); changed = true; }
        }
      }
      deps.sort((a, b) => a.seq - b.seq);
      return { root, deps };
    });
  }

  // ------------------------------------------------------------------ the registry
  // A chain card carries `disp`: what the board shows for each member right now. The replay walkers move `disp`
  // one write at a time behind the server's answer; at rest `disp` is exactly what the server says.
  function serverDisp(w) {
    if (w.sent) return "sent";
    if (w.status === "held") return w.blocked_by.length ? "blocked" : "held";
    if (w.status === "discarded") return "discarded";
    if (w.status === "skipped") return "skipped";
    return "sent";
  }
  const REVEALED = (d) => d && d !== "pending" && d !== "active";
  function chainKey(run, rootId) { return `${run}:${rootId}`; }
  function makeChainCard(rr, c, disp) {
    const key = chainKey(rr.run, c.root.id);
    let card = S.cards.get(key);
    if (!card) {
      card = { key, kind: "chain", run: rr.run, rootId: c.root.id, ids: [], disp: {}, simHold: false, el: null, col: null, sig: "" };
      S.cards.set(key, card);
    }
    card.ids = [c.root.id, ...c.deps.map((d) => d.id)];
    for (const id of card.ids) if (!(id in card.disp) || disp !== undefined) card.disp[id] = disp === undefined ? serverDisp(memberOf(card, id)) : disp;
    return card;
  }
  function memberOf(card, id) { const rr = runOf(card.run); return rr && rr.writes.find((w) => w.id === id); }
  function members(card) { return card.ids.map((id) => memberOf(card, id)).filter(Boolean); }
  function root(card) { return memberOf(card, card.rootId); }
  function makeRuleCard(run, rule) {
    const key = `rule:${run}:${rule.id}`;
    let card = S.cards.get(key);
    if (!card) { card = { key, kind: "rule", run, rule, el: null, col: null, sig: "" }; S.cards.set(key, card); }
    card.rule = rule;
    return card;
  }
  function makeQueuedCard(run) {
    const key = `queued:${run}`;
    let card = S.cards.get(key);
    if (!card) { card = { key, kind: "queued", run, running: false, el: null, col: null, sig: "" }; S.cards.set(key, card); }
    return card;
  }
  function dropCard(key) {
    const card = S.cards.get(key);
    if (!card) return;
    S.cards.delete(key);
    if (S.opened === key) closeDialog();
    cancelGhost(key);
    if (card.el) {
      const node = card.el; card.el = null;
      if (REDUCED || !node.isConnected) { node.remove(); return; }
      node.classList.add("leaving");
      setTimeout(() => node.remove(), 200);
    }
  }
  function modeTag(run) {
    const v = S.view;
    if (v.review_runs.includes(run)) return "review";
    if (v.montage_runs.includes(run)) return `Play 5`;
    if (v.autopilot_runs.includes(run)) return "autopilot";
    return "later";
  }
  // the Fridays the next button will play: those are shown as cards, the rest is one line
  function nextPhaseRuns() {
    const v = S.view;
    const unplayed = (runs) => runs.filter((f) => !v.runs[String(f)]);
    if (unplayed(v.montage_runs).length) return unplayed(v.montage_runs);
    if (unplayed(v.autopilot_runs).length) return unplayed(v.autopilot_runs);
    const out = [];
    for (let f = 1; f <= v.total_runs && out.length < 10; f++) if (!v.runs[String(f)]) out.push(f);
    return out;
  }
  // build every card from the view: played runs at rest, the rest queued
  function buildRegistry() {
    for (const key of [...S.cards.keys()]) { const c = S.cards.get(key); cancelGhost(key); if (c.el) c.el.remove(); S.cards.delete(key); }
    const v = S.view;
    for (const rr of Object.values(v.runs)) for (const c of chains(rr)) makeChainCard(rr, c);
    syncRuleCard();
    syncQueued();
  }
  function syncQueued() {
    const v = S.view;
    for (let f = 1; f <= v.total_runs; f++) {
      const key = `queued:${f}`;
      if (v.runs[String(f)]) { if (S.cards.has(key)) dropCard(key); } else makeQueuedCard(f);
    }
  }
  // the review target's rule card: proposed on the run, or (the demo's run) the rule that came from it once it went live
  function syncRuleCard() {
    const run = reviewRun();
    const rr = R.response ? R.response.run : runOf(run);
    if (!rr) return;
    const rule = rr.proposed_rules[0] || (R === S.review ? (S.view.learned.rules || []).find((r) => r.derived_from && r.status !== "rejected") : null);
    if (rule) makeRuleCard(run, rule);
  }

  // where a card sits, from what the board is showing
  function cardColumn(card) {
    if (card.kind === "queued") return card.running ? "in_progress" : "not_started";
    if (card.kind === "rule") return runDecided(card.run) ? "complete" : "needs_approval";
    const ds = card.ids.map((id) => card.disp[id] || "pending");
    if (ds.some((d) => d === "held" || d === "blocked")) return "needs_approval";
    if (ds.every((d) => d === "sent" || d === "discarded" || d === "skipped")) return "complete";
    if (ds.every((d) => d === "pending")) return "not_started";
    return "in_progress";
  }
  function runDecided(run) { const rr = R.response && R.response.run.run === run ? R.response.run : runOf(run); return !!(rr && rr.decided); }
  function isReviewTarget(card) { const rr = runOf(card.run); return card.run === reviewRun() && !!rr && !rr.decided && rr.mode !== "autopilot" && rr.mode !== "auto"; }
  function uiDiscarded(card) { return R.discards.includes(card.rootId) && card.run === reviewRun() && !runDecided(card.run); }
  function revealedMembers(card) { return members(card).filter((w) => REVEALED(card.disp[w.id])); }
  function flagged(card) { return revealedMembers(card).some((w) => w.flags.length); }
  function firstFlag(card) { for (const w of revealedMembers(card)) if (w.flags.length) return { w, f: w.flags[0] }; return null; }
  function orderKey(card, col) {
    const r = root(card);
    const seq = r ? r.seq : 0;
    // flagged chains, the rule card, the other chains, the queue — newest run first, the queue counting up
    const decided = col === "needs_approval" || col === "complete";
    const rank = card.kind === "queued" ? 3 : card.kind === "rule" ? 1 : decided && flagged(card) ? 0 : 2;
    const run = card.kind === "queued" ? card.run : -card.run;
    return [run, rank, seq];
  }
  function cmp(a, b) { for (let i = 0; i < a.length; i++) { if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1; } return 0; }

  // ------------------------------------------------------------------ card html
  function chainTitle(card) {
    const r = root(card);
    if (!r) return "";
    const [, name] = firstOf(args(r), ["name"]);
    return name || r.tool;
  }
  function chainAmount(card) { const r = root(card); if (!r) return ""; const [, num] = firstOf(args(r), ["number"]); return typeof num === "number" ? money(num) : ""; }
  function cascadeText(ids) {
    if (!ids || !ids.length) return "nothing else depends on it";
    return `also skips ${ids.length} dependent${ids.length === 1 ? "" : "s"}`;
  }
  function cascadeIds(card) {
    if (R.cascade[card.rootId] !== undefined && card.run === reviewRun()) return R.cascade[card.rootId];
    return members(card).filter((w) => w.status === "skipped").map((w) => w.id);
  }
  function memberDisp(card, w) {
    if (uiDiscarded(card)) {
      if (w.id === card.rootId) return "discarded";
      if (cascadeIds(card).includes(w.id)) return "will-skip";
    }
    return card.disp[w.id] || "pending";
  }
  function memberChip(card, w, col) {
    const d = memberDisp(card, w);
    const r = root(card);
    const title = `${w.tool} · ${w.placeholder}${w.result_id ? " → " + w.result_id : ""}${d === "blocked" && r ? ` · held behind ${r.tool}` : d === "will-skip" ? " · will be skipped" : ""}`;
    const id = d === "sent" && col !== "complete" && w.result_id ? `<span class="rid">→ ${esc(w.result_id)}</span>` : "";
    return `<span class="member" data-write="${esc(w.id)}" data-status="${esc(d)}" title="${esc(title)}">${esc(shortTool(w.tool))}${id}</span>`;
  }
  function chainFoot(card, col) {
    const ms = members(card), r = root(card);
    const sent = ms.filter((w) => card.disp[w.id] === "sent");
    const target = isReviewTarget(card);
    const btn = (action, cls, text) => `<button class="btn small ${cls}" data-action="${action}" data-write="${esc(card.rootId)}">${text}</button>`;
    if (uiDiscarded(card)) {
      return `<span class="badge red">discard</span><span class="note">${esc(cascadeText(R.cascade[card.rootId]))}</span><span class="spacer"></span>${btn("keep", "", "Keep")}`;
    }
    if (col === "not_started") return `<span class="badge">queued</span>`;
    if (col === "in_progress") return `<span class="badge">${S.applying ? "applying…" : "agent working…"}</span>`;
    if (col === "needs_approval") {
      if (card.simHold) return `<span class="badge">Tom approves (simulated)</span>`;
      const blocked = ms.filter((w) => card.disp[w.id] === "blocked").length;
      const what = `<span class="badge amber">held</span>${blocked ? `<span class="note">${blocked} waiting behind it</span>` : ""}${sent.length ? `<span class="note">${sent.length} sent</span>` : ""}`;
      if (target && r && r.status === "held" && !r.blocked_by.length) return `${what}<span class="spacer"></span>${btn("discard", "danger", "Discard")}`;
      if (runOf(card.run) && runOf(card.run).mode === "autopilot") return `${what}<span class="note">Tom is away</span>`;
      return what;
    }
    // complete
    if (r && (r.status === "discarded" || card.disp[r.id] === "discarded")) {
      return `<span class="badge red">discarded</span><span class="note">${esc(cascadeText(cascadeIds(card)))}</span>`;
    }
    const how = sent.length && sent.every((w) => w.decided_by === "layer" || w.status === "passed") ? "sent without review"
      : r && r.decided_by === "simulated" ? "Tom approves (simulated)" : r && r.status === "edited" ? "edited, approved" : "approved";
    const ids = sent.map((w) => w.result_id).filter(Boolean);
    return `<span class="badge green">${esc(how)} · ${sent.length} sent</span><span class="ids" title="${esc(ids.join(" "))}">${esc(ids.join(" "))}</span>`;
  }
  function chainHtml(card, col) {
    const ms = members(card);
    const ff = firstFlag(card);
    const title = chainTitle(card);
    const r = root(card);
    // a held card always says why: the flag, or the tool that is still checked
    const why = ff ? `<div class="flag"><span class="kind">${esc(ff.f.kind)}</span>${esc(ff.f.reason)}</div>`
      : col === "needs_approval" && r ? `<div class="why">${esc(r.tool)} · ${card.simHold && released(r.tool) ? "sent without review" : "still checked"}</div>` : "";
    return `
      <button class="open" data-action="open" aria-label="Details for ${esc(title)}"><span class="title">${esc(title)}</span><span class="amount">${esc(chainAmount(card))}</span></button>
      <div class="members">${ms.map((w) => memberChip(card, w, col)).join("")}</div>
      ${why}
      <div class="foot">${chainFoot(card, col)}<span class="tag">${esc(fri(card.run))}</span></div>`;
  }
  function ruleState(card) {
    const rule = card.rule;
    const accepted = R.rules.includes(rule.id) || rule.status === "active";
    const later = R.later.includes(rule.id);
    return { accepted, later, done: runDecided(card.run) };
  }
  function ruleDiff(card) {
    const rr = R.response && R.response.run.run === card.run ? R.response.run : runOf(card.run);
    const rule = card.rule;
    const src = rr && (rr.writes.find((w) => w.id === rule.derived_from) || rr.writes.find((w) => w.edited_args));
    const before = src ? String(src.args[rule.field] ?? "") : "";
    const after = src && src.edited_args ? String(src.edited_args[rule.field] ?? "") : "";
    let beforeHtml = esc(before);
    if (rule.op === "matches" && before) {
      // highlight what the correction took out: the sentence(s) that no longer appear in `after`
      const removed = before.split(/(?<=\.)\s*/).filter((sentence) => sentence && !after.includes(sentence.trim()));
      if (removed.length) removed.forEach((r) => { beforeHtml = beforeHtml.replace(esc(r.trim()), `<del>${esc(r.trim())}</del>`); });
      else { try { beforeHtml = esc(before).replace(new RegExp(rule.value, "g"), (m) => `<del>${m}</del>`); } catch (e) { /* keep plain */ } }
    }
    return { src, before, after, beforeHtml };
  }
  function ruleHtml(card) {
    const { src, beforeHtml } = ruleDiff(card);
    const rule = card.rule;
    const st = ruleState(card);
    const foot = st.accepted
      ? `<span class="badge green">Rule on — from the next action</span>`
      : st.done ? `<span class="badge">Not now — the edit still applied</span>`
      : st.later ? `<span class="badge">Not now — the edit still applies on Approve</span>`
      : `<button class="btn amber small" data-action="rule-accept">Yes always</button><button class="btn ghost small" data-action="rule-later">Not now</button>`;
    return `
      <button class="open" data-action="open" aria-label="Details for the proposed rule"><span class="title">${esc(src ? summary(src) : rule.tool)} — edited</span><span class="tag">${esc(rule.tool)} · ${esc(rule.field)}</span></button>
      <div class="diff"><div class="side before"><span class="lab">Tom's edit</span>${beforeHtml}</div></div>
      <div class="rule-q">Hold every <b>${esc(rule.tool)}</b> whose <b>${esc(rule.field)}</b> contains ${esc(rule.label)}?</div>
      <div class="foot">${foot}<span class="tag">${esc(fri(card.run))}</span></div>`;
  }
  function queuedHtml(card) {
    return `<div class="open"><span class="title">${esc(label())} ${card.run}${card.running ? " · agent running" : ""}</span><span class="modetag">${esc(modeTag(card.run))}</span></div>`;
  }
  function cardSig(card, col) {
    if (card.kind === "chain") return `${col}|${members(card).map((w) => memberDisp(card, w) + w.status + (w.result_id || "")).join(",")}|${card.simHold}|${uiDiscarded(card)}|${(R.cascade[card.rootId] || []).length}|${isReviewTarget(card)}|${S.applying}`;
    if (card.kind === "rule") return `${col}|${JSON.stringify(ruleState(card))}`;
    return `${col}|${card.running}`;
  }
  function ensureEl(card) {
    if (card.el) return card.el;
    const node = el(`<article class="card enter" data-card="${esc(card.key)}" data-kind="${card.kind}" data-run="${card.run}"></article>`);
    setTimeout(() => node.classList.remove("enter"), 400); // by timer: a card moved mid-fade never gets animationend
    node.addEventListener("click", (e) => onCardClick(card, e));
    card.el = node;
    return node;
  }
  function patchCard(card, col) {
    const node = ensureEl(card);
    const sig = cardSig(card, col);
    if (sig === card.sig) return node;
    card.sig = sig;
    node.innerHTML = card.kind === "chain" ? chainHtml(card, col) : card.kind === "rule" ? ruleHtml(card) : queuedHtml(card);
    node.classList.toggle("flagged", card.kind === "chain" && flagged(card));
    node.classList.toggle("discarded", card.kind === "chain" && (uiDiscarded(card) || (root(card) && root(card).status === "discarded")));
    node.classList.toggle("running", card.kind === "queued" && card.running);
    if (S.opened === card.key && dlg.open) fillDialog(card);
    return node;
  }

  // ------------------------------------------------------------------ the board: reconcile the DOM against the registry, move with FLIP
  const ghosts = new Map(); // key -> {ghost, timer}
  function boardMounted() { return !!$("board"); }
  function renderBoard(animate = true) {
    if (!boardMounted()) return;
    const byCol = { not_started: [], in_progress: [], needs_approval: [], complete: [] };
    for (const card of S.cards.values()) byCol[cardColumn(card)].push(card);
    for (const col of COLS) byCol[col].sort((a, b) => cmp(orderKey(a, col), orderKey(b, col)));
    // 1. snapshot the visual rects: a card already in flight starts its next move from where its ghost is now
    const before = new Map();
    if (animate && !REDUCED) for (const card of S.cards.values()) {
      const g = ghosts.get(card.key);
      if (g) before.set(card.key, g.ghost.getBoundingClientRect());
      else if (card.el && card.el.isConnected) before.set(card.key, card.el.getBoundingClientRect());
    }
    const moved = [];
    const expanded = new Set(nextPhaseRuns());
    // 2. patch + place
    for (const col of COLS) {
      const section = main.querySelector(`section.col[data-col="${col}"]`);
      const body = section.querySelector(".col-body");
      const cards = byCol[col];
      const nodes = [];
      let lastRun = null, hidden = 0;
      for (const card of cards) {
        if (card.kind === "queued" && !expanded.has(card.run)) { hidden++; continue; }
        if (col === "complete" && card.kind === "chain" && card.run !== lastRun) {
          lastRun = card.run;
          const rr = runOf(card.run);
          const n = rr ? rr.writes.filter((w) => w.sent).length : 0;
          const d = rr ? rr.writes.filter((w) => w.status === "discarded").length : 0;
          nodes.push(el(`<div class="group" data-group="${card.run}"><span>${esc(label())} ${card.run}</span><span class="g-n">${n} sent${d ? ` · ${d} discarded` : ""}</span></div>`));
        }
        const node = patchCard(card, col);
        if (card.col !== col) moved.push({ card, from: card.col, to: col });
        card.col = col;
        nodes.push(node);
      }
      if (hidden) nodes.push(el(`<div class="more">${hidden} more ${label()}${hidden === 1 ? "" : "s"}</div>`));
      if (!cards.length) nodes.push(el(`<div class="empty">${col === "in_progress" ? "Nothing running" : col === "needs_approval" ? "Nothing waiting on a person" : col === "complete" ? "Nothing has reached a system" : "Nothing queued"}</div>`));
      // drop stale separators and text rows; keep card nodes where they are; insert only what moved
      for (const child of [...body.children]) {
        if (child.classList.contains("card") && child.classList.contains("leaving")) continue;
        if (!child.classList.contains("card") || !nodes.includes(child)) child.remove();
      }
      nodes.forEach((node, i) => { if (body.children[i] !== node) body.insertBefore(node, body.children[i] || null); });
      const n = cards.filter((c) => c.kind !== "queued").length;
      const pill = section.querySelector(".count");
      pill.textContent = n; pill.classList.toggle("zero", !n);
    }
    renderApprovalHead();
    renderColnav(byCol);
    // 3. FLIP: cross-column moves fly a ghost above the board (columns clip their own overflow); in-column shifts animate in place
    if (animate && !REDUCED) {
      const narrow = NARROW();
      for (const { card, from, to } of moved) {
        if (from && card.el.isConnected && before.has(card.key) && !narrow) {
          revealInColumn(card.el);
          flyGhost(card, before.get(card.key), card.el.getBoundingClientRect(), to);
        } else if (to === "needs_approval") land(card.el);
      }
      for (const card of S.cards.values()) {
        if (!card.el || !card.el.isConnected || !before.has(card.key) || ghosts.has(card.key)) continue;
        const a = before.get(card.key), b = card.el.getBoundingClientRect();
        const dx = a.left - b.left, dy = a.top - b.top;
        if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue;
        card.el.getAnimations().forEach((an) => { if (an.id === "flip") an.cancel(); });
        card.el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], { id: "flip", duration: MOVE_MS, easing: EASE });
      }
    }
  }
  // scroll only the column body, never the page or the board: a replay must not fight a swipe on a phone
  function revealInColumn(node) {
    const body = node.closest(".col-body"); if (!body) return;
    const top = node.offsetTop - body.offsetTop, bottom = top + node.offsetHeight;
    if (top < body.scrollTop) body.scrollTo({ top, behavior: "instant" });
    else if (bottom > body.scrollTop + body.clientHeight) body.scrollTo({ top: bottom - body.clientHeight, behavior: "instant" });
  }
  function flyGhost(card, from, to, col) {
    cancelGhost(card.key);
    const node = card.el;
    const ghost = node.cloneNode(true);
    ghost.classList.remove("enter");
    ghost.classList.add("ghost");
    Object.assign(ghost.style, { left: `${from.left}px`, top: `${from.top}px`, width: `${from.width}px`, height: `${from.height}px`, visibility: "visible" });
    let layer = $("ghosts");
    if (!layer) { layer = el(`<div id="ghosts" aria-hidden="true"></div>`); document.body.appendChild(layer); }
    layer.appendChild(ghost);
    node.style.visibility = "hidden";
    ghost.animate(
      [{ transform: "none", width: `${from.width}px`, height: `${from.height}px` }, { transform: `translate(${to.left - from.left}px, ${to.top - from.top}px)`, width: `${to.width}px`, height: `${to.height}px` }],
      { duration: MOVE_MS, easing: EASE, fill: "forwards" },
    );
    const finish = () => {
      if (!ghosts.has(card.key) || ghosts.get(card.key).ghost !== ghost) return;
      ghosts.delete(card.key);
      ghost.remove();
      node.style.visibility = "";
      if (col === "needs_approval") land(node);
    };
    const timer = setTimeout(finish, MOVE_MS + 40);
    ghosts.set(card.key, { ghost, timer, finish });
  }
  function cancelGhost(key) {
    const g = ghosts.get(key);
    if (!g) return;
    clearTimeout(g.timer); ghosts.delete(key); g.ghost.remove();
    const card = S.cards.get(key); if (card && card.el) card.el.style.visibility = "";
  }
  // one attention colour: the amber pulse marks a hold landing, nothing else pulses
  function land(node) {
    if (REDUCED || !node) return;
    node.classList.remove("land-amber");
    void node.offsetWidth;
    node.classList.add("land-amber");
    setTimeout(() => node.classList.remove("land-amber"), 800);
  }

  // the approval column's header: the review target's summary, its banner, and Approve
  function renderApprovalHead() {
    const section = main.querySelector(`section.col[data-col="needs_approval"]`);
    if (!section) return;
    const head = section.querySelector(".col-head");
    const sum = head.querySelector(".sum"), act = head.querySelector(".act"), banner = head.querySelector(".banner");
    const run = reviewRun();
    const rr = R.response ? R.response.run : runOf(run);
    const undecided = rr && !rr.decided && rr.mode !== "autopilot" && rr.mode !== "auto";
    const text = S.colBanner || R.banner || "";
    banner.textContent = text; banner.hidden = !text;
    if (undecided) {
      const cs = chains(rr);
      const fl = cs.filter((c) => c.root.flags.length).length;
      sum.innerHTML = `${esc(label())} ${rr.run}: <b>${cs.length}</b> chains · <b>${rr.writes.length}</b> writes held · <b class="amber">${fl}</b> flagged · <b>${cs.length - fl}</b> still checked`;
      sum.hidden = false;
      act.innerHTML = `<button class="btn primary small" data-action="approve">Approve</button>`;
      act.querySelector("[data-action='approve']").onclick = approve;
    } else if (rr && rr.decided && S.applying !== undefined) {
      sum.innerHTML = S.applying === null ? `<span class="green">Approved · ${rr.effects.length} writes landed</span>` : `<span class="muted">Applying in dependency order…</span>`;
      sum.hidden = false; act.innerHTML = "";
    } else {
      sum.hidden = true; sum.innerHTML = ""; act.innerHTML = "";
    }
  }
  function renderColnav(byCol) {
    const nav = $("colnav"); if (!nav) return;
    nav.innerHTML = COLS.map((col) => { const n = byCol[col].filter((c) => c.kind !== "queued").length; return `<button class="btn ${col === "needs_approval" && n ? "amber-n" : ""}" data-col-nav="${col}"><span class="n">${n}</span>${esc(COL_TITLE[col].replace("Needs human approval", "Needs approval"))}</button>`; }).join("");
    nav.querySelectorAll("[data-col-nav]").forEach((b) => { b.onclick = () => scrollToCol(b.dataset.colNav); });
  }
  function scrollToCol(col, flash = true) {
    const section = main.querySelector(`section.col[data-col="${col}"]`); if (!section) return;
    if (NARROW()) $("board").scrollTo({ left: section.offsetLeft - $("board").offsetLeft, behavior: REDUCED ? "instant" : "smooth" });
    if (flash) { section.classList.remove("flash"); void section.offsetWidth; section.classList.add("flash"); }
  }

  // ------------------------------------------------------------------ the strips above the board
  function phaseFor(view) {
    const runs = Object.values(view.runs);
    if (!runs.length) return { name: "", mode: "review", totals: zeroCounts() };
    const last = runs.reduce((a, b) => (a.run > b.run ? a : b));
    const mode = last.mode;
    const same = runs.filter((r) => r.mode === mode);
    const t = zeroCounts();
    for (const r of same) addCounts(t, r);
    return { name: phaseName(mode, last.run), mode, totals: t };
  }
  function phaseName(mode, run) {
    return mode === "autopilot" ? "Autopilot · Tom is away" : mode === "auto" ? `Play 5 ${label()}s · Tom approves (simulated)` : mode === "live" ? "Live" : `Review · ${label()} ${run}`;
  }
  function addCounts(t, rr) {
    const c = rr.counts;
    t.fridays += 1; t.checked += c.checked; t.through += c.through; t.held += c.held; t.caught += c.caught; t.wrongly_held += c.wrongly_held; t.volume += c.volume;
    t.anomalies += S.view.anomaly_runs.filter((x) => x === rr.run).length;
  }
  function setHero(run, rr, running) {
    const effects = S.view.systems.reduce((n, s) => n + s.count, 0);
    S.hero = running
      ? { label: `${label()} ${run}`, line: "the agent is running…", running: true, after: "" }
      : { label: `The agent's last line, ${label()} ${run}`, line: rr ? rr.agent_text : "…", running: false,
          after: rr ? `<b>${rr.counts.checked}</b> writes checked · <b>${rr.counts.through}</b> sent · <b>${rr.counts.held + rr.counts.blocked}</b> held · <b>${effects}</b> reached a system` : "" };
    renderStrip();
  }
  function renderStrip() {
    const h = $("hero"); if (!h) return;
    h.innerHTML = `<div class="label">${esc(S.hero.label)}</div><p class="line ${S.hero.running ? "running" : ""}">${esc(S.hero.line)}</p><div class="after">${S.hero.after}</div>`;
    const t = S.phase.totals;
    const set = (k, v) => { const n = main.querySelector(`[data-counter="${k}"]`); if (n) n.textContent = v; };
    set("fridays", t.fridays); set("checked", t.checked); set("through", t.through); set("held", t.held); set("volume", money0(t.volume));
    const sc = $("score");
    if (sc) sc.innerHTML = `caught <span class="${t.caught >= t.anomalies ? "ok" : "bad"}">${t.caught}/${t.anomalies}</span> · wrongly held <span class="${t.wrongly_held ? "bad" : "ok"}">${t.wrongly_held}</span>`;
    const ph = main.querySelector("#counters .phase"); if (ph) ph.textContent = S.phase.name;
    const counters = $("counters"); if (counters) counters.classList.toggle("no-score", S.phase.mode === "auto"); // the montage's simulated approvals are not a scoreboard
    const strip = main.querySelector(".strip"); if (strip) strip.classList.toggle("opening", S.screen === "opening");
  }
  function learnEvents(learned, run) {
    return learned.events.filter((e) => (run === undefined || e.run === run) && !(e.kind === "envelope" && REF_TOKEN.test(e.text)));
  }
  function latestHtml(e) {
    return `<span class="latest ${esc(e.kind)}" title="${esc(e.text)}">${esc(fri(e.run))} · ${esc(e.kind === "promotion" ? e.text.replace(/\s*\(.*\)$/, "") : e.text)}</span>`;
  }
  function renderLearnedBar() {
    const bar = $("learned-bar"); if (!bar) return;
    const learned = S.view.learned;
    const rel = learned.ladder.filter((l) => l.level === "released");
    const rules = learned.rules.filter((r) => r.status === "active");
    const events = learnEvents(learned);
    const last = S.latest || events[events.length - 1];
    const chips = [
      ...rel.map((l) => `<span class="chip released" title="${l.approved} approved">${esc(l.tool)} · sent without review${l.released_run ? ` since ${esc(fri(l.released_run))}` : ""}</span>`),
      ...rules.map((r) => `<span class="chip held">rule: ${esc(r.tool)}.${esc(r.field)} ${esc(r.label)}</span>`),
    ];
    const open = !!$("rule-slot") && !!$("rule-slot").innerHTML;
    bar.innerHTML = `<span class="lb-title">Learned</span>${chips.join("") || `<span class="empty">nothing yet — it learns from what Tom approves and corrects</span>`}${last ? latestHtml(last) : ""}<button class="btn ghost small" id="b-rule">${open ? "Close" : "Add a rule"}</button>`;
    $("b-rule").onclick = () => {
      const slot = $("rule-slot");
      if (slot.innerHTML) { slot.innerHTML = ""; renderLearnedBar(); return; }
      slot.innerHTML = ruleForm();
      renderLearnedBar();
      bindRuleForm((res) => { S.view.learned = res; renderLearnedBar(); if ($("learned-events")) fillLearned(res); });
    };
  }
  function showLatest(e) {
    S.latest = e;
    const bar = $("learned-bar"); if (!bar) return;
    const old = bar.querySelector(".latest");
    const node = el(latestHtml(e));
    if (old) old.replaceWith(node); else bar.querySelector("#b-rule").before(node);
  }
  // the learned panel beside the board while Play 5 Fridays runs (BUILD_PLAN §1: "What it has learned fills")
  function setRail(on) {
    S.rail = on;
    const board = $("board"); if (!board) return;
    let rail = $("rail");
    if (on && !rail) { rail = el(`<aside id="rail">${learnedPanel()}</aside>`); board.appendChild(rail); fillLearned(S.view.learned); bindRuleForm((res) => { S.view.learned = res; fillLearned(res); renderLearnedBar(); }); }
    if (!on && rail) rail.remove();
    board.classList.toggle("with-rail", on);
  }

  // ------------------------------------------------------------------ header
  function renderHeader() {
    const v = S.view;
    $("sub").textContent = v ? `${v.scenario} · ${label()} ${v.current_run}` : "";
    const run1 = v && runOf(firstReviewRun());
    const held = run1 && !run1.decided ? run1.writes.filter((w) => w.status === "held").length : 0;
    $("b-review").innerHTML = `Review${held ? `<span class="count">${held}</span>` : ""}`;
    const replaying = S.montage.running || S.auto.running;
    $("b-board").disabled = !v || S.busy || replaying;
    $("b-review").disabled = !run1 || S.busy || replaying;
    // one replay at a time: the server plays Fridays in order, so the two long buttons exclude each other
    $("b-montage").disabled = !v || S.busy || replaying;
    $("b-auto").disabled = !v || S.busy || replaying;
    $("b-learn").disabled = !v || S.busy || replaying;
    $("b-reset").disabled = !v || S.busy || replaying;
    $("b-board").classList.toggle("active", S.screen === "opening");
    for (const [id, sc] of [["b-review", "review"], ["b-montage", "montage"], ["b-auto", "autopilot"], ["b-learn", "learning"]]) {
      $(id).classList.toggle("active", S.screen === sc);
    }
    // "Run live" exists only when the service has a model AND the page was opened with ?live=1 (§1.1's opt-in),
    // so the deployed demo URL keeps exactly three buttons + Reset even with PAKKA_MODEL in the Modal secret
    const liveOptIn = new URLSearchParams(location.search).has("live");
    if (v && v.live_available && liveOptIn && !$("b-live")) {
      const b = el(`<button class="btn ghost" id="b-live" data-action="live">Run live</button>`);
      b.onclick = () => runLive();
      $("b-reset").before(b);
    }
    const live = $("b-live");
    if (live) { live.disabled = S.busy || replaying; live.textContent = S.liveRunning ? "Running…" : "Run live"; }
    const tag = v ? `transcripts: ${v.transcripts_tag}${v.live_available ? (liveOptIn ? " · live model available" : " · live model available (?live=1)") : ""}` : "";
    $("foot-note").textContent = tag;
  }
  function notice(msg) {
    const old = main.querySelector(".notice"); if (old) old.remove();
    main.prepend(el(`<div class="notice amber" role="alert">${esc(msg)}</div>`));
  }

  // ------------------------------------------------------------------ a typed rule (Q&A): hold <tool> when <field> <op> <value>
  const OPS = [["matches", "matches"], ["in", "in"], ["not_in", "not in"], ["gt", ">"], ["lt", "<"]];
  function ruleForm() {
    return `
      <form class="rule-form" autocomplete="off">
        <span class="lab">Add a rule · hold</span>
        <select name="tool" aria-label="tool"><option value="">tool…</option></select>
        <span class="muted">when</span>
        <select name="field" aria-label="field"></select>
        <select name="op" aria-label="op">${OPS.map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}</select>
        <input name="value" placeholder="value" aria-label="value">
        <button class="btn small" type="submit">Add</button>
        <div class="rule-err amber" hidden></div>
      </form>`;
  }
  function ruleValue(op, raw) {
    const s = raw.trim();
    if (op === "gt" || op === "lt") return s !== "" && !isNaN(Number(s)) ? Number(s) : s;
    if (op === "in" || op === "not_in") return s.split(",").map((x) => x.trim()).filter(Boolean);
    return s;
  }
  async function bindRuleForm(onAdded) {
    const forms = [...main.querySelectorAll("form.rule-form")].filter((f) => !f.dataset.bound);
    if (!forms.length) return;
    if (!S.scenario) { try { S.scenario = await api("GET", "/scenario"); } catch (e) { console.error(e); return; } }
    for (const form of forms) {
      if (!document.body.contains(form)) continue;
      form.dataset.bound = "1";
      const tool = form.elements.tool, field = form.elements.field, op = form.elements.op, value = form.elements.value, err = form.querySelector(".rule-err");
      const tools = S.scenario.tools.filter((t) => t.kind === "write");
      tool.innerHTML = tools.map((t) => `<option value="${esc(t.name)}">${esc(t.name)}</option>`).join("");
      const fillFields = () => {
        const t = tools.find((x) => x.name === tool.value);
        const names = t ? Object.keys((t.args_schema && t.args_schema.properties) || {}) : [];
        field.innerHTML = names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
      };
      fillFields();
      tool.onchange = fillFields;
      form.onsubmit = async (ev) => {
        ev.preventDefault();
        err.hidden = true;
        const req = { tool: tool.value, field: field.value, op: op.value, value: ruleValue(op.value, value.value) };
        let res;
        try { res = await api("POST", "/rules", req); }
        catch (e) { err.textContent = e.detail || e.message; err.hidden = false; return; }
        S.view.learned = res;
        value.value = "";
        if (onAdded) onAdded(res);
      };
    }
  }

  // ------------------------------------------------------------------ the board screen
  function renderBoardScreen() {
    main.innerHTML = `
      <div class="strip">
        <div id="hero" aria-live="polite"></div>
        <div id="counters">
          ${counter("fridays", `${label()}s`)}${counter("checked", "actions checked")}${counter("through", "through", "through")}${counter("held", "held", "held")}${counter("volume", "moved")}
          <div class="counter score"><div class="n" id="score"></div><div class="phase"></div></div>
        </div>
      </div>
      <div id="learned-bar"></div>
      <div id="rule-slot"></div>
      <div id="colnav"></div>
      <div id="board">
        ${COLS.map((col) => `<section class="col" data-col="${col}"><div class="col-head"><h2>${esc(COL_TITLE[col])}</h2><span class="count" aria-live="off">0</span><div class="act"></div><div class="banner" hidden></div><div class="sum" hidden></div></div><div class="col-body"></div></section>`).join("")}
      </div>`;
    renderStrip();
    renderLearnedBar();
    renderBoard(false);
    if (S.rail) { S.rail = false; setRail(true); }
    renderHeader();
    if (NARROW()) scrollToCol("needs_approval", false);
  }
  function counter(key, lab, cls) { return `<div class="counter ${cls || ""}"><div class="n" data-counter="${key}">0</div><div class="l">${esc(lab)}</div></div>`; }
  function showBoard() {
    if (!boardMounted()) renderBoardScreen();
  }

  // ------------------------------------------------------------------ clicks on a card
  function onCardClick(card, e) {
    const b = e.target.closest("[data-action]");
    if (b && card.el.contains(b)) {
      const a = b.dataset.action;
      if (a === "open") { openCard(card.key, b); return; }
      e.stopPropagation();
      act(card, a);
      return;
    }
    if (card.kind !== "queued") openCard(card.key, card.el.querySelector(".open"));
  }
  function act(card, a) {
    if (a === "discard") discard(card.rootId);
    else if (a === "keep") { R.discards = R.discards.filter((x) => x !== card.rootId); renderBoard(); }
    else if (a === "rule-accept") { if (!R.rules.includes(card.rule.id)) R.rules.push(card.rule.id); R.later = R.later.filter((x) => x !== card.rule.id); renderBoard(); }
    else if (a === "rule-later") { if (!R.later.includes(card.rule.id)) R.later.push(card.rule.id); renderBoard(); }
  }

  async function discard(writeId) {
    const run = reviewRun();
    const rv = R;
    if (!rv.discards.includes(writeId)) rv.discards.push(writeId);
    renderBoard();
    try {
      const res = await api("GET", `/cascade/${run}/${encodeURIComponent(writeId)}`);
      rv.cascade[writeId] = res.skipped;
    } catch (e) {
      console.error(e);
      rv.cascade[writeId] = [];
    }
    if (R === rv) renderBoard();
  }

  async function approve() {
    if (S.busy) return;
    const rv = R;
    const run = reviewRun();
    const req = {
      run,
      decisions: rv.discards.map((id) => ({ write_id: id, action: "discard" })),
      accept_rules: rv.rules.slice(),
      approve_rest: true,
      decided_by: "person",
    };
    S.busy = true; renderHeader();
    const btn = main.querySelector("[data-action='approve']"); if (btn) { btn.disabled = true; btn.textContent = "Applying…"; }
    let res;
    try {
      res = await api("POST", "/decide", req);
    } catch (e) {
      console.error(e);
      S.busy = false; renderHeader();
      if (btn) { btn.disabled = false; btn.textContent = "Approve"; }
      notice(e.detail || e.message);
      return;
    }
    rv.response = res;
    S.view.runs[String(run)] = res.run;
    S.view.scoreboard = res.scoreboard;
    S.view.learned = res.learned;
    S.busy = false;
    S.applying = true;
    if (S.screen === "opening") setScreen("review");
    // discarded chains fall out first; the rest goes to work and lands in dependency order with real ids where the placeholders were
    const cards = [...S.cards.values()].filter((c) => c.kind === "chain" && c.run === run);
    for (const card of cards) for (const w of members(card)) {
      if (w.status === "discarded") card.disp[w.id] = "discarded";
      else if (w.status === "skipped") card.disp[w.id] = "skipped";
    }
    renderBoard();
    await sleep(REDUCED ? 0 : 260);
    for (const card of cards) for (const w of members(card)) if (w.status !== "discarded" && w.status !== "skipped") card.disp[w.id] = "active";
    renderBoard();
    await sleep(REDUCED ? 0 : 300);
    for (const e of res.run.effects) {
      const w = res.run.writes.find((x) => x.result_id === e.result_id && x.tool === e.tool);
      if (w) {
        const card = cards.find((c) => c.ids.includes(w.id));
        if (card) { card.disp[w.id] = "sent"; renderBoard(); }
      }
      await sleep(120);
    }
    for (const card of cards) for (const w of members(card)) card.disp[w.id] = serverDisp(w);
    S.view.systems = S.view.systems.map((s) => ({ ...s, count: s.count + res.run.effects.filter((e) => e.system === s.name).length }));
    S.applying = null;
    S.phase = phaseFor(S.view);
    setHero(run, res.run, false);
    renderLearnedBar();
    renderBoard();
    renderHeader();
  }

  // a live run (Q&A): the real agent on the next run, reviewed on the board like the replay
  async function runLive() {
    if (S.busy || S.liveRunning) return;
    S.busy = true; S.liveRunning = true; renderHeader();
    showBoard();
    const next = S.view.current_run + 1;
    const q = makeQueuedCard(next); q.running = true; renderBoard();
    setHero(next, null, true);
    let res;
    try {
      res = await api("POST", "/live", {});
    } catch (e) {
      S.busy = false; S.liveRunning = false; q.running = false; renderBoard(); renderHeader();
      notice(e.detail || e.message); // a 400 (no model, or the model could not be built) is one amber line
      return;
    }
    S.busy = false; S.liveRunning = false;
    const v = S.view;
    v.runs[String(res.run.run)] = res.run; v.learned = res.learned; v.scoreboard = res.scoreboard; v.current_run = res.run.run;
    S.live = freshReview(res.run.run, `Live: ${res.run.model}`);
    R = S.live;
    S.applying = undefined;
    setScreen("review");
    S.phase = { name: "Live", mode: "live", totals: zeroCounts() };
    await walkRun(res.run, "review", 2400);
    addCounts(S.phase.totals, res.run);
    syncRuleCard();
    setHero(res.run.run, res.run, false);
    renderLearnedBar(); renderBoard(); renderHeader();
  }

  // ------------------------------------------------------------------ replaying a run on the board, one write at a time
  async function walkRun(rr, mode, budget, events) {
    const run = rr.run;
    dropCard(`queued:${run}`);
    const cs = chains(rr).sort((a, b) => a.root.seq - b.root.seq);
    const cards = cs.map((c) => makeChainCard(rr, c, "pending"));
    renderBoard();
    const ws = rr.writes.slice().sort((a, b) => a.seq - b.seq);
    const dwell = REDUCED ? 0 : 300; // "N tasks appear" reads before "tasks move"
    const sweep = mode === "montage" ? cards.length * 40 + 200 : 0; // the montage's end-of-Friday sweep is paid for up front
    const step = Math.max(50, Math.min(220, Math.floor((budget - 300 - dwell - sweep) / Math.max(1, ws.length))));
    const evs = (events || []).slice();
    await sleep(dwell);
    for (const w of ws) {
      const card = cards.find((c) => c.ids.includes(w.id));
      if (!card) continue;
      // in a Play 5 run the layer held everything a person still checks and a simulated Tom approved it in the same
      // request: show the hold, then sweep the run to Complete at the end. Autopilot and live runs show the truth at once.
      if (mode === "montage" && w.decided_by === "simulated") { card.disp[w.id] = w.blocked_by.length ? "blocked" : "held"; card.simHold = true; }
      else card.disp[w.id] = serverDisp(w);
      const next = card.ids.find((id) => card.disp[id] === "pending");
      if (next) card.disp[next] = "active";
      if (evs.length) showLatest(evs.shift());
      renderBoard();
      await sleep(step);
    }
    for (const card of cards) for (const id of card.ids) if (card.disp[id] === "active") card.disp[id] = "pending";
    while (evs.length) showLatest(evs.shift());
    if (mode === "montage") {
      S.colBanner = `${label()} ${run} approved · ${rr.counts.through} sent`;
      renderApprovalHead();
      for (const card of cards) {
        if (!card.simHold) continue;
        card.simHold = false;
        for (const w of members(card)) card.disp[w.id] = serverDisp(w);
        renderBoard();
        await sleep(REDUCED ? 0 : 40);
      }
    }
    for (const card of cards) for (const w of members(card)) card.disp[w.id] = serverDisp(w);
    renderBoard();
  }

  async function playRuns(todo, mode) {
    const v = S.view;
    const perFriday = mode === "montage" ? Math.min(2000, Math.floor(12000 / todo.length)) : 2400; // ten autopilot runs in about 24s; the holds land near 4s, 9s, 14s and 19s
    const results = todo.map(() => null);
    const waiters = [];
    const promise = (async () => {
      for (let i = 0; i < todo.length; i++) {
        try {
          results[i] = mode === "montage" ? await api("POST", `/run/${todo[i]}`, { auto_approve: true }) : await api("POST", `/autopilot/${todo[i]}`);
        } catch (e) { console.error(e); results[i] = { error: e.detail || e.message }; }
        if (waiters[i]) waiters[i]();
      }
    })();
    for (let i = 0; i < todo.length; i++) {
      const started = Date.now();
      const f = todo[i];
      const q = makeQueuedCard(f); q.running = true; renderBoard();
      setHero(f, null, true);
      if (mode === "montage") { S.colBanner = "Tom approves (simulated)"; renderApprovalHead(); }
      if (!results[i]) await new Promise((res) => { waiters[i] = res; if (results[i]) res(); });
      const r = results[i];
      if (r.error) { dropCard(`queued:${f}`); notice(`${label()} ${f}: ${r.error}`); renderBoard(); continue; }
      v.runs[String(f)] = r.run; v.scoreboard = r.scoreboard; v.learned = r.learned; v.current_run = f;
      setHero(f, r.run, false);
      await walkRun(r.run, mode, perFriday, learnEvents(r.learned, f));
      addCounts(S.phase.totals, r.run);
      v.systems = v.systems.map((s) => ({ ...s, count: s.count + r.run.effects.filter((e) => e.system === s.name).length }));
      setHero(f, r.run, false);
      renderLearnedBar();
      if ($("learned-events")) fillLearned(r.learned);
      renderHeader();
      const remaining = perFriday - (Date.now() - started);
      if (remaining > 0) await sleep(remaining);
    }
    await promise;
  }

  async function startMontage() {
    if (S.montage.running || S.auto.running || S.busy) return;
    const v = S.view;
    showBoard();
    const todo = v.montage_runs.filter((f) => !(runOf(f) && runOf(f).decided));
    if (!todo.length) { notice(`Those ${label()}s have already been played. Reset to play them again.`); return; }
    S.montage.running = true;
    setScreen("montage");
    S.applying = undefined; // the review's "Approved · n landed" line belongs to the review
    S.phase = { name: phaseName("auto"), mode: "auto", totals: zeroCounts() };
    setRail(true);
    renderStrip(); renderHeader();
    await playRuns(todo, "montage");
    S.colBanner = ""; renderApprovalHead();
    S.montage.running = false; S.montage.done = true;
    renderHeader();
  }

  async function startAutopilot() {
    if (S.auto.running || S.montage.running || S.busy) return;
    const v = S.view;
    showBoard();
    const played = new Set(Object.keys(v.runs).map(Number));
    let todo = v.autopilot_runs.filter((f) => !played.has(f));
    if (!todo.length) {
      const last = Math.max(...v.autopilot_runs, ...played);
      todo = [];
      for (let f = last + 1; f <= v.total_runs && todo.length < 10; f++) if (!played.has(f)) todo.push(f);
    }
    if (!todo.length) { notice(`Every ${label()} has been played — Reset to start over.`); return; }
    S.auto.running = true;
    setScreen("autopilot");
    setRail(false);
    S.colBanner = ""; S.applying = undefined;
    if (S.phase.mode !== "autopilot") S.phase = { name: phaseName("autopilot"), mode: "autopilot", totals: zeroCounts() };
    renderStrip(); renderHeader();
    await playRuns(todo, "autopilot");
    S.auto.running = false;
    renderHeader();
  }

  // ------------------------------------------------------------------ the popup
  function hlPh(json) { return esc(json).replace(PH_RE, (m) => `<span class="ph">${m}</span>`); }
  function hlIds(json, ids) { let out = esc(json); for (const id of ids) out = out.split(esc(id)).join(`<span class="real">${esc(id)}</span>`); return out; }
  function flagDetail(f) {
    const bits = [];
    if (f.kind === "grounding") { if (f.entity) bits.push(`entity <code>${esc(f.entity)}</code>`); bits.push(`${esc(f.field)} <code>${esc(f.value)}</code>`); if (f.conflicts && f.conflicts.length) bits.push(`on record: ${f.conflicts.map((c) => `<code>${esc(c)}</code>`).join(", ")}`); }
    if (f.kind === "envelope") { if (f.entity) bits.push(`entity <code>${esc(f.entity)}</code>`); if (f.field) bits.push(`${esc(f.field)}${f.value ? ` <code>${esc(f.value)}</code>` : ""}`); if (f.bound) bits.push(`bound <code>${esc(f.bound)}</code>`); if (f.ratio) bits.push(`ratio ${esc(f.ratio)}×`); bits.push(`scope ${esc(f.scope)} · ${esc(f.detail)}`); }
    if (f.kind === "rule") bits.push(`rule <code>${esc(f.rule_id)}</code> · ${esc(f.field)} · from ${esc(fri(f.created_run))}`);
    if (f.kind === "memory") { bits.push(`<code>${esc(f.value)}</code> · ${esc(f.detail)}`); if (f.first_run) bits.push(`first on ${esc(fri(f.first_run))}`); }
    return bits.join(" · ");
  }
  // the read that supplied a grounding flag's on-record value: "the agent read both"
  function readFor(rr, f) {
    if (!rr || f.kind !== "grounding" || !f.conflicts || !f.conflicts.length) return "";
    for (const rd of rr.reads) {
      const text = JSON.stringify(rd.result);
      const hit = f.conflicts.find((c) => text.includes(c));
      if (hit) return `<span class="detail">read #${rd.seq} <code>${esc(rd.tool)}</code> returned <code>${esc(hit)}</code>${f.entity ? ` for ${esc(f.entity)}` : ""} earlier in this ${esc(label().toLowerCase())}</span>`;
    }
    return "";
  }
  function runContext(rr) {
    if (!rr) return "";
    if (rr.mode === "autopilot") return "autopilot · Tom is away";
    if (rr.mode === "auto") return "Tom approves (simulated)";
    if (rr.mode === "live") return `live · ${rr.model}`;
    return rr.decided ? "reviewed by Tom" : "waiting for Tom";
  }
  function statusClass(d) { return d === "sent" ? "sent" : d === "held" || d === "blocked" ? "held" : d === "discarded" || d === "skipped" || d === "will-skip" ? "red" : ""; }
  function fillDialog(card) {
    if (card.kind === "rule") { fillRuleDialog(card); return; }
    const ms = members(card), r = root(card);
    const rr = runOf(card.run);
    const col = cardColumn(card);
    const byPh = {}; ms.forEach((w) => { byPh[w.placeholder] = w; });
    const flagsHtml = ms.flatMap((w) => w.flags.map((f) => `<div class="flagline"><span class="kind">${esc(f.kind)}</span>${esc(f.reason)}<span class="detail">${esc(w.tool)} · ${flagDetail(f)}</span>${readFor(rr, f)}</div>`)).join("");
    const chainHtml2 = ms.map((w) => {
      const d = memberDisp(card, w);
      const st = d === "sent" ? w.result_id : d === "pending" ? "not yet attempted" : d === "active" ? (S.applying ? "applying" : "attempting") : d === "blocked" ? "held behind its dependency" : d === "will-skip" ? "will be skipped" : d;
      const by = w.decided_by ? `decided by ${esc(w.decided_by)} · ${esc(w.status)}` : `status ${esc(w.status)}`;
      const finalArgs = w.final_args && JSON.stringify(w.final_args) !== JSON.stringify(args(w)) ? `<pre>${hlIds(JSON.stringify(w.final_args, null, 2), ms.map((x) => x.result_id).filter(Boolean))}</pre><div class="by">sent with the real ids substituted for the placeholders</div>` : "";
      const edited = w.edited_args ? `<div class="diff"><div class="side before"><span class="lab">as proposed</span>${hlPh(JSON.stringify(w.args, null, 2))}</div><div class="side after"><span class="lab">as edited</span>${hlPh(JSON.stringify(w.edited_args, null, 2))}</div></div>` : `<pre>${hlPh(JSON.stringify(w.args, null, 2))}</pre>`;
      return `<div class="w"><div class="wh"><span class="tool">${esc(w.tool)}</span><span class="ph">${esc(w.placeholder)}</span><span class="st ${statusClass(d)}">${esc(st)}</span></div><div class="by">${by}${w.anomaly ? ` · scenario anomaly <code>${esc(w.anomaly)}</code>` : ""}</div>${edited}${finalArgs}</div>`;
    }).join("");
    const deps = ms.filter((w) => w.depends_on.length).map((w) => `<div class="kv"><code>${esc(w.tool)}</code> depends on ${w.depends_on.map((p) => `<code>${esc(byPh[p] ? byPh[p].tool : p)}</code> <span class="mono">${esc(p)}</span>`).join(", ")}${w.blocked_by.length ? ` · blocked by <code>${esc(w.blocked_by.join(", "))}</code>` : ""}</div>`).join("") || `<div class="kv">none — a root write</div>`;
    const cascade = uiDiscarded(card) || (r && r.status === "discarded")
      ? `<h3>Cascade</h3><div class="kv">${cascadeIds(card).map((id) => { const w = ms.find((x) => x.id === id); return w ? `<code>${esc(w.tool)}</code> ${esc(w.placeholder)}` : esc(id); }).join(", ") || "nothing else depends on it"} — never sent</div>` : "";
    const target = isReviewTarget(card) && r && r.status === "held" && !r.blocked_by.length;
    const actions = target ? (uiDiscarded(card) ? `<span class="note">Marked to discard · ${esc(cascadeText(R.cascade[card.rootId]))}</span><button class="btn small" data-action="keep">Keep</button>` : `<button class="btn danger small" data-action="discard">Discard</button><span class="note">Approve applies the run in dependency order</span>`) : "";
    dlg.innerHTML = `
      <div class="dlg-head"><span class="title" id="dlg-title">${esc(chainTitle(card))}</span><span class="amount">${esc(chainAmount(card))}</span>
        <span class="meta"><span>${esc(label())} ${card.run}</span><span class="${col === "needs_approval" ? "amber" : col === "complete" ? "green" : "muted"}">${esc(COL_TITLE[col])}</span>${r && r.anomaly ? `<span class="mono">${esc(r.anomaly)}</span>` : ""}</span>
        <button class="close" data-action="close" aria-label="Close">×</button>
        <div class="ctx">${esc(runContext(rr))}</div></div>
      <div class="dlg-body">
        ${flagsHtml ? `<h3>Why it stopped</h3>${flagsHtml}` : ""}
        <h3>The chain, in the order the agent called it</h3>${chainHtml2}
        <h3>Dependencies</h3>${deps}
        ${cascade}
      </div>
      ${actions ? `<div class="dlg-actions">${actions}</div>` : ""}`;
    bindDialog(card);
  }
  function fillRuleDialog(card) {
    const { src, beforeHtml, after } = ruleDiff(card);
    const rule = card.rule;
    const st = ruleState(card);
    const actions = st.accepted ? `<span class="note green">Rule on — from the next action</span>` : st.done ? `<span class="note">Not now — the edit still applied</span>` : `<button class="btn amber small" data-action="rule-accept">Yes always</button><button class="btn ghost small" data-action="rule-later">Not now</button>`;
    dlg.innerHTML = `
      <div class="dlg-head"><span class="title" id="dlg-title">A rule from Tom's edit</span><span class="meta"><span>${esc(label())} ${card.run}</span><span class="mono">${esc(rule.id)}</span></span><button class="close" data-action="close" aria-label="Close">×</button><div class="ctx">${esc(runContext(runOf(card.run)))}</div></div>
      <div class="dlg-body">
        <h3>What Tom changed</h3>
        <div class="kv">${esc(src ? src.tool : rule.tool)} · ${esc(rule.field)}${src ? ` · ${esc(summary(src))}` : ""}</div>
        <div class="diff"><div class="side before"><span class="lab">before</span>${beforeHtml}</div><div class="side after"><span class="lab">after (Tom's edit)</span>${esc(after)}</div></div>
        <h3>The rule the layer derived</h3>
        <div class="flagline"><span class="kind">rule</span>Hold every <b>${esc(rule.tool)}</b> whose <b>${esc(rule.field)}</b> ${rule.op === "matches" ? "contains" : rule.op} ${esc(rule.label)}<span class="detail">${esc(rule.op)} <code>${esc(typeof rule.value === "string" ? rule.value : JSON.stringify(rule.value))}</code> · status ${esc(st.accepted ? "active" : rule.status)} · by ${esc(rule.created_by)}</span></div>
      </div>
      <div class="dlg-actions">${actions}</div>`;
    bindDialog(card);
  }
  function bindDialog(card) {
    dlg.querySelectorAll("[data-action]").forEach((b) => {
      b.onclick = (e) => { e.stopPropagation(); if (b.dataset.action === "close") closeDialog(); else act(card, b.dataset.action); };
    });
  }
  let opener = null;
  function openCard(key, from) {
    const card = S.cards.get(key); if (!card || card.kind === "queued") return;
    S.opened = key; opener = from || null;
    fillDialog(card);
    dlg.classList.remove("closing");
    if (!dlg.open) dlg.showModal();
    const close = dlg.querySelector(".close"); if (close) close.focus({ preventScroll: true });
  }
  function closeDialog() {
    if (!dlg.open) return;
    const done = () => {
      dlg.classList.remove("closing"); if (dlg.open) dlg.close();
      dlg.innerHTML = ""; // a closed dialog never holds a [data-action] button ahead of the board
      S.opened = null;
      if (opener && opener.isConnected) opener.focus({ preventScroll: true });
      opener = null;
    };
    if (REDUCED) { done(); return; }
    dlg.classList.add("closing");
    setTimeout(done, 170);
  }
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); closeDialog(); });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) closeDialog(); });

  // ------------------------------------------------------------------ the learned panel and the learning screen: Chart.js over what the layer already has
  function learnedPanel(withEnts = true) {
    return `<div class="panel learned"><h2>What it has learned</h2>
      <div id="learned-ladder"></div>
      <div id="learned-rules"></div>
      <div class="lh" id="learned-hh" hidden>History</div>
      <div class="events" id="learned-events"></div>
      ${withEnts ? `<div class="ents" id="learned-ents"></div>` : ""}
      ${ruleForm()}</div>`;
  }
  function ruleSentence(r) {
    const join = r.op === "matches" ? "contains" : "is";
    return `hold ${r.tool} when ${r.field} ${join} ${r.label || `${r.op} ${r.value}`}`;
  }
  function fillLearned(learned, sinceRun) {
    const ev = $("learned-events"), ents = $("learned-ents"), lad = $("learned-ladder");
    if (!ev) return;
    const rel = learned.ladder.filter((l) => l.level === "released");
    const checked = learned.ladder.filter((l) => l.level !== "released");
    const lh = (title, n) => `<div class="lh">${title}<span class="n">${n}</span></div>`;
    const row = (name, meta) => `<div class="lrow"><span class="ln">${esc(name)}</span><span class="lm">${esc(meta)}</span></div>`;
    lad.innerHTML =
      (rel.length ? lh("Sent without review", rel.length) + rel.map((l) => row(l.tool, `${l.released_run ? `since ${fri(l.released_run)} · ` : ""}${l.approved} approved`)).join("") : "") +
      (checked.length ? lh("Still checked, earning trust", checked.length) + checked.map((l) => row(l.tool, `${l.approved} approved${l.discarded ? ` · ${l.discarded} discarded` : ""}`)).join("") : "");
    const active = learned.rules.filter((r) => r.status === "active");
    $("learned-rules").innerHTML = active.length
      ? lh("Tom's rules", active.length) + active.map((r) =>
          `<div class="lrule"><div class="ln">${esc(ruleSentence(r))}</div><div class="lm">${esc(r.created_by === "person" ? "Tom" : r.created_by)} · ${esc(fri(r.created_run))}</div></div>`).join("")
      : "";
    const shown = new Set([...ev.querySelectorAll(".ev")].map((n) => n.dataset.key));
    for (const e of learned.events) {
      if (sinceRun !== undefined && e.run !== sinceRun) continue;
      if (e.kind === "envelope" && REF_TOKEN.test(e.text)) continue; // a per-record label the layer took for an entity: nothing to show
      const key = `${e.run}|${e.kind}|${e.text}`;
      if (shown.has(key)) continue;
      const text = e.kind === "promotion" && e.text.includes("now sent") ? e.text.replace(/\s*\(.*\)$/, "") : e.text;
      let group = ev.querySelector(`.evg[data-run="${e.run}"] .evi`);
      if (!group) {
        const wrap = el(`<div class="evg" data-run="${e.run}"><div class="evk">${esc(fri(e.run))}</div><div class="evi"></div></div>`);
        ev.appendChild(wrap);
        group = wrap.lastElementChild;
      }
      group.appendChild(el(`<div class="ev ${esc(e.kind)}" data-key="${esc(key)}">${esc(text)}</div>`));
    }
    const hh = $("learned-hh");
    if (hh) hh.hidden = !ev.children.length;
    if (!ents) { snapEvents(ev); return; }
    // one line per entity: the tool whose writes carry an account-shaped value wins, else the first with a range
    const byValue = {};
    for (const x of learned.entities) {
      if (REF_TOKEN.test(x.value)) continue;
      const accounts = Object.entries(x.sets).filter(([k, s]) => k !== x.field && s.values.every((v) => shape(v) === "account")).map(([, s]) => s.values.join(", "));
      const range = Object.entries(x.ranges)[0];
      const score = (accounts.length ? 2 : 0) + (range ? 1 : 0);
      const cur = byValue[x.value];
      if (!cur || score > cur.score) byValue[x.value] = { x, accounts, range, score };
    }
    ents.innerHTML = Object.values(byValue).map(({ x, accounts, range }) =>
      `<div class="ent"><span class="nm">${esc(x.value)}</span><span class="rg">${range ? `${esc(range[0])} usually ${money0(range[1].observed_min)}–${money0(range[1].observed_max)}` : `${x.n} approved`}${accounts.length ? ` · ${esc(accounts[0])}` : ""}</span></div>`
    ).join("");
    snapEvents(ev);
  }
  // scrolled to the newest event, then shortened so the first row on screen starts at the top edge instead of half under the chips
  function snapEvents(ev) {
    ev.style.height = "";
    ev.scrollTop = ev.scrollHeight;
    if (ev.scrollHeight <= ev.clientHeight + 1) return;
    const top = ev.getBoundingClientRect().top + parseFloat(getComputedStyle(ev).paddingTop || "0");
    const first = [...ev.querySelectorAll(".ev")].find((r) => r.getBoundingClientRect().top >= top - 1);
    const excess = first ? first.getBoundingClientRect().top - top : 0;
    if (excess > 1 && excess < ev.clientHeight / 2) {
      ev.style.height = `${Math.round(ev.clientHeight - excess)}px`;
      ev.scrollTop = ev.scrollHeight;
    }
  }

  const LCharts = {};
  function mountChart(boxId, height, config) {
    const box = $(boxId);
    box.style.height = `${height}px`;
    box.innerHTML = `<canvas></canvas>`;
    if (LCharts[boxId]) LCharts[boxId].destroy();
    LCharts[boxId] = new Chart(box.firstElementChild, config);
  }
  function themeCharts() {
    const css = getComputedStyle(document.documentElement);
    const v = (name) => css.getPropertyValue(name).trim();
    Chart.defaults.font.family = "InterVariable, Inter, system-ui, sans-serif";
    Chart.defaults.font.size = 11.5;
    Chart.defaults.color = v("--fog");
    Chart.defaults.borderColor = v("--graphite");
    Chart.defaults.animation.duration = 300;
    Chart.defaults.plugins.legend.position = "bottom";
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.boxWidth = 6;
    Chart.defaults.plugins.legend.labels.boxHeight = 6;
    Chart.defaults.plugins.legend.labels.padding = 14;
    Object.assign(Chart.defaults.plugins.tooltip, {
      backgroundColor: v("--obsidian"), borderColor: v("--graphite"), borderWidth: 1,
      titleColor: v("--mist"), bodyColor: v("--fog"), cornerRadius: 6, padding: 10, displayColors: false,
    });
    return { amber: v("--amber"), green: v("--green"), red: v("--red"), fog: v("--fog"), mist: v("--mist"), carbon: v("--carbon"), graphite: v("--graphite") };
  }

  function renderLearning() {
    setScreen("learning");
    closeDialog();
    for (const card of S.cards.values()) if (card.el) { cancelGhost(card.key); card.el.remove(); card.col = null; }
    main.innerHTML = `
      <div class="cols">
        <div class="charts">
          <div class="panel chart"><h2>Hold rate per ${label()} (% of writes checked)</h2><div class="chart-box" id="ch-line"></div></div>
          <div class="panel chart"><h2>Review outcomes by tool (writes)</h2><div class="chart-box" id="ch-tools"></div></div>
          <div class="panel chart"><h2>Envelope bounds by entity (min–max approved value)</h2><div class="chart-box" id="ch-env"></div></div>
        </div>
        ${learnedPanel(false)}
      </div>`;
    const T = themeCharts();
    drawHeldLine(T);
    drawTools(T);
    drawEnv(T);
    fillLearned(S.view.learned);
    bindRuleForm((res) => { fillLearned(res); drawTools(T); drawEnv(T); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => Object.values(LCharts).forEach((c) => c.update("none")));
    renderHeader();
  }

  function drawHeldLine(T) {
    const runs = Object.values(S.view.runs).sort((a, b) => a.run - b.run);
    if (runs.length < 2) { $("ch-line").innerHTML = `<div class="empty">Play some ${label()}s first.</div>`; return; }
    const pct = (r) => (r.counts.checked ? Math.round((100 * (r.counts.held + r.counts.blocked)) / r.counts.checked) : 0);
    mountChart("ch-line", 220, {
      type: "line",
      data: {
        labels: runs.map((r) => r.run),
        datasets: [
          {
            label: "held for review", data: runs.map(pct),
            borderColor: T.amber, backgroundColor: T.amber, borderWidth: 2, tension: 0, clip: false,
            pointRadius: (c) => (runs[c.dataIndex].counts.caught ? 4 : 0),
            pointHoverRadius: 5, pointBorderWidth: 0, pointStyle: "circle",
          },
          {
            label: "checked", data: runs.map(() => 100),
            borderColor: T.fog, backgroundColor: T.fog, borderWidth: 1.5, pointRadius: 0, pointHoverRadius: 0, clip: false,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        layout: { padding: { top: 6 } },
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { min: 0, max: 100, ticks: { callback: (v) => v + "%", stepSize: 50 } },
          x: { grid: { display: false }, ticks: { maxTicksLimit: 10, callback: (v, i) => `${label().slice(0, 3)} ${runs[i].run}` } },
        },
        plugins: {
          tooltip: {
            callbacks: {
              title: (items) => `${label()} ${runs[items[0].dataIndex].run}`,
              label: (item) => {
                if (item.datasetIndex === 1) return `checked ${runs[item.dataIndex].counts.checked} writes`;
                const c = runs[item.dataIndex].counts;
                return `held ${c.held + c.blocked} of ${c.checked}${c.caught ? ` · caught ${c.caught}` : ""}`;
              },
            },
          },
        },
      },
    });
  }

  function drawTools(T) {
    const lad = S.view.learned.ladder.slice().sort((a, b) => (b.approved + b.edited + b.discarded) - (a.approved + a.edited + a.discarded));
    if (!lad.length) { $("ch-tools").innerHTML = `<div class="empty">No reviews yet.</div>`; return; }
    const seg = (label2, key, color) => ({
      label: label2, data: lad.map((l) => l[key]),
      backgroundColor: color, borderColor: T.carbon, borderWidth: 1, borderRadius: 3, borderSkipped: false, barThickness: 12,
    });
    mountChart("ch-tools", 60 + lad.length * 34, {
      type: "bar",
      data: {
        labels: lad.map((l) => l.tool),
        datasets: [seg("approved", "approved", T.green), seg("edited", "edited", T.fog), seg("discarded", "discarded", T.red)],
      },
      options: {
        maintainAspectRatio: false,
        indexAxis: "y",
        scales: {
          x: { stacked: true, ticks: { precision: 0 } },
          y: { stacked: true, grid: { display: false }, ticks: { color: T.mist } },
        },
        plugins: {
          tooltip: {
            callbacks: {
              afterTitle: (items) => {
                const l = lad[items[0].dataIndex];
                return l.level === "released" ? "sent without review" : "checked";
              },
            },
          },
        },
      },
    });
  }

  function drawEnv(T) {
    const best = {};
    for (const e of S.view.learned.entities) {
      const range = Object.entries(e.ranges)[0];
      if (!range || REF_TOKEN.test(e.value)) continue;
      if (!best[e.value] || e.n > best[e.value].e.n) best[e.value] = { e, range };
    }
    const rows = Object.values(best).sort((a, b) => b.range[1].observed_max - a.range[1].observed_max);
    if (!rows.length) { $("ch-env").innerHTML = `<div class="empty">Nothing approved yet.</div>`; return; }
    mountChart("ch-env", 46 + rows.length * 30, {
      type: "bar",
      data: {
        labels: rows.map(({ e }) => e.value),
        datasets: [{
          data: rows.map(({ range }) => [range[1].observed_min, range[1].observed_max]),
          backgroundColor: T.mist, borderRadius: 4, borderSkipped: false, barThickness: 8,
        }],
      },
      options: {
        maintainAspectRatio: false,
        indexAxis: "y",
        scales: {
          x: { beginAtZero: true, ticks: { callback: (v) => money0(v) } },
          y: { grid: { display: false }, ticks: { color: T.mist } },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (item) => {
                const { e, range } = rows[item.dataIndex];
                return `${range[0]} usually ${money0(range[1].observed_min)}–${money0(range[1].observed_max)} · ${e.n} approved`;
              },
            },
          },
        },
      },
    });
  }

  // ------------------------------------------------------------------ opening, review, reset
  function openBoard() {
    const v = S.view;
    S.phase = phaseFor(v);
    const run = v.current_run || firstReviewRun();
    setHero(run, runOf(run), false);
    renderBoardScreen();
  }
  function renderOpening() {
    setScreen("opening");
    openBoard();
  }
  function renderReview(which) {
    if (which === "live") R = S.live; else if (which === "demo" || !S.live.run) R = S.review;
    showBoard();
    syncRuleCard();
    setScreen("review");
    renderStrip();
    renderBoard();
    renderHeader();
    scrollToCol("needs_approval");
  }
  async function reset() {
    if (S.busy) return;
    S.busy = true; renderHeader();
    closeDialog();
    try {
      S.view = await api("POST", "/reset");
    } catch (e) { console.error(e); S.busy = false; renderHeader(); notice(e.detail || e.message); return; }
    S.busy = false;
    S.review = freshReview(); S.live = freshReview(); R = S.review;
    S.montage = { done: false, running: false };
    S.auto = { running: false, played: [] };
    S.applying = undefined; S.latest = null; S.colBanner = ""; S.rail = false;
    buildRegistry();
    renderOpening();
  }

  // ------------------------------------------------------------------ boot
  async function boot() {
    $("b-board").onclick = () => renderOpening();
    $("b-review").onclick = () => renderReview("demo");
    $("b-montage").onclick = () => startMontage();
    $("b-auto").onclick = () => startAutopilot();
    $("b-learn").onclick = () => renderLearning();
    $("b-reset").onclick = () => reset();
    try {
      S.view = await api("GET", "/state");
      if (!runOf(firstReviewRun())) S.view = await api("POST", "/reset");
      const rr = runOf(firstReviewRun());
      if (rr && rr.decided) S.review.decided = true;
    } catch (e) {
      console.error(e);
      main.innerHTML = `<div class="panel"><h2>Could not reach the service</h2><div class="red">${esc(e.message)}</div></div>`;
      return;
    }
    buildRegistry();
    renderOpening();
  }
  window.pakka = { S, boot, renderOpening, renderReview, renderBoard, openCard, startMontage, startAutopilot, reset, runLive, renderHeader };
  boot();
})();
