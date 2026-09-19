/* pakka — the board. A job runs through an agent; every write it wants to make is held. Each card is one write plus
   the writes that depend on it; its column is what happened to it. You decide in the popup (approve, edit, discard);
   the decisions go to the server once per job, and the approved writes land in order with real ids. No framework. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ state
  const COLS = ["not_started", "in_progress", "needs_approval", "complete"];
  const COL_TITLE = { not_started: "Not started", in_progress: "In progress", needs_approval: "Needs your approval", complete: "Complete" };
  const S = {
    view: null,              // StateView from GET /state
    screen: "board",
    busy: false,
    running: false,          // a job is running
    cards: new Map(),        // key -> card
    latest: null,            // the learn event the bar shows
    applying: new Set(),     // runs whose decisions are landing right now
    decisions: {},           // run -> { write id -> {action, args} }   collected locally, sent once
    rules: {},               // run -> { rule id -> true|false }         accept / decline, sent with the decisions
    opened: null,            // card key in the popup
    sheet: null,             // "rules" | "settings" | null
    cascade: {},             // write id -> ids skipped if it is discarded (preview)
    editing: null,           // write id being edited in the popup
    errors: {},              // write id -> validation messages from the last decision
    ruleText: {},            // rule id -> the rule in the person's words, as typed in the popup
    readings: {},            // rule id -> { text, reading }: how the layer read those words (POST /rules/read)
    scenario: null,          // GET /scenario
    team: null,              // this board's team key (X-Pakka-Team); null = the shared team
  };
  const REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const NARROW = () => window.matchMedia && window.matchMedia("(max-width: 1100px)").matches;
  const EASE = "cubic-bezier(0.2, 0.7, 0.2, 1)";
  const MOVE_MS = 320;

  const $ = (id) => document.getElementById(id);
  const main = $("main");
  const dlg = $("detail");

  // ------------------------------------------------------------------ api: every call carries the team key
  try { S.team = localStorage.getItem("pakka-team") || null; } catch (e) { S.team = null; }
  function setTeam(key) { S.team = key || null; try { if (key) localStorage.setItem("pakka-team", key); else localStorage.removeItem("pakka-team"); } catch (e) { /* private mode */ } }
  async function api(method, path, body) {
    const headers = body !== undefined ? { "Content-Type": "application/json" } : {};
    if (S.team) headers["X-Pakka-Team"] = S.team;
    const r = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
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

  // ------------------------------------------------------------------ words
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
  function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function unit() { return (S.view && S.view.volume_unit) || ""; }
  function money(n) { return typeof n === "number" ? unit() + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : ""; }
  function money0(n) { return unit() + Math.round(n).toLocaleString("en-GB"); }
  function label() { return (S.view && S.view.run_label) || "Run"; }
  function runName(n) { return `${label()} ${n}`; }
  function human(s) { s = String(s || "").replace(/_/g, " ").trim(); return s.charAt(0).toUpperCase() + s.slice(1); } // create_payout → Create payout
  function args(w) { return w.edited_args || w.args; }
  function firstOf(a, shapes) { for (const [k, v] of Object.entries(a)) if (shapes.includes(shape(v))) return [k, v]; return [null, null]; }
  function el(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }
  function setScreen(name) { S.screen = name; main.dataset.screen = name; }
  function runOf(n) { return S.view && S.view.runs[String(n)]; }
  function ruleById(id) { return (S.view.learned.rules || []).find((r) => r.id === id); }
  function opWords(op) { return { matches: "contains", in: "is one of", not_in: "is not one of", gt: "is over", lt: "is under" }[op] || op; }
  function ruleSentence(r) { return `Hold ${human(r.tool).toLowerCase()} when ${human(r.field || "any field").toLowerCase()} ${opWords(r.op)} ${r.label || (Array.isArray(r.value) ? r.value.join(", ") : r.value)}`; }
  function valueWords(r) { if (r.label) return r.label; if (Array.isArray(r.value)) return r.value.join(", "); if (typeof r.value === "number") return r.value.toLocaleString("en-GB"); return r.op === "matches" ? `/${r.value}/` : String(r.value); }
  // the popup's prefill: the layer's proposal in the words its reader accepts (pakka/rule_text.py), so the person can edit it
  function ruleWords(r) { return `Always hold ${human(r.tool)} when ${human(r.field || "any field").toLowerCase()} ${opWords(r.op)} ${valueWords(r)}`; }
  function ruleSource(r) { return r.derived_from ? "from your edit" : r.created_by === "person" ? "typed by you" : r.created_by; }
  function readingSentence(r) { return `Hold ${r.tool === "*" ? "any tool" : human(r.tool)} when ${human(r.field || "any field").toLowerCase()} ${opWords(r.op)} ${valueWords(r)}`; } // the same words pakka/rule_text.py reads back
  function ruleOrigin(r) { return r.derived_from ? `from your edit, ${runName(r.created_run)}` : r.created_by === "person" ? `typed by you, ${runName(r.created_run)}` : `${r.created_by}, ${runName(r.created_run)}`; }
  function latestRun() { const runs = Object.values(S.view.runs); return runs.length ? runs.reduce((a, b) => (a.run > b.run ? a : b)) : null; }
  function agentLabel(id) { const a = (S.view.agents || []).find((x) => x.id === id); return a ? a.label : id || ""; }
  function tokens(n) { return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n); }
  // the job that "Send decisions" acts on: the newest one still waiting on you
  function focusRun() {
    const runs = Object.values(S.view.runs).filter((r) => !r.decided && r.writes.some((w) => w.status === "held"));
    return runs.length ? runs.reduce((a, b) => (a.run > b.run ? a : b)).run : null;
  }
  function pending(run) { return S.decisions[run] || (S.decisions[run] = {}); }
  function ruleChoices(run) { return S.rules[run] || (S.rules[run] = {}); }

  // chains: one card per root write (no depends_on); dependents follow the placeholders
  function chains(rr) {
    const roots = rr.writes.filter((w) => !w.depends_on.length);
    return roots.map((root) => {
      const deps = [];
      const dead = new Set([root.placeholder]);
      let changed = true;
      while (changed) {
        changed = false;
        for (const w of rr.writes) if (w !== root && !deps.includes(w) && w.depends_on.some((p) => dead.has(p))) { deps.push(w); dead.add(w.placeholder); changed = true; }
      }
      deps.sort((a, b) => a.seq - b.seq);
      return { root, deps };
    });
  }

  // ------------------------------------------------------------------ the registry: what the board shows for each write right now
  function serverDisp(w) {
    if (w.sent) return "sent";
    if (w.status === "held") return w.blocked_by.length ? "blocked" : "held";
    if (w.status === "discarded") return "discarded";
    if (w.status === "skipped") return "skipped";
    if (w.status === "approved" || w.status === "edited") return "held"; // decided but not landed (a failed delivery, or a step whose dependency is still held)
    return "sent";
  }
  const REVEALED = (d) => d && d !== "pending" && d !== "active";
  function makeChainCard(rr, c, disp) {
    const key = `${rr.run}:${c.root.id}`;
    let card = S.cards.get(key);
    if (!card) { card = { key, kind: "chain", run: rr.run, rootId: c.root.id, ids: [], disp: {}, el: null, col: null, sig: "" }; S.cards.set(key, card); }
    card.ids = [c.root.id, ...c.deps.map((d) => d.id)];
    for (const id of card.ids) if (!(id in card.disp) || disp !== undefined) card.disp[id] = disp === undefined ? serverDisp(memberOf(card, id)) : disp;
    return card;
  }
  function memberOf(card, id) { const rr = runOf(card.run); return rr && rr.writes.find((w) => w.id === id); }
  function members(card) { return card.ids.map((id) => memberOf(card, id)).filter(Boolean); }
  function root(card) { return memberOf(card, card.rootId); }
  function makeRuleCard(run, rule) {
    const key = `rule:${rule.id}`;
    let card = S.cards.get(key);
    if (!card) { card = { key, kind: "rule", run, rule, el: null, col: null, sig: "" }; S.cards.set(key, card); }
    card.rule = rule; card.run = run;
    return card;
  }
  function makeJobCard(run, text) {
    const key = `job:${run}`;
    let card = S.cards.get(key);
    if (!card) { card = { key, kind: "job", run, text, el: null, col: null, sig: "" }; S.cards.set(key, card); }
    card.text = text;
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
  function buildRegistry() {
    for (const key of [...S.cards.keys()]) { const c = S.cards.get(key); cancelGhost(key); if (c.el) c.el.remove(); S.cards.delete(key); }
    for (const rr of Object.values(S.view.runs)) for (const c of chains(rr)) makeChainCard(rr, c);
    syncRules();
  }
  // a rule the layer proposes from an edit is a card on the run it came from until the decisions are sent
  function syncRules() {
    for (const rr of Object.values(S.view.runs)) for (const r of rr.proposed_rules || []) makeRuleCard(rr.run, ruleById(r.id) || r);
    for (const r of S.view.learned.rules || []) if (r.derived_from) makeRuleCard(r.created_run || 1, r);
  }

  // where a card sits, from what the board is showing
  function cardColumn(card) {
    if (card.kind === "job") return "in_progress";
    if (card.kind === "rule") return card.rule.status === "proposed" && !runOf(card.run)?.decided ? "needs_approval" : "complete";
    const ds = card.ids.map((id) => card.disp[id] || "pending");
    if (ds.some((d) => d === "held" || d === "blocked")) return "needs_approval";
    if (ds.every((d) => d === "sent" || d === "discarded" || d === "skipped")) return "complete";
    if (ds.every((d) => d === "pending")) return "not_started";
    return "in_progress";
  }
  function actionable(card) { const rr = runOf(card.run); return !!rr && !rr.decided && members(card).some((w) => w.status === "held") && !S.applying.has(card.run); }
  function revealedMembers(card) { return members(card).filter((w) => REVEALED(card.disp[w.id])); }
  function flagged(card) { return revealedMembers(card).some((w) => w.flags.length); }
  function firstFlag(card) { for (const w of revealedMembers(card)) if (w.flags.length) return { w, f: w.flags[0] }; return null; }
  function mark(card) { const p = pending(card.run); const r = root(card); if (r && p[r.id]) return p[r.id].action; for (const w of members(card)) if (p[w.id]) return p[w.id].action; return null; }
  function orderKey(card, col) {
    const r = root(card);
    const decided = col === "needs_approval" || col === "complete";
    const rank = card.kind === "job" ? 0 : card.kind === "rule" ? 1 : decided && flagged(card) ? 0 : 2;
    return [-card.run, rank, r ? r.seq : 0];
  }
  function cmp(a, b) { for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1; return 0; }

  // ------------------------------------------------------------------ card html: title, amount, the steps as dots, one line of status
  function chainTitle(card) { const r = root(card); if (!r) return ""; const [, name] = firstOf(args(r), ["name"]); return name || human(r.tool); }
  function chainAmount(card) { const r = root(card); if (!r) return ""; const [, num] = firstOf(args(r), ["number"]); return typeof num === "number" ? money(num) : ""; }
  function skippedIds(card) {
    const done = members(card).filter((w) => w.status === "skipped").map((w) => w.id);
    return done.length ? done : (S.cascade[card.rootId] || []);
  }
  function deliveryOf(w) { const rr = runOf(w.run); const e = rr && rr.effects.find((x) => x.result_id === w.result_id && x.tool === w.tool); return e && e.detail && e.detail.status ? e.detail : null; }
  function statusLine(card, col) {
    const ms = members(card), r = root(card);
    const sent = ms.filter((w) => card.disp[w.id] === "sent");
    const m = mark(card);
    if (col === "not_started") return `<span class="st">Queued</span>`;
    if (col === "in_progress") return `<span class="st">${S.applying.has(card.run) ? "Sending…" : "Agent working…"}</span>`;
    if (col === "needs_approval") {
      const errs = ms.filter((w) => S.errors[w.id]).length;
      if (errs) return `<span class="st red">Not sent — fix the edit</span>`;
      if (m === "discard") return `<span class="st red">Will be discarded${skippedIds(card).length ? ` · ${skippedIds(card).length} step${skippedIds(card).length === 1 ? "" : "s"} skipped` : ""}</span>`;
      if (m === "edit") return `<span class="st green">Edited · will be sent</span>`;
      if (m === "approve") return `<span class="st green">Will be sent</span>`;
      const rr = runOf(card.run);
      if (rr && rr.decided && r && (r.status === "approved" || r.status === "edited")) return `<span class="st amber">Approved · not delivered</span>`;
      return `<span class="st amber">Held for you${sent.length ? ` · ${sent.length} of ${ms.length} sent` : ""}</span>`;
    }
    if (r && card.disp[r.id] === "discarded") { const n = skippedIds(card).length; return `<span class="st red">Discarded${n ? ` · ${n} step${n === 1 ? "" : "s"} skipped` : ""}</span>`; }
    const how = sent.length && sent.every((w) => w.decided_by === "layer" || w.status === "passed") ? "Sent without review" : r && r.status === "edited" ? "Edited and sent" : "Sent";
    const ids = sent.map((w) => w.result_id).filter(Boolean);
    const d = r && deliveryOf(r);
    return `<span class="st green">${esc(how)}${d ? ` · ${esc(d.status)}` : ""}</span><span class="ids" title="${esc(ids.join(" "))}">${esc(ids.join(" "))}</span>`;
  }
  function chainHtml(card, col) {
    const ms = members(card);
    const ff = firstFlag(card);
    const title = chainTitle(card);
    const steps = ms.map((w) => `<span class="step" data-status="${esc(card.disp[w.id] || "pending")}" title="${esc(human(w.tool))}${w.result_id ? " → " + esc(w.result_id) : ""}"></span>`).join("");
    return `
      <button class="open" data-action="open" aria-label="Open ${esc(title)}"><span class="title">${esc(title)}</span><span class="amount">${esc(chainAmount(card))}</span></button>
      <div class="steps"><span class="dots">${steps}</span><span class="names">${ms.map((w) => esc(human(w.tool))).join(" · ")}</span></div>
      ${ff ? `<div class="flag">${esc(ff.f.reason)}</div>` : ""}
      <div class="foot">${statusLine(card, col)}<span class="tag">${esc(runName(card.run))}</span></div>`;
  }
  function markPattern(text, rule) {
    let html = esc(text);
    if (rule.op === "matches" && rule.value) { try { html = esc(text).replace(new RegExp(rule.value, "g"), (m) => `<mark>${m}</mark>`); } catch (e) { /* plain */ } }
    return html;
  }
  // the edit a rule came from: what was taken out (the sentences gone from `after`, else what the pattern finds), marked
  function ruleDiff(rule) {
    const rr = runOf(rule.created_run) || latestRun();
    const src = rr && (rr.writes.find((w) => w.id === rule.derived_from) || rr.writes.find((w) => w.edited_args));
    const before = src ? String(src.args[rule.field] ?? "") : "";
    const after = src && src.edited_args ? String(src.edited_args[rule.field] ?? "") : "";
    let removed = before ? before.split(/(?<=\.)\s*/).map((x) => x.trim()).filter((x) => x && !after.includes(x)) : [];
    if (!removed.length && rule.op === "matches" && before) { try { removed = before.match(new RegExp(rule.value, "g")) || []; } catch (e) { removed = []; } }
    let beforeHtml = esc(before);
    removed.forEach((x) => { beforeHtml = beforeHtml.replace(esc(x), `<del>${esc(x)}</del>`); });
    const fragHtml = removed.map((x) => markPattern(x, rule)).join(" … ");
    return { src, before, after, removed, beforeHtml, fragHtml };
  }
  function ruleHtml(card) {
    const rule = ruleById(card.rule.id) || card.rule;
    const { fragHtml } = ruleDiff(rule);
    const choice = ruleChoices(card.run)[rule.id];
    const undo = `<button class="btn ghost small" data-action="rule-undo">Undo</button>`;
    const foot = rule.status === "active" ? `<span class="st green">Rule on — applies from the next write</span>`
      : rule.status === "rejected" ? `<span class="st">Not a rule — the edit still applied</span>`
      : choice === true ? `<span class="st green">Yes — becomes a rule with your decisions</span>${undo}`
      : choice && typeof choice === "object" ? `<span class="st green">Your rule goes with your decisions</span>${undo}`
      : choice === "fine" ? `<span class="st">Fine by you — no rule</span>${undo}`
      : choice === false ? `<span class="st">Not now</span><button class="btn ghost small" data-action="rule-accept">Yes, always</button>`
      : `<button class="btn amber small" data-action="rule-accept">Yes, always</button><button class="btn ghost small" data-action="rule-later">Not now</button>`;
    const words = choice && typeof choice === "object" ? choice.sentence : ruleSentence(rule);
    return `
      <button class="open" data-action="open" aria-label="Open the proposed rule"><span class="title">Make this a rule?</span><span class="tag">${esc(human(rule.tool))}</span></button>
      ${fragHtml ? `<div class="frag small"><span class="lab">you took out</span>${fragHtml}</div>` : ""}
      <div class="rule-q">${esc(words)}</div>
      <div class="foot">${foot}<span class="tag">${esc(runName(card.run))}</span></div>`;
  }
  function jobHtml(card) { return `<div class="open"><span class="title">${esc(card.text)}</span></div><div class="foot"><span class="st">Agent running</span><span class="tag">${esc(runName(card.run))}</span></div>`; }
  function cardSig(card, col) {
    if (card.kind === "chain") return `${col}|${members(card).map((w) => (card.disp[w.id] || "p") + w.status + (w.result_id || "") + (S.errors[w.id] ? "!" : "")).join(",")}|${actionable(card)}|${mark(card)}|${(S.cascade[card.rootId] || []).length}`;
    if (card.kind === "rule") return `${col}|${(ruleById(card.rule.id) || card.rule).status}|${JSON.stringify(ruleChoices(card.run)[card.rule.id] ?? null)}`;
    return `${col}|${card.text}`;
  }
  function ensureEl(card) {
    if (card.el) return card.el;
    const node = el(`<article class="card enter" data-card="${esc(card.key)}" data-kind="${card.kind}" data-run="${card.run}"></article>`);
    setTimeout(() => node.classList.remove("enter"), 400);
    node.addEventListener("click", (e) => onCardClick(card, e));
    card.el = node;
    return node;
  }
  function patchCard(card, col) {
    const node = ensureEl(card);
    const sig = cardSig(card, col);
    if (sig === card.sig) return node;
    card.sig = sig;
    node.innerHTML = card.kind === "chain" ? chainHtml(card, col) : card.kind === "rule" ? ruleHtml(card) : jobHtml(card);
    node.classList.toggle("flagged", card.kind === "chain" && flagged(card) && col === "needs_approval");
    node.classList.toggle("discarded", card.kind === "chain" && ((!!root(card) && root(card).status === "discarded") || mark(card) === "discard"));
    node.classList.toggle("marked", card.kind === "chain" && mark(card) !== null && col === "needs_approval");
    if (S.opened === card.key && dlg.open && !S.editing) fillDialog(card);
    return node;
  }

  // ------------------------------------------------------------------ the board: reconcile the DOM against the registry, move with FLIP
  const ghosts = new Map();
  function boardMounted() { return !!$("board"); }
  function renderBoard(animate = true) {
    if (!boardMounted()) return;
    const byCol = { not_started: [], in_progress: [], needs_approval: [], complete: [] };
    for (const card of S.cards.values()) byCol[cardColumn(card)].push(card);
    for (const col of COLS) byCol[col].sort((a, b) => cmp(orderKey(a, col), orderKey(b, col)));
    const before = new Map();
    if (animate && !REDUCED) for (const card of S.cards.values()) {
      const g = ghosts.get(card.key);
      if (g) before.set(card.key, g.ghost.getBoundingClientRect());
      else if (card.el && card.el.isConnected) before.set(card.key, card.el.getBoundingClientRect());
    }
    const moved = [];
    for (const col of COLS) {
      const section = main.querySelector(`section.col[data-col="${col}"]`);
      const body = section.querySelector(".col-body");
      const cards = byCol[col];
      const nodes = [];
      let lastRun = null;
      for (const card of cards) {
        if (col === "complete" && card.kind === "chain" && card.run !== lastRun) {
          lastRun = card.run;
          const rr = runOf(card.run);
          const n = rr ? rr.writes.filter((w) => w.sent).length : 0, d = rr ? rr.writes.filter((w) => w.status === "discarded").length : 0;
          nodes.push(el(`<div class="group" data-group="${card.run}"><span>${esc(runName(card.run))}</span><span class="g-n">${n} sent${d ? ` · ${d} discarded` : ""}</span></div>`));
        }
        const node = patchCard(card, col);
        if (card.col !== col) moved.push({ card, from: card.col, to: col });
        card.col = col;
        nodes.push(node);
      }
      if (!cards.length) nodes.push(el(`<div class="empty">${col === "in_progress" ? "Nothing running" : col === "needs_approval" ? "Nothing waiting on you" : col === "complete" ? "Nothing has reached a system yet" : "Nothing queued — run a job"}</div>`));
      for (const child of [...body.children]) {
        if (child.classList.contains("card") && child.classList.contains("leaving")) continue;
        if (!child.classList.contains("card") || !nodes.includes(child)) child.remove();
      }
      nodes.forEach((node, i) => { if (body.children[i] !== node) body.insertBefore(node, body.children[i] || null); });
      const n = cards.filter((c) => c.kind !== "job").length;
      const pill = section.querySelector(".count");
      pill.textContent = n; pill.classList.toggle("zero", !n);
    }
    renderApprovalHead();
    renderColnav(byCol);
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
    ghost.classList.remove("enter"); ghost.classList.add("ghost");
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
      ghosts.delete(card.key); ghost.remove(); node.style.visibility = "";
      if (col === "needs_approval") land(node);
    };
    ghosts.set(card.key, { ghost, timer: setTimeout(finish, MOVE_MS + 40), finish });
  }
  function cancelGhost(key) {
    const g = ghosts.get(key); if (!g) return;
    clearTimeout(g.timer); ghosts.delete(key); g.ghost.remove();
    const card = S.cards.get(key); if (card && card.el) card.el.style.visibility = "";
  }
  function land(node) {
    if (REDUCED || !node) return;
    node.classList.remove("land-amber"); void node.offsetWidth; node.classList.add("land-amber");
    setTimeout(() => node.classList.remove("land-amber"), 800);
  }

  // the approval column's header: what is waiting, and the one button that sends this job's decisions
  function renderApprovalHead() {
    const section = main.querySelector(`section.col[data-col="needs_approval"]`); if (!section) return;
    const head = section.querySelector(".col-head");
    const sum = head.querySelector(".sum"), act = head.querySelector(".act");
    const run = focusRun();
    const rr = run === null ? null : runOf(run);
    const waiting = rr ? [...S.cards.values()].filter((c) => c.kind === "chain" && c.run === run && cardColumn(c) === "needs_approval") : [];
    if (rr && waiting.length && !S.applying.has(run)) {
      const marks = waiting.map(mark);
      const nd = marks.filter((m) => m === "discard").length, ne = marks.filter((m) => m === "edit").length;
      const fl = waiting.filter((c) => flagged(c)).length;
      sum.innerHTML = `${esc(runName(run))}: <b>${waiting.length}</b> waiting${fl ? ` · <b class="amber">${fl}</b> flagged` : ""}${nd ? ` · <b class="red">${nd}</b> to discard` : ""}${ne ? ` · <b>${ne}</b> edited` : ""} · the rest is approved when you send`;
      sum.hidden = false;
      act.innerHTML = `<button class="btn primary small" data-action="approve" title="Send every decision for ${esc(runName(run))} in one go">Send decisions</button>`;
      act.querySelector("[data-action='approve']").onclick = () => sendDecisions(run);
    } else if (run !== null && S.applying.has(run)) {
      sum.innerHTML = `<span class="muted">Sending in dependency order…</span>`; sum.hidden = false; act.innerHTML = "";
    } else { sum.hidden = true; sum.innerHTML = ""; act.innerHTML = ""; }
  }
  function renderColnav(byCol) {
    const nav = $("colnav"); if (!nav) return;
    nav.innerHTML = COLS.map((col) => { const n = byCol[col].filter((c) => c.kind !== "job").length; return `<button class="btn ${col === "needs_approval" && n ? "amber-n" : ""}" data-col-nav="${col}"><span class="n">${n}</span>${esc(COL_TITLE[col].replace("Needs your approval", "Needs approval"))}</button>`; }).join("");
    nav.querySelectorAll("[data-col-nav]").forEach((b) => { b.onclick = () => scrollToCol(b.dataset.colNav); });
  }
  function scrollToCol(col, flash = true) {
    const section = main.querySelector(`section.col[data-col="${col}"]`); if (!section) return;
    if (NARROW()) $("board").scrollTo({ left: section.offsetLeft - $("board").offsetLeft, behavior: REDUCED ? "instant" : "smooth" });
    if (flash) { section.classList.remove("flash"); void section.offsetWidth; section.classList.add("flash"); }
  }

  // ------------------------------------------------------------------ the job bar and the stats strip
  function renderJobBar() {
    const bar = $("jobbar"); if (!bar) return;
    const v = S.view;
    const agents = v.agents || [];
    const live = agents.find((a) => a.kind !== "replay" && a.available);
    const conns = v.connectors || [];
    bar.innerHTML = `
      <form id="job-form" autocomplete="off">
        <input name="prompt" class="prompt" value="${esc(v.default_prompt || "")}" placeholder="What should the agent do?" aria-label="The job">
        <select name="agent" aria-label="Agent">${agents.map((a) => `<option value="${esc(a.id)}" ${!a.available ? "disabled" : ""} ${a.id === (live ? live.id : "replay") ? "selected" : ""} title="${esc(a.detail)}">${esc(a.label)}</option>`).join("") || `<option value="">no agent</option>`}</select>
        <details class="pick" id="conn-pick"><summary aria-label="Connectors">Connectors<span class="n" id="conn-n"></span></summary>
          <div class="menu">${conns.map((c) => `<label title="${esc(c.targets.length ? "targets: " + c.targets.join(", ") : c.description)}"><input type="checkbox" name="connectors" value="${esc(c.name)}"><span>${esc(human(c.name))}</span><span class="chip ${c.mode === "live" ? "released" : ""}">${esc(c.mode)}</span></label>`).join("") || `<span class="hint">none</span>`}<span class="hint">The ${esc(v.scenario)} systems are always on.</span></div>
        </details>
        <button class="btn primary" type="submit" id="b-run" ${S.running ? "disabled" : ""}>${S.running ? "Running…" : "Run"}</button>
        <div class="err" id="job-err" hidden></div>
      </form>`;
    const form = $("job-form");
    const n = () => { const k = form.querySelectorAll("input[name=connectors]:checked").length; $("conn-n").textContent = k ? ` ${k}` : ""; };
    form.querySelectorAll("input[name=connectors]").forEach((i) => { i.onchange = n; });
    document.addEventListener("click", (e) => { const d = $("conn-pick"); if (d && d.open && !d.contains(e.target)) d.open = false; });
    form.onsubmit = async (e) => {
      e.preventDefault();
      const req = { prompt: form.elements.prompt.value, agent: form.elements.agent.value, connectors: [...form.querySelectorAll("input[name=connectors]:checked")].map((i) => i.value) };
      const err = $("job-err"); err.hidden = true;
      const failed = await runJob(req);
      if (failed) { const e2 = $("job-err"); if (e2) { e2.textContent = failed.status === 409 ? `${failed.detail} — Reset, or look at the run on the board.` : failed.detail || failed.message; e2.hidden = false; } }
    };
  }
  function renderStrip() {
    const h = $("stats"); if (!h) return;
    const rr = latestRun();
    const sb = S.view.scoreboard || {};
    if (!rr) { h.innerHTML = `<span class="muted">No jobs yet — type one above and press Run.</span>`; return; }
    const c = rr.counts, u = rr.usage || {};
    const held = rr.writes.filter((w) => w.status === "held" && !w.blocked_by.length).length;
    const cost = u.replay ? `recorded · 0 tokens` : `${tokens(u.total_tokens || 0)} tokens · ${u.requests || 0} requests · ${(u.latency_s || 0).toFixed(1)} s`;
    h.innerHTML = `<span class="k">${esc(runName(rr.run))}</span>${rr.prompt ? `<span class="q" title="${esc(rr.prompt)}">“${esc(rr.prompt.length > 70 ? rr.prompt.slice(0, 70) + "…" : rr.prompt)}”</span>` : ""}<span class="v"><b>${c.checked}</b> checked</span><span class="v"><b class="green">${rr.writes.filter((w) => w.sent).length}</b> through</span><span class="v"><b class="amber">${held}</b> held</span>${c.caught ? `<span class="v"><b>${c.caught}</b> caught</span>` : ""}<span class="v muted">${esc(cost)}</span><span class="v muted" title="every job on this board">totals · ${sb.checked || 0} checked · ${sb.through || 0} through · ${sb.held || 0} held · ${tokens((sb.input_tokens || 0) + (sb.output_tokens || 0))} tokens · ${(sb.latency_s || 0).toFixed(1)} s</span>${rr.agent_text ? `<span class="said" title="what the agent said">${esc(rr.agent_text)}</span>` : ""}`;
  }
  function learnEvents(learned, run) { return learned.events.filter((e) => (run === undefined || e.run === run) && !(e.kind === "envelope" && REF_TOKEN.test(e.text))); }

  // ------------------------------------------------------------------ header
  function renderHeader() {
    const v = S.view;
    $("sub").textContent = v ? `${v.scenario}${S.team ? "" : " · shared team"}` : "";
    const run = v ? focusRun() : null;
    const held = run === null ? 0 : [...S.cards.values()].filter((c) => c.kind === "chain" && c.run === run && cardColumn(c) === "needs_approval").length;
    $("b-board").innerHTML = `Board${held ? `<span class="count">${held}</span>` : ""}`;
    const lock = !v || S.busy || S.running;
    for (const id of ["b-board", "b-learn", "b-rules", "b-settings", "b-reset"]) $(id).disabled = lock;
    const rules = v ? v.learned.rules.filter((r) => r.status === "active").length : 0;
    $("b-rules").innerHTML = `Rules${rules ? `<span class="count plain">${rules}</span>` : ""}`;
    const live = v ? (v.connectors || []).filter((c) => c.mode === "live").length : 0;
    $("b-settings").innerHTML = `Settings${live ? `<span class="count plain">${live} live</span>` : ""}`;
    $("b-board").classList.toggle("active", S.screen === "board");
    $("b-learn").classList.toggle("active", S.screen === "learning");
    const run1 = $("b-run"); if (run1) { run1.disabled = S.running || S.busy; run1.textContent = S.running ? "Running…" : "Run"; }
    $("foot-note").textContent = v ? `transcripts: ${v.transcripts_tag}` : "";
  }
  function notice(msg) {
    const old = main.querySelector(".notice"); if (old) old.remove();
    main.prepend(el(`<div class="notice amber" role="alert">${esc(msg)}</div>`));
  }

  // ------------------------------------------------------------------ the board screen
  function renderBoardScreen() {
    main.innerHTML = `
      <div id="jobbar"></div>
      <div id="stats"></div>
      <div id="colnav"></div>
      <div id="board">
        ${COLS.map((col) => `<section class="col" data-col="${col}"><div class="col-head"><h2>${esc(COL_TITLE[col])}</h2><span class="count" aria-live="off">0</span><div class="act"></div><div class="sum" hidden></div></div><div class="col-body"></div></section>`).join("")}
      </div>`;
    renderJobBar();
    renderStrip();
    renderBoard(false);
    renderHeader();
    if (NARROW()) scrollToCol("needs_approval", false);
  }
  function showBoard() { if (!boardMounted()) { setScreen("board"); renderBoardScreen(); } }

  // ------------------------------------------------------------------ clicks on a card
  function onCardClick(card, e) {
    const b = e.target.closest("[data-action]");
    if (b && card.el.contains(b)) {
      e.stopPropagation();
      const a = b.dataset.action;
      if (a === "open") openCard(card.key, b);
      else if (a === "rule-accept") setRuleChoice(card, true);
      else if (a === "rule-later") setRuleChoice(card, false);
      else if (a === "rule-undo") setRuleChoice(card, undefined);
      return;
    }
    if (card.kind !== "job") openCard(card.key, card.el.querySelector(".open"));
  }
  // a proposed rule's choice: true (yes), false (not now), "fine" (the person said it's fine: no rule, don't ask again),
  // or { rule, words, sentence } — the person's own rule, saved with the decisions in place of the proposal
  function setRuleChoice(card, value) {
    const ch = ruleChoices(card.run);
    if (value === undefined) delete ch[card.rule.id]; else ch[card.rule.id] = value;
    renderBoard(); if (S.sheet === "rules") fillRulesSheet();
  }

  // ------------------------------------------------------------------ decisions: collected on the board, sent once per job
  function decideLocal(card, action, args) {
    const p = pending(card.run);
    const ms = members(card);
    for (const w of ms) delete p[w.id];
    if (action === "discard") { const r = root(card); if (r && r.status === "held") p[r.id] = { action: "discard" }; }
    else if (action === "edit") { for (const w of ms) if (w.status === "held") p[w.id] = args && args[w.id] ? { action: "edit", args: args[w.id] } : { action: "approve" }; }
    else if (action === "approve") { for (const w of ms) if (w.status === "held") p[w.id] = { action: "approve" }; }
    S.errors = Object.fromEntries(Object.entries(S.errors).filter(([id]) => !ms.some((w) => w.id === id)));
    renderBoard(); renderHeader();
  }
  async function sendDecisions(run) {
    if (S.busy) return;
    const rr = runOf(run); if (!rr || rr.decided) return;
    const p = pending(run);
    const choices = ruleChoices(run);
    S.busy = true; renderHeader();
    // a rule in the person's own words is saved first (POST /rules); the proposal it replaces is declined with the decisions
    for (const v of Object.values(choices)) {
      if (!v || typeof v !== "object" || v.saved) continue;
      try { S.view.learned = await api("POST", "/rules", v.rule); v.saved = true; }
      catch (e) { S.busy = false; renderHeader(); notice(`Your rule was not saved: ${e.detail || e.message}`); return; }
    }
    const req = {
      run,
      decisions: Object.entries(p).map(([write_id, d]) => ({ write_id, action: d.action, ...(d.args ? { args: d.args } : {}) })),
      approve_rest: true,
      accept_rules: Object.entries(choices).filter(([, v]) => v === true).map(([id]) => id),
      reject_rules: Object.entries(choices).filter(([, v]) => v === false || v === "fine" || (v && typeof v === "object")).map(([id]) => id),
      accept_promotions: ["*"],
      decided_by: "person",
    };
    let res;
    try { res = await api("POST", "/decide", req); }
    catch (e) { S.busy = false; renderHeader(); notice(e.detail || e.message); return; }
    S.busy = false;
    S.errors = res.errors || {};
    delete S.decisions[run]; delete S.rules[run]; S.ruleText = {}; S.readings = {};
    S.view.runs[String(run)] = res.run; S.view.scoreboard = res.scoreboard; S.view.learned = res.learned;
    syncRules();
    closeDialog();
    // discarded chains fall out first; the rest goes to work and lands in dependency order with real ids where the placeholders were
    const cards = [...S.cards.values()].filter((c) => c.kind === "chain" && c.run === run);
    const sentIds = res.run.writes.filter((w) => w.sent).map((w) => w.id);
    for (const card of cards) for (const w of members(card)) {
      if (w.status === "discarded") card.disp[w.id] = "discarded";
      else if (w.status === "skipped") card.disp[w.id] = "skipped";
      else if (w.sent && card.disp[w.id] !== "sent") card.disp[w.id] = "active";
      else card.disp[w.id] = serverDisp(w);
    }
    S.applying.add(run);
    renderBoard();
    await sleep(REDUCED ? 0 : 300);
    const order = res.run.effects.map((e) => res.run.writes.find((x) => x.result_id === e.result_id && x.tool === e.tool)).filter((w) => w && sentIds.includes(w.id));
    for (const w of order) {
      const card = cards.find((c) => c.ids.includes(w.id));
      if (card && card.disp[w.id] !== "sent") { card.disp[w.id] = "sent"; renderBoard(); await sleep(REDUCED ? 0 : 120); }
    }
    for (const card of cards) for (const w of members(card)) card.disp[w.id] = serverDisp(w);
    S.applying.delete(run);
    if (Object.keys(S.errors).length) notice(`${Object.keys(S.errors).length} edit${Object.keys(S.errors).length === 1 ? " was" : "s were"} rejected by the tool's schema — open the card to see why. Everything else went out.`);
    renderStrip(); renderBoard(); renderHeader();
  }

  // ------------------------------------------------------------------ a job: its writes walk onto the board one at a time and wait for you
  async function walkRun(rr, budget) {
    const run = rr.run;
    dropCard(`job:${run}`);
    const cs = chains(rr).sort((a, b) => a.root.seq - b.root.seq);
    const cards = cs.map((c) => makeChainCard(rr, c, "pending"));
    renderBoard();
    const ws = rr.writes.slice().sort((a, b) => a.seq - b.seq);
    const dwell = REDUCED ? 0 : 300;
    const step = Math.max(50, Math.min(220, Math.floor((budget - 300 - dwell) / Math.max(1, ws.length))));
    await sleep(dwell);
    for (const w of ws) {
      const card = cards.find((c) => c.ids.includes(w.id));
      if (!card) continue;
      card.disp[w.id] = serverDisp(w);
      const next = card.ids.find((id) => card.disp[id] === "pending");
      if (next) card.disp[next] = "active";
      renderBoard();
      await sleep(step);
    }
    for (const card of cards) for (const w of members(card)) card.disp[w.id] = serverDisp(w);
    renderBoard();
  }
  async function runJob(req) {
    if (S.busy || S.running) return null;
    showBoard();
    S.running = true; renderHeader();
    const next = S.view.current_run + 1;
    makeJobCard(next, req.prompt || S.view.default_prompt || "job");
    renderBoard();
    let res;
    try { res = await api("POST", "/job", req); }
    catch (e) { S.running = false; dropCard(`job:${next}`); renderBoard(); renderHeader(); return e; }
    const v = S.view;
    v.runs[String(res.run.run)] = res.run; v.learned = res.learned; v.scoreboard = res.scoreboard; v.current_run = res.run.run;
    renderStrip(); renderHeader();
    await walkRun(res.run, 2400);
    S.running = false;
    syncRules(); renderStrip(); renderBoard(); renderHeader();
    return null;
  }
  async function reset() {
    if (S.busy || S.running) return;
    S.busy = true; renderHeader(); closeDialog();
    try { S.view = await api("POST", "/reset"); }
    catch (e) { S.busy = false; renderHeader(); notice(e.detail || e.message); return; }
    S.busy = false;
    S.decisions = {}; S.rules = {}; S.cascade = {}; S.errors = {}; S.ruleText = {}; S.readings = {}; S.applying = new Set(); S.latest = null;
    buildRegistry();
    setScreen("board"); renderBoardScreen();
  }

  // ------------------------------------------------------------------ the popup: why it is held, what the agent wants to do, and your decision
  function stepIndex(card, ph) { const i = members(card).findIndex((w) => w.placeholder === ph); return i >= 0 ? i + 1 : null; }
  function valueHtml(card, w, k, v) {
    if (typeof v === "string" && /^ph_[0-9a-f]{12}$/.test(v)) { const i = stepIndex(card, v); const src = members(card).find((x) => x.placeholder === v); return src && src.result_id ? `<code class="real">${esc(src.result_id)}</code>` : `<em class="ph">the id from step ${i || "?"}</em>`; }
    if (typeof v === "number") return `<span class="num">${esc(k.toLowerCase().includes("amount") ? money(v) : String(v))}</span>`;
    if (typeof v === "string") { const s = esc(v).replace(PH_RE, (m) => { const i = stepIndex(card, m); return `<em class="ph">[the id from step ${i || "?"}]</em>`; }); return ["account", "ref", "id", "email"].includes(shape(v)) ? `<code>${s}</code>` : s; }
    return esc(JSON.stringify(v));
  }
  function effectiveArgs(w) { const d = pending(w.run)[w.id]; return d && d.action === "edit" && d.args ? d.args : args(w); }
  function fieldsHtml(card, w) {
    return `<dl class="fields">${Object.entries(effectiveArgs(w)).map(([k, v]) => `<dt>${esc(human(k))}</dt><dd>${valueHtml(card, w, k, v)}</dd>`).join("")}</dl>`;
  }
  function editHtml(w) {
    const errs = S.errors[w.id] || [];
    return `<div class="edit" data-edit="${esc(w.id)}">${Object.entries(effectiveArgs(w)).map(([k, v]) => {
      const long = typeof v === "string" && (v.length > 60 || k === "body");
      const input = typeof v === "number" ? `<input name="${esc(k)}" type="number" step="any" value="${esc(v)}">` : long ? `<textarea name="${esc(k)}" rows="3">${esc(v)}</textarea>` : `<input name="${esc(k)}" value="${esc(v)}">`;
      return `<label><span>${esc(human(k))}</span>${input}</label>`;
    }).join("")}${errs.length ? `<div class="err">${errs.map(esc).join("<br>")}</div>` : ""}</div>`;
  }
  function readEdit(w) {
    const box = dlg.querySelector(`[data-edit="${CSS.escape(w.id)}"]`); if (!box) return null;
    const out = {};
    for (const [k, v] of Object.entries(effectiveArgs(w))) {
      const input = box.querySelector(`[name="${CSS.escape(k)}"]`);
      if (!input) { out[k] = v; continue; }
      out[k] = typeof v === "number" ? (input.value.trim() === "" || isNaN(Number(input.value)) ? input.value : Number(input.value)) : input.value;
    }
    return out;
  }
  // the flag as a diff: what the agent wants against what the layer knows
  function flagDiff(card, w, f) {
    const rows = (a, b) => `<div class="cmp"><div class="row bad"><span class="lab">${a[0]}</span><span class="val">${a[1]}</span></div><div class="row good"><span class="lab">${b[0]}</span><span class="val">${b[1]}</span></div></div>`;
    if (f.kind === "grounding") {
      if (f.detail === "conflict") return rows([`This write · ${esc(human(f.field))}`, `<code>${esc(f.value)}</code>`], [`On record${f.entity ? ` for ${esc(f.entity)}` : ""}`, (f.conflicts || []).map((c) => `<code>${esc(c)}</code>`).join(", ") || "—"]);
      return rows([`This write · ${esc(human(f.field))}`, `<code>${esc(f.value)}</code>`], ["What the agent read", "nothing with this value"]);
    }
    if (f.kind === "envelope") {
      const val = f.value ? (isNaN(Number(f.value)) ? esc(f.value) : esc(money(Number(f.value)))) : "—";
      const usual = f.detail === "unknown_value" || f.detail === "new_domain" ? "never approved before" : f.detail === "changed_value" ? `was ${f.bound ? `<code>${esc(f.bound)}</code>` : "different"}` : f.detail === "too_many" ? `at most ${esc(f.bound || "?")} in one job` : `${f.detail === "below_range" ? "at least" : "up to"} ${f.bound ? (isNaN(Number(f.bound)) ? esc(f.bound) : esc(money(Number(f.bound)))) : "?"}${f.ratio ? ` · this is ${esc(f.ratio)}×` : ""}`;
      return rows([`This write${f.field ? ` · ${esc(human(f.field))}` : ""}`, val], [`Usual${f.entity ? ` for ${esc(f.entity)}` : ""}`, usual]);
    }
    if (f.kind === "rule") {
      const rule = ruleById(f.rule_id);
      const text = String(args(w)[f.field] ?? "");
      let marked = esc(text);
      if (rule && rule.op === "matches") { try { marked = esc(text).replace(new RegExp(rule.value, "g"), (m) => `<mark>${m}</mark>`); } catch (e) { /* plain */ } }
      return `<div class="cmp"><div class="row bad"><span class="lab">This write · ${esc(human(f.field))}</span><span class="val text">${marked}</span></div><div class="row good"><span class="lab">Your rule</span><span class="val">${esc(rule ? ruleSentence(rule) : f.label)} · ${esc(runName(f.created_run))}</span></div></div>`;
    }
    if (f.kind === "memory") return rows([`This write${f.field ? ` · ${esc(human(f.field))}` : ""}`, `<code>${esc(f.value)}</code>`], ["Already sent", f.first_run ? esc(runName(f.first_run)) : "earlier"]);
    return "";
  }
  function fillDialog(card) {
    if (card.kind === "rule") { fillRuleDialog(card); return; }
    const ms = members(card), r = root(card), rr = runOf(card.run), col = cardColumn(card);
    const can = actionable(card);
    const m = mark(card);
    const flags = ms.flatMap((w) => w.flags.map((f) => ({ w, f })));
    const why = flags.length
      ? `<h3>Why it's held</h3>${flags.map(({ w, f }) => `<div class="why"><div class="reason">${esc(f.reason)}</div>${flagDiff(card, w, f)}</div>`).join("")}`
      : col === "needs_approval" && r ? `<h3>Why it's held</h3><div class="why"><div class="reason muted">Nothing looks wrong. ${esc(human(r.tool))} is still checked by a person: it has not been approved often enough to go out on its own.</div></div>` : "";
    const stepsHtml = ms.map((w, i) => {
      const d = card.disp[w.id] || "pending";
      const pd = pending(card.run)[w.id];
      const st = S.errors[w.id] ? `<span class="st red">edit rejected</span>` : pd && pd.action === "discard" ? `<span class="st red">will be discarded</span>` : pd && pd.action === "edit" ? `<span class="st green">edited · will be sent</span>` : pd ? `<span class="st green">will be sent</span>` : d === "sent" ? `<span class="st green">sent · <code>${esc(w.result_id)}</code></span>` : d === "discarded" ? `<span class="st red">discarded</span>` : d === "skipped" ? `<span class="st red">skipped</span>` : d === "blocked" ? `<span class="st amber">waits for step ${stepIndex(card, w.depends_on[0]) || 1}</span>` : d === "held" ? `<span class="st amber">held</span>` : d === "active" ? `<span class="st">sending…</span>` : `<span class="st">not yet attempted</span>`;
      const editing = S.editing === w.id;
      const editBtn = can && w.status === "held" && !editing ? `<button class="btn ghost small" data-action="edit" data-write="${esc(w.id)}">Edit</button>` : "";
      const delivery = d === "sent" && deliveryOf(w) ? `<div class="note">${esc(deliveryOf(w).status)}${deliveryOf(w).url ? ` · <a href="${esc(deliveryOf(w).url)}" target="_blank" rel="noopener">open</a>` : ""}${deliveryOf(w).channel ? ` · ${esc(deliveryOf(w).channel)}` : ""}</div>` : "";
      return `<div class="stp"><div class="sh"><span class="n">${i + 1}</span><span class="tool">${esc(human(w.tool))}</span>${st}<span class="spacer"></span>${editBtn}</div>${editing ? editHtml(w) : fieldsHtml(card, w)}${!editing && S.errors[w.id] ? `<div class="err">${S.errors[w.id].map(esc).join("<br>")}</div>` : ""}${delivery}<details class="raw"><summary>Details</summary><pre>${esc(w.tool)}(${esc(JSON.stringify(w.args, null, 2))})${w.edited_args ? `\n\nas edited:\n${esc(JSON.stringify(w.edited_args, null, 2))}` : ""}${w.final_args ? `\n\nas sent:\n${esc(JSON.stringify(w.final_args, null, 2))}` : ""}\n\nplaceholder ${esc(w.placeholder)}${w.result_id ? ` → ${esc(w.result_id)}` : ""}</pre></details></div>`;
    }).join("");
    const skipNames = skippedIds(card).map((id) => { const w = ms.find((x) => x.id === id); return w ? human(w.tool).toLowerCase() : id; });
    let actions = "";
    if (can) {
      if (S.editing) actions = `<button class="btn primary" data-action="save-edit">Keep these changes</button><button class="btn ghost" data-action="cancel-edit">Cancel</button><span class="note">The change is checked against the tool's schema when you send the decisions.</span>`;
      else actions = `<button class="btn primary ${m === "approve" || m === "edit" ? "chosen" : ""}" data-action="approve-card">${m === "approve" || m === "edit" ? "✓ Approved" : `Approve${ms.filter((w) => w.status === "held").length > 1 ? " all steps" : ""}`}</button><button class="btn danger ${m === "discard" ? "chosen" : ""}" data-action="discard">${m === "discard" ? "✓ Discarding" : "Discard"}</button>${m ? `<button class="btn ghost" data-action="undo">Undo</button>` : ""}<span class="note">${r && r.status === "held" ? (skipNames.length ? `Discarding also skips ${skipNames.join(" and ")}. ` : "Nothing else depends on it. ") : ""}Nothing is sent until you press Send decisions on the board; anything you leave untouched is approved then.</span>`;
    } else if (col === "complete") actions = `<span class="note">${r && r.status === "discarded" ? "Discarded — it never reached a system." : "Done — it reached the system with the ids above."}</span>`;
    else if (S.applying.has(card.run)) actions = `<span class="note">Sending…</span>`;
    else if (rr && rr.decided && col === "needs_approval") actions = `<span class="note">Decided, but not delivered${Object.keys(S.errors).some((id) => ms.some((w) => w.id === id)) ? " — the edit was rejected by the tool's schema; the run is closed, so Reset to try again" : ""}.</span>`;
    dlg.innerHTML = `
      <div class="dlg-head"><span class="title" id="dlg-title">${esc(chainTitle(card))}</span><span class="amount">${esc(chainAmount(card))}</span>
        <span class="meta"><span>${esc(runName(card.run))}</span><span class="${col === "needs_approval" ? "amber" : col === "complete" ? "green" : "muted"}">${esc(COL_TITLE[col])}</span><span class="muted">${esc(rr ? agentLabel(rr.agent) || rr.model : "")}</span></span>
        <button class="close" data-action="close" aria-label="Close">×</button></div>
      <div class="dlg-body">
        ${why}
        <h3>What the agent wants to do</h3>
        ${stepsHtml}
      </div>
      ${actions ? `<div class="dlg-actions">${actions}</div>` : ""}`;
    bindDialog(card);
  }
  // ---- the rule popup: what you took out, first; then the rule in your words, read back by the layer before you accept it
  // the layer's own proposal needs no round trip: its reading is known
  function proposalReading(rule, text) {
    return { text, intent: "hold", rule: { tool: rule.tool, field: rule.field, op: rule.op, value: rule.value, label: rule.label || null }, tool: rule.tool, field: rule.field, sentence: readingSentence(rule), pattern: rule.op === "matches" ? rule.value : null, problem: null, same_as: rule.id, same_as_status: rule.status === "active" ? "active" : "proposed" };
  }
  function ruleTextOf(card, rule) {
    if (S.ruleText[rule.id] === undefined) { const ch = ruleChoices(card.run)[rule.id]; S.ruleText[rule.id] = ch && typeof ch === "object" ? ch.words : ruleWords(rule); }
    return S.ruleText[rule.id];
  }
  function currentReading(card, rule) {
    const text = ruleTextOf(card, rule);
    if (text.trim() === ruleWords(rule).trim()) return proposalReading(rule, text);
    const r = S.readings[rule.id];
    return r && r.text === text ? r.reading : null;
  }
  // other things the person might mean here: the patterns the layer's reader knows (learning.RULE_PATTERNS), and the opposite
  function ruleChips(rule) {
    const out = [];
    for (const alt of ["a sort code", "an account number", "a currency amount"]) if (alt !== rule.label) out.push({ label: `contains ${alt}`, words: `Always hold ${human(rule.tool)} when ${human(rule.field).toLowerCase()} contains ${alt}` });
    out.push({ label: `it's fine`, words: `From now on it's fine if ${human(rule.field).toLowerCase()} contains ${valueWords(rule)}` });
    return out.slice(0, 3);
  }
  function readbackHtml(rule, rd) {
    if (!rd) return `<span class="rb muted">Reading…</span>`;
    if (rd.intent === "unclear") return `<span class="rb bad">Not read as a rule yet.</span><span class="rb-note">${esc(rd.problem || "")}</span>`;
    const what = `<span class="rb">→ <b>${esc(rd.sentence)}</b></span>`;
    const t = rd.tool === "*" ? "write" : human(rd.tool || rule.tool).toLowerCase();
    const same = rd.same_as ? ruleById(rd.same_as) : null;
    if (rd.intent === "hold") {
      if (rd.same_as === rule.id && rule.status === "proposed") return `${what}<span class="rb-note">The layer's proposal, as it stands. Every future ${esc(t)} that matches is held for you, whatever the agent and whatever it has learned.</span>`;
      if (rd.same_as_status === "active") return `${what}<span class="rb-note">Already a live rule${same ? ` (${esc(ruleOrigin(same))})` : ""}. Nothing to add.</span>`;
      return `${what}<span class="rb-note">Your own rule. It replaces the proposed one (${esc(valueWords(rule))}) and is saved with this job's decisions.</span>`;
    }
    if (rd.same_as === rule.id && rule.status === "proposed") return `${what}<span class="rb-note">No rule. Your edit still applies to this message, and the layer won't ask about ${esc(valueWords(rule))} in ${esc(human(rule.tool).toLowerCase())} again.</span>`;
    if (rd.same_as_status === "active") return `${what}<span class="rb-note">That is a live rule already${same ? ` (${esc(ruleOrigin(same))})` : ""}. Turning a rule off isn't built yet.</span>`;
    return `${what}<span class="rb-note">Nothing holds that today, so nothing would change.</span>`;
  }
  // the primary button for this reading: what it says and whether pressing it does anything
  function yesFor(rule, rd) {
    if (!rd || rd.intent === "unclear") return { label: "Yes, always", on: false };
    if (rd.intent === "hold") return { label: "Yes, always", on: rd.same_as_status !== "active" };
    return { label: "Yes, it's fine", on: rd.same_as === rule.id && rule.status === "proposed" };
  }
  function chosenNow(card, rule, rd) {
    const ch = ruleChoices(card.run)[rule.id];
    if (!rd || ch === undefined || ch === false) return false;
    if (ch === true) return rd.intent === "hold" && rd.same_as === rule.id;
    if (ch === "fine") return rd.intent === "allow" && rd.same_as === rule.id;
    return rd.intent === "hold" && !!rd.rule && JSON.stringify(rd.rule) === JSON.stringify(ch.rule);
  }
  let readTimer = null;
  function scheduleReading(card, rule, delay = 250) {
    clearTimeout(readTimer);
    const text = S.ruleText[rule.id];
    if (currentReading(card, rule)) { refreshReadback(card, rule); return; }
    readTimer = setTimeout(async () => {
      let reading;
      try { reading = await api("POST", "/rules/read", { text, tool: rule.tool, field: rule.field }); }
      catch (e) { reading = { text, intent: "unclear", problem: e.detail || e.message }; }
      if (S.ruleText[rule.id] !== text) return; // they kept typing; a newer reading is on its way
      S.readings[rule.id] = { text, reading };
      refreshReadback(card, rule);
    }, delay);
  }
  function refreshReadback(card, rule) {
    const box = $("rule-readback"); if (!box || S.opened !== card.key) return;
    const rd = currentReading(card, rule);
    box.classList.toggle("pending", !rd);
    box.innerHTML = readbackHtml(rule, rd);
    const yes = yesFor(rule, rd), chosen = chosenNow(card, rule, rd);
    const b = dlg.querySelector("[data-action='rule-yes']");
    if (b) { b.disabled = !yes.on; b.textContent = (chosen ? "✓ " : "") + yes.label; b.classList.toggle("chosen", chosen); }
  }
  function applyReading(card) {
    const rule = ruleById(card.rule.id) || card.rule;
    const rd = currentReading(card, rule);
    if (!rd || !yesFor(rule, rd).on) return;
    if (rd.intent === "hold") setRuleChoice(card, rd.same_as === rule.id ? true : { rule: rd.rule, words: S.ruleText[rule.id], sentence: rd.sentence });
    else setRuleChoice(card, "fine");
    fillDialog(card);
  }
  function fillRuleDialog(card) {
    const rule = ruleById(card.rule.id) || card.rule;
    const rr = runOf(card.run);
    const { src, beforeHtml, after, fragHtml } = ruleDiff(rule);
    const choice = ruleChoices(card.run)[rule.id];
    const open = rule.status === "proposed" && !(rr && rr.decided);
    const text = ruleTextOf(card, rule);
    const rd = currentReading(card, rule);
    const field = human(rule.field || "any field").toLowerCase();
    const catchHtml = src
      ? `<div class="catch">
          <div class="catch-line">You took ${esc(valueWords(rule))} out of the ${esc(field)} of this ${esc(human(src.tool).toLowerCase())}.</div>
          ${fragHtml ? `<div class="frag">${fragHtml}</div>` : ""}
          <div class="catch-why">${src.flags.length
            ? `The layer held this for another reason and did not check for ${esc(valueWords(rule))}; you caught that when you edited it. A rule means the layer checks for it itself from now on, so you don't have to.`
            : `The layer's checks did not catch this; you did, when you edited it. A rule means the layer checks for ${esc(valueWords(rule))} itself from now on, so you don't have to.`}</div>
          <details class="whole"><summary>The whole ${esc(field)}, before and after your edit</summary><div class="diff"><div class="side before"><span class="lab">before</span>${beforeHtml}</div><div class="side after"><span class="lab">after your edit</span>${esc(after)}</div></div></details>
        </div>`
      : `<div class="catch"><div class="catch-line">${esc(ruleSentence(rule))}</div><div class="catch-why">${esc(ruleOrigin(rule))}</div></div>`;
    const chips = open ? ruleChips(rule).map((c) => `<button class="chip as-btn" type="button" data-action="rule-words" data-words="${esc(c.words)}">${esc(c.label)}</button>`).join("") : "";
    const yes = yesFor(rule, rd), chosen = chosenNow(card, rule, rd);
    const actions = rule.status === "active" ? `<span class="note green">Rule on — applies from the next write.</span>`
      : rule.status === "rejected" ? `<span class="note">Not a rule. The edit itself still applied.</span>`
      : !open ? `<span class="note">This job's decisions were sent; the rule stayed as it was.</span>`
      : `<button class="btn amber ${chosen ? "chosen" : ""}" data-action="rule-yes" ${yes.on ? "" : "disabled"}>${chosen ? "✓ " : ""}${esc(yes.label)}</button><button class="btn ghost ${choice === false ? "chosen" : ""}" data-action="rule-later">${choice === false ? "✓ Not now" : "Not now"}</button>${choice !== undefined ? `<button class="btn ghost" data-action="rule-undo">Undo</button>` : ""}<span class="note">Sent with this job's decisions. Nothing changes until you press Send decisions on the board.</span>`;
    dlg.innerHTML = `
      <div class="dlg-head"><span class="title" id="dlg-title">Make this a rule?</span><span class="meta"><span>${esc(runName(card.run))}</span><span class="muted">${esc(ruleSource(rule))}</span></span><button class="close" data-action="close" aria-label="Close">×</button></div>
      <div class="dlg-body">
        ${catchHtml}
        <h3>The rule, in your words</h3>
        <div class="rule-words">
          <textarea id="rule-words" rows="2" spellcheck="false" aria-label="The rule, in your words" ${open ? "" : "readonly"}>${esc(text)}</textarea>
          <div class="readback ${rd ? "" : "pending"}" id="rule-readback" aria-live="polite">${readbackHtml(rule, rd)}</div>
          ${chips ? `<div class="chips"><span>Or try:</span>${chips}</div>` : ""}
        </div>
      </div>
      <div class="dlg-actions">${actions}</div>`;
    bindDialog(card);
    const box = $("rule-words");
    if (box && open) {
      box.oninput = () => { S.ruleText[rule.id] = box.value; refreshReadback(card, rule); scheduleReading(card, rule); };
      if (!rd) scheduleReading(card, rule, 0);
    }
  }
  function bindDialog(card) {
    dlg.querySelectorAll("[data-action]").forEach((b) => {
      b.onclick = async (e) => {
        e.stopPropagation();
        const a = b.dataset.action;
        if (a === "close") closeDialog();
        else if (a === "discard") { decideLocal(card, "discard"); closeDialog(); }
        else if (a === "approve-card") { decideLocal(card, "approve"); closeDialog(); }
        else if (a === "undo") { decideLocal(card, null); fillDialog(card); }
        else if (a === "edit") { S.editing = b.dataset.write; fillDialog(card); }
        else if (a === "cancel-edit") { S.editing = null; fillDialog(card); }
        else if (a === "save-edit") { const w = memberOf(card, S.editing); const edits = {}; if (w) edits[w.id] = readEdit(w); S.editing = null; decideLocal(card, "edit", edits); fillDialog(card); }
        else if (a === "rule-accept") { setRuleChoice(card, true); fillDialog(card); }
        else if (a === "rule-later") { setRuleChoice(card, false); fillDialog(card); }
        else if (a === "rule-undo") { setRuleChoice(card, undefined); fillDialog(card); }
        else if (a === "rule-yes") applyReading(card);
        else if (a === "rule-words") { const rule = ruleById(card.rule.id) || card.rule; S.ruleText[rule.id] = b.dataset.words; fillDialog(card); const box = $("rule-words"); if (box) box.focus({ preventScroll: true }); }
      };
    });
  }
  let opener = null;
  async function openCard(key, from) {
    const card = S.cards.get(key); if (!card || card.kind === "job") return;
    S.opened = key; S.editing = null; S.sheet = null; opener = from || null;
    dlg.dataset.kind = "card";
    fillDialog(card);
    dlg.classList.remove("closing");
    if (!dlg.open) dlg.showModal();
    const close = dlg.querySelector(".close"); if (close) close.focus({ preventScroll: true });
    // the cascade preview for a held root: what a discard would take with it
    const r = root(card);
    if (card.kind === "chain" && r && r.status === "held" && S.cascade[card.rootId] === undefined) {
      try { const res = await api("GET", `/cascade/${card.run}/${encodeURIComponent(card.rootId)}`); S.cascade[card.rootId] = res.skipped; } catch (e) { S.cascade[card.rootId] = []; }
      if (S.opened === key && dlg.open && !S.editing) fillDialog(card);
    }
  }
  function closeDialog() {
    if (!dlg.open) return;
    const done = () => {
      dlg.classList.remove("closing"); if (dlg.open) dlg.close();
      dlg.innerHTML = ""; delete dlg.dataset.kind;
      S.opened = null; S.sheet = null; S.editing = null;
      if (opener && opener.isConnected) opener.focus({ preventScroll: true });
      opener = null;
    };
    if (REDUCED) { done(); return; }
    dlg.classList.add("closing");
    setTimeout(done, 170);
  }
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); closeDialog(); });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) closeDialog(); });

  // ------------------------------------------------------------------ the sheets: the rules, the settings
  function openSheet(kind, from) {
    S.sheet = kind; S.opened = null; S.editing = null; opener = from || null;
    dlg.dataset.kind = kind;
    if (kind === "rules") fillRulesSheet(); else fillSettingsSheet();
    dlg.classList.remove("closing");
    if (!dlg.open) dlg.showModal();
    const first = dlg.querySelector(".close"); if (first) first.focus({ preventScroll: true });
  }
  const OPS = [["matches", "contains"], ["in", "is one of"], ["not_in", "is not one of"], ["gt", "is over"], ["lt", "is under"]];
  function head(title, sub) { return `<div class="dlg-head"><span class="title" id="dlg-title">${esc(title)}</span>${sub ? `<span class="meta"><span class="muted">${esc(sub)}</span></span>` : ""}<button class="close" data-action="close" aria-label="Close">×</button></div>`; }
  async function fillRulesSheet() {
    const learned = S.view.learned;
    const active = learned.rules.filter((r) => r.status === "active");
    const proposed = learned.rules.filter((r) => r.status === "proposed");
    const run = focusRun();
    dlg.innerHTML = `${head("Rules", "a rule holds a write for you whatever the agent and whatever it has learned")}
      <div class="dlg-body">
        ${proposed.length ? `<h3>Proposed from an edit</h3>${proposed.map((r) => { const ch = run !== null ? ruleChoices(run)[r.id] : undefined; const own = ch && typeof ch === "object"; const yes = ch === true || own, no = ch === false || ch === "fine"; return `<div class="rule"><div class="rs">${esc(own ? ch.sentence : ruleSentence(r))}</div><div class="ro">${esc(own ? `your words, in place of: ${ruleSentence(r).toLowerCase()}` : ruleOrigin(r))}${run === null ? " · decided with the next job" : ""}</div>${run !== null ? `<div class="ra"><button class="btn amber small ${yes ? "chosen" : ""}" data-rule-accept="${esc(r.id)}">${yes ? "✓ Yes, always" : "Yes, always"}</button><button class="btn ghost small ${no ? "chosen" : ""}" data-rule-reject="${esc(r.id)}">${no ? "✓ Not now" : "Not now"}</button><span class="hint">sent with ${esc(runName(run))}'s decisions · open the card to put it in your own words</span></div>` : ""}</div>`; }).join("")}` : ""}
        <h3>Active</h3>
        ${active.length ? active.map((r) => `<div class="rule"><div class="rs">${esc(ruleSentence(r))}</div><div class="ro">${esc(ruleOrigin(r))}</div></div>`).join("") : `<div class="note">No rules yet. Add one below, or accept one the layer proposes after an edit.</div>`}
        <h3>Add a rule</h3>
        <form class="rule-form" id="rule-form" autocomplete="off">
          <span class="lab">Hold</span><select name="tool" aria-label="tool"></select>
          <span class="lab">when</span><select name="field" aria-label="field"></select>
          <select name="op" aria-label="condition">${OPS.map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}</select>
          <input name="value" placeholder="a pattern, a number, or a, b, c" aria-label="value">
          <button class="btn small primary" type="submit">Add</button>
          <div class="err" hidden></div>
        </form>
        <div class="hint">For example: hold <b>create payout</b> when <b>amount</b> is over <b>10000</b> · hold <b>send remittance email</b> when <b>body</b> contains <b>\\d{2}-\\d{2}-\\d{2}</b> · hold <b>post message</b> when <b>channel</b> is one of <b>alerts</b>.</div>
      </div>`;
    bindSheet();
    dlg.querySelectorAll("[data-rule-accept]").forEach((b) => { b.onclick = () => { if (run !== null) { ruleChoices(run)[b.dataset.ruleAccept] = true; renderBoard(); fillRulesSheet(); } }; });
    dlg.querySelectorAll("[data-rule-reject]").forEach((b) => { b.onclick = () => { if (run !== null) { ruleChoices(run)[b.dataset.ruleReject] = false; renderBoard(); fillRulesSheet(); } }; });
    await bindRuleForm();
  }
  function ruleValue(op, raw) {
    const s = raw.trim();
    if (op === "gt" || op === "lt") return s !== "" && !isNaN(Number(s)) ? Number(s) : s;
    if (op === "in" || op === "not_in") return s.split(",").map((x) => x.trim()).filter(Boolean);
    return s;
  }
  async function bindRuleForm() {
    const form = $("rule-form"); if (!form) return;
    if (!S.scenario) { try { S.scenario = await api("GET", "/scenario"); } catch (e) { console.error(e); return; } }
    if (!document.body.contains(form)) return;
    const tool = form.elements.tool, field = form.elements.field, op = form.elements.op, value = form.elements.value, err = form.querySelector(".err");
    const tools = S.scenario.tools.filter((t) => t.kind === "write").map((t) => ({ name: t.name, fields: Object.keys((t.args_schema && t.args_schema.properties) || {}) }));
    for (const c of S.view.connectors || []) for (const name of c.tools) if (!name.startsWith("list_") && !tools.some((t) => t.name === name)) tools.push({ name, fields: [] });
    tool.innerHTML = tools.map((t) => `<option value="${esc(t.name)}">${esc(human(t.name))}</option>`).join("");
    const fillFields = () => {
      const t = tools.find((x) => x.name === tool.value);
      field.innerHTML = (t && t.fields.length ? t.fields : ["*"]).map((n) => `<option value="${esc(n)}">${esc(n === "*" ? "any field" : human(n))}</option>`).join("");
    };
    fillFields(); tool.onchange = fillFields;
    form.onsubmit = async (ev) => {
      ev.preventDefault(); err.hidden = true;
      const req = { tool: tool.value, field: field.value === "*" ? "" : field.value, op: op.value, value: ruleValue(op.value, value.value) };
      let res;
      try { res = await api("POST", "/rules", req); }
      catch (e) { err.textContent = e.detail || e.message; err.hidden = false; return; }
      S.view.learned = res;
      renderHeader(); if ($("learned-events")) fillLearned(res);
      fillRulesSheet();
    };
  }
  function fillSettingsSheet() {
    const conns = S.view.connectors || [];
    dlg.innerHTML = `${head("Settings", "your team's board: its key, and what a job may write to")}
      <div class="dlg-body">
        <h3>Team</h3>
        <div class="team">
          ${S.team ? `<div class="kv">This board's key: <code id="team-key">${esc(S.team)}</code> <button class="btn ghost small" data-team="copy">Copy</button></div><div class="hint">Paste it on another device to see the same board. Connector settings and everything the layer has learned stay with this key.</div>`
                   : `<div class="kv">You are on the shared team: everyone without a key sees this board, and live connector settings are refused.</div>`}
          <div class="ra"><button class="btn small ${S.team ? "" : "primary"}" data-team="new">${S.team ? "New key" : "Use your own key"}</button><input id="team-paste" placeholder="paste a key from another device"><button class="btn small" data-team="use">Use</button>${S.team ? `<button class="btn ghost small" data-team="shared">Back to the shared team</button>` : ""}</div>
        </div>
        <h3>Connectors</h3>
        ${conns.map((c) => `<div class="conn" data-conn="${esc(c.name)}">
          <div class="ch"><span class="cn">${esc(human(c.name))}</span><span class="chip ${c.mode === "live" ? "released" : ""}">${esc(c.mode === "live" ? "live" : "demo")}</span><span class="hint">${esc(c.tools.map(human).join(" · "))}</span></div>
          <div class="cd">${esc(c.description)}</div>
          ${c.targets.length ? `<div class="ct">Targets: ${c.targets.map((t) => `<code>${esc(t)}</code>`).join(" ")}</div>` : ""}
          ${Object.keys(c.settings).length ? `<details ${c.mode === "live" ? "open" : ""}><summary>${c.mode === "live" ? "Configured · change" : "Use your own"}</summary><form class="cset" data-conn-form="${esc(c.name)}">
            ${Object.entries(c.settings).map(([k, hint]) => `<label class="block"><span>${esc(human(k))}</span>${k === "channels" || k === "endpoints" ? `<textarea name="${esc(k)}" rows="2" placeholder="${esc(hint)}"></textarea>` : `<input name="${esc(k)}" placeholder="${esc(hint)}" ${/key|token/.test(k) ? 'type="password"' : ""}>`}</label>`).join("")}
            <div class="err" hidden></div>
            <div class="ra"><button class="btn primary small" type="submit">Save</button><button class="btn ghost small" type="button" data-conn-demo="${esc(c.name)}">Back to demo</button><span class="hint">Stored for your team only; a key is never shown again.</span></div>
          </form></details>` : `<div class="hint">Always simulated.</div>`}
        </div>`).join("") || `<div class="note">No connectors on this deployment.</div>`}
      </div>`;
    bindSheet();
    dlg.querySelectorAll("[data-team]").forEach((b) => {
      b.onclick = async () => {
        const a = b.dataset.team;
        if (a === "copy") { try { await navigator.clipboard.writeText(S.team); b.textContent = "Copied"; } catch (e) { /* no clipboard */ } return; }
        if (a === "new") setTeam(crypto.randomUUID());
        else if (a === "use") { const k = $("team-paste").value.trim(); if (!k) return; setTeam(k); }
        else if (a === "shared") setTeam(null);
        await reloadState();
        fillSettingsSheet();
      };
    });
    dlg.querySelectorAll("form[data-conn-form]").forEach((form) => {
      form.onsubmit = (e) => { e.preventDefault(); saveConnector(form.dataset.connForm, form, false); };
      form.querySelector("[data-conn-demo]").onclick = () => saveConnector(form.dataset.connForm, form, true);
    });
  }
  async function reloadState() {
    try { S.view = await api("GET", "/state"); } catch (e) { notice(e.detail || e.message); return; }
    S.decisions = {}; S.rules = {}; S.cascade = {}; S.errors = {}; S.ruleText = {}; S.readings = {};
    buildRegistry();
    if (S.screen === "board") { renderBoardScreen(); } else renderLearning();
  }
  function parseLines(text) {
    // "name = value" per line → {name: value}; a JSON value becomes an object (the http connector's endpoints)
    const out = {};
    for (const line of String(text).split("\n")) {
      const m = line.match(/^\s*([^=:\s]+)\s*[=:]\s*(.+?)\s*$/); if (!m) continue;
      let v = m[2];
      if (v.startsWith("{")) { try { v = JSON.parse(v); } catch (e) { /* keep as text */ } }
      out[m[1]] = v;
    }
    return out;
  }
  async function saveConnector(name, form, demo) {
    const err = form.querySelector(".err"); err.hidden = true;
    const body = {};
    if (!demo) for (const input of form.querySelectorAll("[name]")) {
      const k = input.name, v = input.value;
      if (!v.trim()) continue;
      body[k] = k === "channels" || k === "endpoints" ? parseLines(v) : v.trim();
    }
    let view;
    try { view = await api("POST", `/connectors/${encodeURIComponent(name)}`, body); }
    catch (e) { err.textContent = e.status === 403 ? "Live settings need your own team key — set one above." : e.detail || e.message; err.hidden = false; return; }
    S.view.connectors = (S.view.connectors || []).map((c) => (c.name === name ? view : c));
    fillSettingsSheet(); renderHeader(); if ($("jobbar")) renderJobBar();
  }
  function bindSheet() {
    dlg.querySelectorAll("[data-action='close']").forEach((b) => { b.onclick = (e) => { e.stopPropagation(); closeDialog(); }; });
  }

  // ------------------------------------------------------------------ the learning page: what it has learned, as charts and a record
  function fillLearned(learned) {
    const ev = $("learned-events"), ents = $("learned-ents"), lad = $("learned-ladder");
    if (!ev) return;
    const rel = learned.ladder.filter((l) => l.level === "released");
    const checked = learned.ladder.filter((l) => l.level !== "released");
    const lh = (title, n) => `<div class="lh">${title}<span class="n">${n}</span></div>`;
    const row = (name, meta) => `<div class="lrow"><span class="ln">${esc(name)}</span><span class="lm">${esc(meta)}</span></div>`;
    lad.innerHTML =
      (rel.length ? lh("Sent without review", rel.length) + rel.map((l) => row(human(l.tool), `${l.released_run ? `since ${runName(l.released_run)} · ` : ""}${l.approved} approved`)).join("") : "") +
      (checked.length ? lh("Still checked by you", checked.length) + checked.map((l) => row(human(l.tool), `${l.approved} approved${l.discarded ? ` · ${l.discarded} discarded` : ""}`)).join("") : lh("Still checked by you", 0) + `<div class="hint">Every tool starts here. After enough approvals across enough jobs, the layer proposes to send it without asking.</div>`);
    const active = learned.rules.filter((r) => r.status === "active");
    $("learned-rules").innerHTML = active.length ? lh("Your rules", active.length) + active.map((r) => `<div class="lrule"><div class="ln">${esc(ruleSentence(r))}</div><div class="lm">${esc(ruleOrigin(r))}</div></div>`).join("") : "";
    ev.innerHTML = "";
    const events = learnEvents(learned).slice().reverse();
    for (const e of events) {
      const text = e.kind === "promotion" && e.text.includes("now sent") ? e.text.replace(/\s*\(.*\)$/, "") : e.text;
      let group = ev.querySelector(`.evg[data-run="${e.run}"] .evi`);
      if (!group) { const wrap = el(`<div class="evg" data-run="${e.run}"><div class="evk">${esc(label().slice(0, 3))} ${e.run}</div><div class="evi"></div></div>`); ev.appendChild(wrap); group = wrap.lastElementChild; }
      group.appendChild(el(`<div class="ev ${esc(e.kind)}">${esc(text)}</div>`));
    }
    const hh = $("learned-hh"); if (hh) hh.hidden = !ev.children.length;
    if (!ents) return;
    const byValue = {};
    for (const x of learned.entities) {
      if (REF_TOKEN.test(x.value)) continue;
      const accounts = Object.entries(x.sets).filter(([k, s]) => k !== x.field && s.values.every((v) => shape(v) === "account")).map(([, s]) => s.values.join(", "));
      const range = Object.entries(x.ranges)[0];
      const score = (accounts.length ? 2 : 0) + (range ? 1 : 0);
      const cur = byValue[x.value];
      if (!cur || score > cur.score) byValue[x.value] = { x, accounts, range, score };
    }
    const rows = Object.values(byValue);
    ents.innerHTML = rows.length ? lh("What is usual", rows.length) + rows.map(({ x, accounts, range }) =>
      `<div class="ent"><span class="nm">${esc(x.value)}</span><span class="rg">${range ? `${esc(human(range[0]).toLowerCase())} usually ${money0(range[1].observed_min)}–${money0(range[1].observed_max)}` : `${x.n} approved`}${accounts.length ? ` · ${esc(accounts[0])}` : ""}</span></div>`).join("") : "";
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
    Object.assign(Chart.defaults.plugins.tooltip, { backgroundColor: v("--obsidian"), borderColor: v("--graphite"), borderWidth: 1, titleColor: v("--mist"), bodyColor: v("--fog"), cornerRadius: 6, padding: 10, displayColors: false });
    return { amber: v("--amber"), green: v("--green"), red: v("--red"), fog: v("--fog"), mist: v("--mist"), carbon: v("--carbon"), graphite: v("--graphite") };
  }
  function renderLearning() {
    setScreen("learning");
    closeDialog();
    for (const card of S.cards.values()) if (card.el) { cancelGhost(card.key); card.el.remove(); card.col = null; }
    main.innerHTML = `
      <div class="cols">
        <div class="charts">
          <div class="panel chart"><h2>Held for you per job (% of writes checked)</h2><div class="chart-box" id="ch-line"></div></div>
          <div class="panel chart"><h2>What you decided, by tool (writes)</h2><div class="chart-box" id="ch-tools"></div></div>
          <div class="panel chart"><h2>Usual amounts by name (min–max approved)</h2><div class="chart-box" id="ch-env"></div></div>
        </div>
        <div class="panel learned"><h2>What it has learned</h2>
          <div id="learned-ladder"></div>
          <div id="learned-rules"></div>
          <div id="learned-ents"></div>
          <div class="lh" id="learned-hh" hidden>History, newest first</div>
          <div class="events" id="learned-events"></div>
        </div>
      </div>`;
    const T = themeCharts();
    drawHeldLine(T); drawTools(T); drawEnv(T);
    fillLearned(S.view.learned);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => Object.values(LCharts).forEach((c) => c.update("none")));
    renderHeader();
  }
  function drawHeldLine(T) {
    const runs = Object.values(S.view.runs).sort((a, b) => a.run - b.run);
    if (runs.length < 2) { $("ch-line").innerHTML = `<div class="empty">Run a few jobs first.</div>`; return; }
    const pct = (r) => (r.counts.checked ? Math.round((100 * (r.counts.held + r.counts.blocked)) / r.counts.checked) : 0);
    mountChart("ch-line", 220, {
      type: "line",
      data: { labels: runs.map((r) => r.run), datasets: [
        { label: "held for you", data: runs.map(pct), borderColor: T.amber, backgroundColor: T.amber, borderWidth: 2, tension: 0, clip: false, pointRadius: 3, pointHoverRadius: 5, pointBorderWidth: 0, pointStyle: "circle" },
        { label: "checked", data: runs.map(() => 100), borderColor: T.fog, backgroundColor: T.fog, borderWidth: 1.5, pointRadius: 0, pointHoverRadius: 0, clip: false },
      ] },
      options: { maintainAspectRatio: false, layout: { padding: { top: 6 } }, interaction: { mode: "index", intersect: false },
        scales: { y: { min: 0, max: 100, ticks: { callback: (v) => v + "%", stepSize: 50 } }, x: { grid: { display: false }, ticks: { maxTicksLimit: 10, callback: (v, i) => `${label().slice(0, 3)} ${runs[i].run}` } } },
        plugins: { tooltip: { callbacks: { title: (items) => runName(runs[items[0].dataIndex].run), label: (item) => { if (item.datasetIndex === 1) return `checked ${runs[item.dataIndex].counts.checked} writes`; const c = runs[item.dataIndex].counts; return `held ${c.held + c.blocked} of ${c.checked}`; } } } } },
    });
  }
  function drawTools(T) {
    const lad = S.view.learned.ladder.slice().sort((a, b) => (b.approved + b.edited + b.discarded) - (a.approved + a.edited + a.discarded));
    if (!lad.length) { $("ch-tools").innerHTML = `<div class="empty">No decisions yet.</div>`; return; }
    const seg = (label2, key, color) => ({ label: label2, data: lad.map((l) => l[key]), backgroundColor: color, borderColor: T.carbon, borderWidth: 1, borderRadius: 3, borderSkipped: false, barThickness: 12 });
    mountChart("ch-tools", 60 + lad.length * 34, {
      type: "bar",
      data: { labels: lad.map((l) => human(l.tool)), datasets: [seg("approved", "approved", T.green), seg("edited", "edited", T.fog), seg("discarded", "discarded", T.red)] },
      options: { maintainAspectRatio: false, indexAxis: "y", scales: { x: { stacked: true, ticks: { precision: 0 } }, y: { stacked: true, grid: { display: false }, ticks: { color: T.mist } } },
        plugins: { tooltip: { callbacks: { afterTitle: (items) => (lad[items[0].dataIndex].level === "released" ? "sent without review" : "checked by you") } } } },
    });
  }
  function drawEnv(T) {
    const best = {};
    for (const e of S.view.learned.entities) { const range = Object.entries(e.ranges)[0]; if (!range || REF_TOKEN.test(e.value)) continue; if (!best[e.value] || e.n > best[e.value].e.n) best[e.value] = { e, range }; }
    const rows = Object.values(best).sort((a, b) => b.range[1].observed_max - a.range[1].observed_max);
    if (!rows.length) { $("ch-env").innerHTML = `<div class="empty">Nothing approved yet.</div>`; return; }
    mountChart("ch-env", 46 + rows.length * 30, {
      type: "bar",
      data: { labels: rows.map(({ e }) => e.value), datasets: [{ data: rows.map(({ range }) => [range[1].observed_min, range[1].observed_max]), backgroundColor: T.mist, borderRadius: 4, borderSkipped: false, barThickness: 8 }] },
      options: { maintainAspectRatio: false, indexAxis: "y", scales: { x: { beginAtZero: true, ticks: { callback: (v) => money0(v) } }, y: { grid: { display: false }, ticks: { color: T.mist } } },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (item) => { const { e, range } = rows[item.dataIndex]; return `${human(range[0]).toLowerCase()} usually ${money0(range[1].observed_min)}–${money0(range[1].observed_max)} · ${e.n} approved`; } } } } },
    });
  }

  // ------------------------------------------------------------------ boot
  async function boot() {
    $("b-board").onclick = () => { setScreen("board"); renderBoardScreen(); };
    $("b-learn").onclick = () => renderLearning();
    $("b-rules").onclick = () => openSheet("rules", $("b-rules"));
    $("b-settings").onclick = () => openSheet("settings", $("b-settings"));
    $("b-reset").onclick = () => reset();
    try {
      S.view = await api("GET", "/state");
    } catch (e) {
      console.error(e);
      main.innerHTML = `<div class="panel"><h2>Could not reach the service</h2><div class="red">${esc(e.message)}</div></div>`;
      return;
    }
    buildRegistry();
    setScreen("board");
    renderBoardScreen();
  }
  window.pakka = { S, boot, renderBoard, openCard, openSheet, runJob, sendDecisions, reset, renderHeader };
  boot();
})();
