/* pakka — one page, five screens, driven by /state → /run → /decide → /autopilot. No framework. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ state
  const S = {
    view: null,          // StateView from GET /state or POST /reset
    screen: "opening",
    busy: false,
    review: freshReview(),   // the demo's review run
    live: freshReview(),     // a run the real agent produced just now (Q&A)
    scenario: null,          // GET /scenario, fetched once the rule form needs it
    montage: { done: false, running: false },
    auto: { running: false, played: [], totals: zeroCounts(), heldRows: [] },
  };
  let R = S.review; // the review state on screen

  const $ = (id) => document.getElementById(id);
  const main = $("main");

  function freshReview(run, banner) {
    return { run: run || null, banner: banner || "", discards: [], rules: [], cascade: {}, open: {}, decided: false, response: null };
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
  function args(w) { return w.edited_args || w.args; }
  function firstOf(a, shapes) {
    for (const [k, v] of Object.entries(a)) if (shapes.includes(shape(v))) return [k, v];
    return [null, null];
  }
  function short(id) { return id ? id.slice(0, 15) : ""; }
  function el(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }
  function setScreen(name) { S.screen = name; main.dataset.screen = name; } // video/record.py waits on [data-screen=…]

  // chains: one card per root write (no depends_on), dependents follow the placeholders
  function chains(rr) {
    const byPh = {};
    rr.writes.forEach((w) => { byPh[w.placeholder] = w; });
    const roots = rr.writes.filter((w) => !w.depends_on.length);
    const out = roots.map((root) => {
      const deps = [];
      const dead = new Set([root.placeholder]);
      let changed = true;
      while (changed) {
        changed = false;
        for (const w of rr.writes) {
          if (w !== root && !deps.includes(w) && w.depends_on.some((p) => dead.has(p))) { deps.push(w); dead.add(w.placeholder); changed = true; }
        }
      }
      return { root, deps, flagged: root.flags.length > 0 };
    });
    // flagged first, then journal order
    return out.sort((a, b) => (b.flagged - a.flagged) || (a.root.seq - b.root.seq));
  }
  function isHeldRoot(w) { return w.status === "held" && !w.blocked_by.length; }
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

  // ------------------------------------------------------------------ header
  function renderHeader() {
    const v = S.view;
    $("sub").textContent = v ? `${v.scenario} · ${label()} ${v.current_run}` : "";
    const run1 = v && v.runs[String(firstReviewRun())];
    const held = run1 && !run1.decided ? run1.writes.filter((w) => w.status === "held").length : 0;
    $("b-review").innerHTML = `Review${held ? `<span class="count">${held}</span>` : ""}`;
    $("b-review").disabled = !run1 || S.busy;
    // one replay at a time: the server plays Fridays in order, so the two long buttons exclude each other
    $("b-montage").disabled = !v || S.busy || S.montage.running || S.auto.running;
    $("b-auto").disabled = !v || S.busy || S.auto.running || S.montage.running;
    $("b-learn").disabled = !v || S.busy || S.auto.running || S.montage.running;
    $("b-reset").disabled = !v || S.busy;
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
    if (live) { live.disabled = S.busy || S.montage.running || S.auto.running; live.textContent = S.liveRunning ? "Running…" : "Run live"; }
    const tag = v ? `transcripts: ${v.transcripts_tag}${v.live_available ? (liveOptIn ? " · live model available" : " · live model available (?live=1)") : ""}` : "";
    $("foot-note").textContent = tag;
  }
  function notice(msg) {
    const old = main.querySelector(".notice"); if (old) old.remove();
    main.prepend(el(`<div class="notice amber" role="alert">${esc(msg)}</div>`));
  }

  // ------------------------------------------------------------------ a typed rule (Q&A): hold <tool> when <field> <op> <value>
  const OPS = [["matches", "matches"], ["in", "in"], ["not_in", "not in"], ["gt", ">"], ["lt", "<"]];
  function ruleChips(learned) {
    return learned.rules.filter((r) => r.status === "active").map((r) => `<span class="chip held">rule: ${esc(r.tool)}.${esc(r.field)} ${esc(r.label)}</span>`).join("");
  }
  function ruleForm() {
    return `
      <form class="rule-form" id="rule-form" autocomplete="off">
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
    const form = $("rule-form"); if (!form) return;
    const tool = form.elements.tool, field = form.elements.field, op = form.elements.op, value = form.elements.value, err = form.querySelector(".rule-err");
    if (!S.scenario) { try { S.scenario = await api("GET", "/scenario"); } catch (e) { console.error(e); return; } }
    if (!document.body.contains(form)) return;
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
  function firstReviewRun() { return (S.view && S.view.review_runs && S.view.review_runs[0]) || 1; }

  // ------------------------------------------------------------------ screen 1: opening
  function renderOpening() {
    setScreen("opening");
    const v = S.view;
    const rr = v.runs[String(firstReviewRun())];
    const effects = v.systems.reduce((n, s) => n + s.count, 0);
    main.innerHTML = `
      <div class="hero">
        <div class="label">The agent's last line, ${label()} ${rr ? rr.run : ""}</div>
        <p class="line">${esc(rr ? rr.agent_text : "…")}</p>
        <div class="after">${rr ? `<b>${rr.counts.checked}</b> writes checked · <b>${effects}</b> reached a system` : ""}</div>
      </div>
      <div class="actions">
        <button class="btn primary" id="o-review">Review</button>
        <button class="btn" id="o-montage">Play 5 ${label()}s</button>
        <button class="btn" id="o-auto">Autopilot</button>
      </div>
      <div class="rule-slot" id="rule-slot"><button class="btn ghost small muted" id="o-rule">Add a rule</button></div>`;
    $("o-review").onclick = () => renderReview("demo");
    $("o-montage").onclick = () => startMontage();
    $("o-auto").onclick = () => startAutopilot();
    $("o-rule").onclick = () => {
      const slot = $("rule-slot");
      slot.innerHTML = `<div class="ladder" id="rule-chips">${ruleChips(v.learned)}</div>${ruleForm()}`;
      bindRuleForm((res) => { const c = $("rule-chips"); if (c) c.innerHTML = ruleChips(res); });
    };
    renderHeader();
  }

  // ------------------------------------------------------------------ screen 2: review
  function renderReview(which) {
    setScreen("review");
    const v = S.view;
    if (which === "live") R = S.live; else if (which === "demo" || !S.live.run) R = S.review;
    const run = R.run || firstReviewRun();
    const rr = R.response ? R.response.run : v.runs[String(run)];
    if (!rr) { renderOpening(); return; }
    R.decided = !!rr.decided;
    const cs = chains(rr);
    const heldRoots = rr.writes.filter(isHeldRoot).length;
    const flagged = cs.filter((c) => c.flagged).length;
    // the demo's review run shows its rule card even after the rule went live; a live run shows only what it proposed
    const rule = rr.proposed_rules[0] || (R === S.review ? (v.learned.rules || []).find((r) => r.derived_from && r.status !== "rejected") : null);
    main.innerHTML = `
      ${R.banner ? `<div class="banner" id="review-banner">${esc(R.banner)}</div>` : ""}
      <div class="review-head">
        <div class="sum">${label()} ${rr.run}: <b>${cs.length}</b> chains, <b>${rr.writes.length}</b> writes held · <b class="amber">${flagged}</b> flagged · <b>${heldRoots - flagged}</b> normal</div>
        <div>${rr.decided ? `<span class="green">Approved</span>` : `<button class="btn primary" id="r-approve" data-action="approve">Approve</button>`}</div>
      </div>
      <div class="cards" id="cards"></div>`;
    const box = $("cards");
    if (rule && !rr.decided) box.appendChild(ruleCard(rr, rule));
    cs.forEach((c) => box.appendChild(chainCard(rr, c)));
    if (rule && rr.decided) box.appendChild(ruleCard(rr, rule));
    const ap = $("r-approve");
    if (ap) ap.onclick = approve;
    renderHeader();
  }

  function chainCard(rr, c) {
    const w = c.root;
    const a = args(w);
    const [, name] = firstOf(a, ["name"]);
    const [, num] = firstOf(a, ["number"]);
    const idents = Object.entries(a).filter(([, x]) => ["account", "ref", "id", "email"].includes(shape(x)));
    const discarded = R.discards.includes(w.id) || w.status === "discarded";
    const card = el(`<div class="card ${c.flagged ? "flagged" : ""} ${discarded ? "discarded" : ""}" data-id="${esc(w.id)}"></div>`);
    card.innerHTML = `
      <div class="top"><div class="title">${esc(name || w.tool)}</div><div class="amount">${typeof num === "number" ? money(num) : ""}</div></div>
      <div class="meta"><span>${esc(w.tool)}</span>${idents.map(([k, x]) => `<span>${esc(k)} <code>${esc(x)}</code></span>`).join("")}<span class="mono">${esc(w.placeholder)}</span></div>
      ${w.flags.map((f) => `<div class="flag"><span class="kind">${esc(f.kind)}</span><span>${esc(f.reason)}</span></div>`).join("")}
      <div class="deps">${c.deps.map((d) => depRow(d)).join("")}</div>
      <div class="foot">
        ${statusBadge(w, discarded)}
        ${!rr.decided && !discarded && w.status === "held" ? `<button class="btn danger small" data-discard="${esc(w.id)}" data-action="discard">Discard</button>` : ""}
        ${!rr.decided && discarded && w.status === "held" ? `<button class="btn small" data-undo="${esc(w.id)}">Keep</button>` : ""}
        <span class="note" data-cascade="${esc(w.id)}"></span>
        <button class="btn ghost small" data-details="${esc(w.id)}">Details</button>
      </div>
      <div class="details" data-details-box="${esc(w.id)}" hidden>${esc(detailsText([w, ...c.deps]))}</div>`;
    const dis = card.querySelector("[data-discard]");
    if (dis) dis.onclick = () => discard(w.id);
    const undo = card.querySelector("[data-undo]");
    if (undo) undo.onclick = () => { R.discards = R.discards.filter((x) => x !== w.id); renderReview(); };
    card.querySelector("[data-details]").onclick = () => {
      const box = card.querySelector("[data-details-box]");
      box.hidden = !box.hidden;
    };
    const note = card.querySelector("[data-cascade]");
    if (discarded && R.cascade[w.id]) note.textContent = cascadeText(R.cascade[w.id]);
    return card;
  }
  function depRow(d) {
    const cls = d.sent ? "sent" : d.status === "skipped" || R.discards.some((id) => R.cascade[id] && R.cascade[id].includes(d.id)) ? "skipped" : "";
    const st = d.sent ? d.result_id : d.status === "skipped" ? "skipped" : cls === "skipped" ? "will be skipped" : d.status;
    return `<div class="dep ${cls}" data-dep="${esc(d.id)}"><span class="tool">${esc(d.tool)}</span><span>${esc(summary(d))}</span><span class="mono muted">${esc(short(d.placeholder))}</span><span class="status mono">${esc(st)}</span></div>`;
  }
  function statusBadge(w, discarded) {
    if (w.sent) return `<span class="green mono">${esc(w.result_id)}</span>`;
    if (w.status === "discarded" || discarded) return `<span class="red">discarded</span>`;
    if (w.status === "skipped") return `<span class="red">skipped</span>`;
    if (w.status === "held") return `<span class="muted">held</span>`;
    return `<span class="muted">${esc(w.status)}</span>`;
  }
  function detailsText(ws) {
    return ws.map((w) => `${w.tool}  ${w.placeholder}  status=${w.status}${w.depends_on.length ? "  depends_on=" + w.depends_on.join(",") : ""}${w.result_id ? "  → " + w.result_id : ""}\n${JSON.stringify(args(w), null, 2)}`).join("\n\n");
  }
  function cascadeText(ids) {
    if (!ids || !ids.length) return "nothing else depends on it";
    return `also skips ${ids.length} dependent${ids.length === 1 ? "" : "s"}`;
  }

  function ruleCard(rr, rule) {
    const src = rr.writes.find((w) => w.id === rule.derived_from) || rr.writes.find((w) => w.edited_args);
    const before = src ? String(src.args[rule.field] ?? "") : "";
    const after = src && src.edited_args ? String(src.edited_args[rule.field] ?? "") : "";
    const accepted = R.rules.includes(rule.id) || rule.status === "active";
    let beforeHtml = esc(before);
    if (rule.op === "matches" && before) {
      // highlight what the correction took out: the sentence(s) that no longer appear in `after`
      const removed = before.split(/(?<=\.)\s*/).filter((sentence) => sentence && !after.includes(sentence.trim()));
      if (removed.length) {
        beforeHtml = esc(before);
        removed.forEach((r) => { beforeHtml = beforeHtml.replace(esc(r.trim()), `<del>${esc(r.trim())}</del>`); });
      } else {
        try { beforeHtml = esc(before).replace(new RegExp(rule.value, "g"), (m) => `<del>${m}</del>`); } catch (e) { /* keep plain */ }
      }
    }
    const card = el(`<div class="card rule"></div>`);
    card.innerHTML = `
      <div class="top"><div class="title">${esc(src ? summary(src) : rule.tool)} — edited</div><div class="muted">${esc(rule.tool)} · ${esc(rule.field)}</div></div>
      <div class="diff">
        <div class="side before"><span class="lab">before</span>${beforeHtml}</div>
        <div class="side after"><span class="lab">after (Tom's edit)</span>${esc(after)}</div>
      </div>
      <div class="flag"><span class="kind">rule</span><span>Hold every <b>${esc(rule.tool)}</b> whose <b>${esc(rule.field)}</b> contains ${esc(rule.label)}?</span></div>
      <div class="foot">
        ${accepted ? `<span class="green">Rule on — from the next action</span>` : `<button class="btn amber" data-yes data-action="rule-accept">Yes always</button><button class="btn ghost" data-no>Not now</button>`}
      </div>`;
    const yes = card.querySelector("[data-yes]");
    if (yes) yes.onclick = () => { if (!R.rules.includes(rule.id)) R.rules.push(rule.id); renderReview(); };
    const no = card.querySelector("[data-no]");
    if (no) no.onclick = () => { card.querySelector(".foot").innerHTML = `<span class="muted">Not now — the edit still applies on Approve</span>`; };
    return card;
  }

  async function discard(writeId) {
    const run = R.run || firstReviewRun();
    const rv = R;
    if (!rv.discards.includes(writeId)) rv.discards.push(writeId);
    renderReview();
    try {
      const res = await api("GET", `/cascade/${run}/${encodeURIComponent(writeId)}`);
      rv.cascade[writeId] = res.skipped;
    } catch (e) {
      console.error(e);
      rv.cascade[writeId] = [];
    }
    if (S.screen === "review" && R === rv) renderReview();
  }

  async function approve() {
    if (S.busy) return;
    const rv = R;
    const run = rv.run || firstReviewRun();
    const req = {
      run,
      decisions: rv.discards.map((id) => ({ write_id: id, action: "discard" })),
      accept_rules: rv.rules.slice(),
      approve_rest: true,
      decided_by: "person",
    };
    S.busy = true; renderHeader();
    const btn = $("r-approve"); if (btn) { btn.disabled = true; btn.textContent = "Applying…"; }
    let res;
    try {
      res = await api("POST", "/decide", req);
    } catch (e) {
      console.error(e);
      S.busy = false; renderHeader();
      if (btn) { btn.disabled = false; btn.textContent = "Approve"; }
      return;
    }
    rv.response = res;
    S.view.runs[String(run)] = res.run;
    S.view.scoreboard = res.scoreboard;
    S.view.learned = res.learned;
    S.busy = false;
    // the world fills in dependency order; the cards get real ids where the placeholders were
    const byPh = {}; res.run.writes.forEach((w) => { byPh[w.placeholder] = w; });
    const head = main.querySelector(".review-head > div:last-child");
    if (head) head.innerHTML = `<span class="muted">Applying in dependency order…</span>`;
    for (const w of res.run.writes) {
      if (w.status === "skipped" || w.status === "discarded") {
        const card = main.querySelector(`.card[data-id="${CSS.escape(w.id)}"]`);
        if (card) { card.classList.add("discarded"); const f = card.querySelector(".foot"); if (f) f.innerHTML = `<span class="red">${w.status}</span><span class="note">${esc(cascadeText(rv.cascade[w.id]))}</span>`; }
        const dep = main.querySelector(`.dep[data-dep="${CSS.escape(w.id)}"]`);
        if (dep) { dep.classList.add("skipped"); dep.querySelector(".status").textContent = "skipped"; }
      }
    }
    for (const e of res.run.effects) {
      const w = res.run.writes.find((x) => x.result_id === e.result_id && x.tool === e.tool);
      if (w) {
        const card = main.querySelector(`.card[data-id="${CSS.escape(w.id)}"]`);
        if (card) { const f = card.querySelector(".foot"); if (f) f.innerHTML = `<span class="green mono">${esc(w.result_id)}</span><span class="note">sent · was ${esc(w.placeholder)}</span>`; }
        const dep = main.querySelector(`.dep[data-dep="${CSS.escape(w.id)}"]`);
        if (dep) { dep.classList.add("sent"); dep.querySelector(".status").textContent = w.result_id; }
      }
      await sleep(120);
    }
    S.view.systems = S.view.systems.map((s) => ({ ...s, count: s.count + res.run.effects.filter((e) => e.system === s.name).length }));
    if (head) head.innerHTML = `<span class="green">Approved · ${res.run.effects.length} writes landed</span>`;
    const rc = main.querySelector(".card.rule .foot");
    if (rc && rv.rules.length) rc.innerHTML = `<span class="green">Rule on — from the next action</span>`;
    renderHeader();
  }

  // a live run (Q&A): the real agent on the next run, reviewed on the same screen as the replay
  async function runLive() {
    if (S.busy || S.liveRunning) return;
    S.busy = true; S.liveRunning = true; renderHeader();
    let res;
    try {
      res = await api("POST", "/live", {});
    } catch (e) {
      S.busy = false; S.liveRunning = false; renderHeader();
      notice(e.detail || e.message); // a 400 (no model, or the model could not be built) is one amber line
      return;
    }
    S.busy = false; S.liveRunning = false;
    const v = S.view;
    v.runs[String(res.run.run)] = res.run; v.learned = res.learned; v.scoreboard = res.scoreboard; v.current_run = res.run.run;
    S.live = freshReview(res.run.run, `Live: ${res.run.model}`);
    renderReview("live");
  }

  // ------------------------------------------------------------------ screen 3: montage
  function learnedPanel(withEnts = true) {
    // trusted tools on top, then Tom's rules, then the history; entities only where there is no envelope chart
    return `<div class="panel learned"><h2>What it has learned</h2>
      <div id="learned-ladder"></div>
      <div id="learned-rules"></div>
      <div class="lh" id="learned-hh" hidden>History</div>
      <div class="events" id="learned-events"></div>
      ${withEnts ? `<div class="ents" id="learned-ents"></div>` : ""}
      ${ruleForm()}</div>`;
  }
  function fri(n) { return `${label().slice(0, 3)} ${n}`; }
  function ruleSentence(r) {
    const join = r.op === "matches" ? "contains" : "is";
    return `hold ${r.tool} when ${r.field} ${join} ${r.label || `${r.op} ${r.value}`}`;
  }
  function fillLearned(learned, sinceRun) {
    const ev = $("learned-events"), ents = $("learned-ents"), lad = $("learned-ladder");
    if (!ev) return;
    const released = learned.ladder.filter((l) => l.level === "released");
    const checked = learned.ladder.filter((l) => l.level !== "released");
    const row = (name, meta) => `<div class="lrow"><span class="ln">${esc(name)}</span><span class="lm">${esc(meta)}</span></div>`;
    lad.innerHTML =
      (released.length ? `<div class="lh">Sent without review</div>` + released.map((l) => row(l.tool, `${l.released_run ? `since ${fri(l.released_run)} · ` : ""}${l.approved} approved`)).join("") : "") +
      (checked.length ? `<div class="lh">Still checked, earning trust</div>` + checked.map((l) => row(l.tool, `${l.approved} approved${l.discarded ? ` · ${l.discarded} discarded` : ""}`)).join("") : "");
    const active = learned.rules.filter((r) => r.status === "active");
    $("learned-rules").innerHTML = active.length
      ? `<div class="lh">Tom's rules</div>` + active.map((r) => row(ruleSentence(r), `${r.created_by === "person" ? "Tom" : r.created_by}, ${fri(r.created_run)}`)).join("")
      : "";
    const shown = new Set([...ev.querySelectorAll(".ev")].map((n) => n.dataset.key));
    for (const e of learned.events) {
      if (sinceRun !== undefined && e.run !== sinceRun) continue;
      if (e.kind === "envelope" && REF_TOKEN.test(e.text)) continue; // a per-record label the layer took for an entity: nothing to show

      const key = `${e.run}|${e.kind}|${e.text}`;
      if (shown.has(key)) continue;
      const text = e.kind === "promotion" && e.text.includes("now sent") ? e.text.replace(/\s*\(.*\)$/, "") : e.text;
      const node = el(`<div class="ev ${esc(e.kind)}" data-key="${esc(key)}"><span class="k">${esc(fri(e.run))}</span>${esc(text)}</div>`);
      ev.appendChild(node);
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

  function renderMontage() {
    setScreen("montage");
    main.innerHTML = `
      <div class="cols">
        <div>
          <div class="review-head"><div class="sum"><b>Play 5 ${label()}s</b> · 8× · <span class="green">Tom approves (simulated)</span></div><div class="muted" id="m-status"></div></div>
          <div class="friday-strip" id="strip"></div>
        </div>
        ${learnedPanel()}
      </div>`;
    fillLearned(S.view.learned);
    bindRuleForm((res) => fillLearned(res));
    renderHeader();
  }

  async function startMontage() {
    if (S.montage.running) return;
    S.montage.running = true;
    renderMontage();
    const v = S.view;
    const todo = v.montage_runs.filter((f) => !(v.runs[String(f)] && v.runs[String(f)].decided));
    const strip = $("strip");
    if (!todo.length) {
      strip.appendChild(el(`<div class="empty">Those ${label()}s have already been played. Reset to play them again.</div>`));
      v.montage_runs.forEach((f) => { const rr = v.runs[String(f)]; if (rr) strip.appendChild(fridayBlock(rr, true)); });
      S.montage.running = false; renderHeader();
      return;
    }
    // fire the requests sequentially (the server state is sequential); animate as each lands, never blocking the next request
    const results = todo.map(() => null);
    const waiters = [];
    const promise = (async () => {
      for (let i = 0; i < todo.length; i++) {
        try {
          results[i] = await api("POST", `/run/${todo[i]}`, { auto_approve: true });
        } catch (e) { console.error(e); results[i] = { error: e.message }; }
        if (waiters[i]) waiters[i]();
      }
    })();
    const perFriday = Math.min(2000, Math.floor(12000 / todo.length));
    for (let i = 0; i < todo.length; i++) {
      if (!results[i]) await new Promise((res) => { waiters[i] = res; if (results[i]) res(); });
      const r = results[i];
      $("m-status").textContent = `${label()} ${todo[i]}`;
      if (r.error) { strip.appendChild(el(`<div class="friday"><div class="fh"><span class="t">${label()} ${todo[i]}</span><span class="red">${esc(r.error)}</span></div></div>`)); continue; }
      v.runs[String(todo[i])] = r.run; v.scoreboard = r.scoreboard; v.learned = r.learned; v.current_run = todo[i];
      const block = fridayBlock(r.run, false);
      strip.appendChild(block);
      const chips = block.querySelector(".writes");
      const ws = r.run.writes;
      const step = Math.max(40, Math.min(150, Math.floor((perFriday - 300) / Math.max(1, ws.length))));
      for (const w of ws) {
        chips.appendChild(el(`<span class="chip ${w.sent ? "sent" : "held"}">${esc(w.tool)} ${w.sent ? "→ " + esc(w.result_id) : "held"}</span>`));
        await sleep(step);
      }
      block.querySelector(".tag").textContent = `Tom approves (simulated) · ${r.run.counts.through} sent`;
      block.querySelector(".tag").classList.add("approve");
      fillLearned(r.learned);
      S.view.systems = S.view.systems.map((s) => ({ ...s, count: s.count + r.run.effects.filter((e) => e.system === s.name).length }));
      renderHeader();
    }
    await promise;
    $("m-status").textContent = "done";
    S.montage.running = false; S.montage.done = true;
    renderHeader();
  }
  function fridayBlock(rr, complete) {
    const b = el(`<div class="friday"><div class="fh"><span class="t">${label()} ${rr.run}</span><span class="muted">${esc(rr.agent_text)}</span><span class="tag">${complete ? "Tom approves (simulated)" : "running…"}</span></div><div class="writes"></div></div>`);
    if (complete) rr.writes.forEach((w) => b.querySelector(".writes").appendChild(el(`<span class="chip ${w.sent ? "sent" : "held"}">${esc(w.tool)} ${w.sent ? "→ " + esc(w.result_id) : esc(w.status)}</span>`)));
    return b;
  }

  // ------------------------------------------------------------------ screen 4: learning
  // Three Chart.js charts over data the layer already has: per-run counts, the
  // per-tool ladder, and the per-entity envelopes. chart.umd.js is vendored.
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
    main.innerHTML = `
      <div class="cols">
        <div class="charts">
          <div class="panel chart"><h2>Checked vs held, per ${label()}</h2><div class="chart-box" id="ch-line"></div></div>
          <div class="panel chart"><h2>Outcomes by tool, from Tom's reviews</h2><div class="chart-box" id="ch-tools"></div></div>
          <div class="panel chart"><h2>Envelopes: what passes without a look, from approvals only</h2><div class="chart-box" id="ch-env"></div></div>
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
            label: "held for a person", data: runs.map(pct),
            borderColor: T.amber, backgroundColor: T.amber, borderWidth: 2, tension: 0,
            pointRadius: (c) => (runs[c.dataIndex].counts.caught ? 4 : 0),
            pointHoverRadius: 5, pointBorderWidth: 0, pointStyle: "circle",
          },
          {
            label: "checked", data: runs.map(() => 100),
            borderColor: T.fog, backgroundColor: T.fog, borderWidth: 1.5, pointRadius: 0, pointHoverRadius: 0,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
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

  // ------------------------------------------------------------------ screen 5: autopilot
  function renderAutopilot() {
    setScreen("autopilot");
    main.innerHTML = `
      <div>
        <div class="counters">
          ${counter("fridays", `${label()}s`)}${counter("checked", "actions checked")}${counter("through", "through", "through")}${counter("held", "held", "held")}${counter("volume", "moved")}
        </div>
        <div class="cols">
          <div>
            <p class="score" id="score">caught 0/0 · wrongly held 0</p>
            <div class="feed" id="feed"></div>
          </div>
          <div class="panel held-list"><h2>Held for a person</h2><div id="held"></div><div class="empty" id="held-empty">Nothing yet.</div></div>
        </div>
      </div>`;
    renderCounters();
    renderHeader();
  }
  function counter(key, lab, cls) { return `<div class="counter ${cls || ""}"><div class="n" data-counter="${key}">0</div><div class="l">${esc(lab)}</div></div>`; }
  function renderCounters() {
    const t = S.auto.totals;
    const set = (k, v) => { const n = main.querySelector(`[data-counter="${k}"]`); if (n) n.textContent = v; };
    set("fridays", t.fridays); set("checked", t.checked); set("through", t.through); set("held", t.held); set("volume", money0(t.volume));
    const sc = $("score");
    if (sc) sc.innerHTML = `caught <span class="${t.caught >= t.anomalies ? "ok" : "bad"}">${t.caught}/${t.anomalies}</span> · wrongly held <span class="${t.wrongly_held ? "bad" : "ok"}">${t.wrongly_held}</span>`;
  }

  async function startAutopilot() {
    if (S.auto.running) return;
    S.auto.running = true;
    const v = S.view;
    if (S.screen !== "autopilot") { S.auto.totals = zeroCounts(); renderAutopilot(); }
    else renderHeader();
    const played = new Set(Object.keys(v.runs).map(Number));
    let todo = v.autopilot_runs.filter((f) => !played.has(f));
    if (!todo.length) {
      const last = Math.max(...v.autopilot_runs, ...played);
      todo = [];
      for (let f = last + 1; f <= v.total_runs && todo.length < 10; f++) if (!played.has(f)) todo.push(f);
    }
    const feed = $("feed");
    if (!todo.length) {
      feed.appendChild(el(`<div class="row sep">every ${label()} has been played — Reset to start over</div>`));
      S.auto.running = false; renderHeader();
      return;
    }
    const results = todo.map(() => null);
    const waiters = [];
    const promise = (async () => {
      for (let i = 0; i < todo.length; i++) {
        try { results[i] = await api("POST", `/autopilot/${todo[i]}`); }
        catch (e) { console.error(e); results[i] = { error: e.message }; }
        if (waiters[i]) waiters[i]();
      }
    })();
    const perFriday = 2400; // ten runs in about 24s; the four holds land near 4s, 9s, 14s and 19s after the click
    for (let i = 0; i < todo.length; i++) {
      const started = Date.now();
      if (!results[i]) await new Promise((res) => { waiters[i] = res; if (results[i]) res(); });
      const r = results[i];
      const f = todo[i];
      if (r.error) { feed.appendChild(el(`<div class="row sep red">${label()} ${f}: ${esc(r.error)}</div>`)); continue; }
      v.runs[String(f)] = r.run; v.scoreboard = r.scoreboard; v.learned = r.learned; v.current_run = f;
      feed.appendChild(el(`<div class="row sep">${label()} ${f} · ${esc(r.run.agent_text)}</div>`));
      const rows = r.run.writes.filter((w) => w.status === "passed" || isHeldRoot(w));
      const step = Math.max(60, Math.min(220, Math.floor((perFriday - 400) / Math.max(1, rows.length))));
      for (const w of rows) {
        if (w.status === "passed") {
          feed.appendChild(el(`<div class="row pass"><span class="f">${esc(label().slice(0, 3))} ${f}</span><span class="tool">${esc(w.tool)}</span><span class="what">${esc(summary(w))} → ${esc(w.result_id)}</span></div>`));
        } else {
          const reason = w.flags.length ? w.flags[0].reason : `${w.tool} is still checked`;
          feed.appendChild(el(`<div class="row hold"><span class="f">${esc(label().slice(0, 3))} ${f}</span><span class="tool">${esc(w.tool)}</span><span class="what">${esc(summary(w))} — ${esc(reason)}</span></div>`));
          addHeld(w, f, reason);
        }
        feed.scrollTop = feed.scrollHeight;
        await sleep(step);
      }
      const c = r.run.counts, t = S.auto.totals;
      t.fridays += 1; t.checked += c.checked; t.through += c.through; t.held += c.held; t.caught += c.caught; t.wrongly_held += c.wrongly_held; t.volume += c.volume;
      t.anomalies += v.anomaly_runs.filter((x) => x === f).length;
      S.auto.played.push(f);
      renderCounters();
      S.view.systems = S.view.systems.map((s) => ({ ...s, count: s.count + r.run.effects.filter((e) => e.system === s.name).length }));
      renderHeader();
      const remaining = perFriday - (Date.now() - started);
      if (remaining > 0) await sleep(remaining);
    }
    await promise;
    S.auto.running = false;
    renderHeader();
  }
  function addHeld(w, f, reason) {
    const box = $("held"); if (!box) return;
    const empty = $("held-empty"); if (empty) empty.hidden = true;
    box.appendChild(el(`<div class="h"><div class="t">${esc(summary(w) || w.tool)}</div><div class="r">${esc(reason)}</div><div class="m">${esc(label())} ${f} · ${esc(w.tool)} · ${esc(w.placeholder)}${w.anomaly ? " · " + esc(w.anomaly) : ""}</div></div>`));
  }

  // ------------------------------------------------------------------ screen 5: reset
  async function reset() {
    if (S.busy) return;
    S.busy = true; renderHeader();
    try {
      S.view = await api("POST", "/reset");
    } catch (e) { console.error(e); }
    S.busy = false;
    S.review = freshReview(); S.live = freshReview(); R = S.review;
    S.montage = { done: false, running: false };
    S.auto = { running: false, played: [], totals: zeroCounts(), heldRows: [] };
    renderOpening();
  }

  // ------------------------------------------------------------------ boot
  async function boot() {
    $("b-review").onclick = () => renderReview("demo");
    $("b-montage").onclick = () => startMontage();
    $("b-auto").onclick = () => startAutopilot();
    $("b-learn").onclick = () => renderLearning();
    $("b-reset").onclick = () => reset();
    try {
      S.view = await api("GET", "/state");
      if (!S.view.runs[String(firstReviewRun())]) S.view = await api("POST", "/reset");
      const rr = S.view.runs[String(firstReviewRun())];
      if (rr && rr.decided) S.review.decided = true;
    } catch (e) {
      console.error(e);
      main.innerHTML = `<div class="panel"><h2>Could not reach the service</h2><div class="red">${esc(e.message)}</div></div>`;
      return;
    }
    renderOpening();
  }
  window.pakka = { S, boot, renderOpening, renderReview, startMontage, startAutopilot, reset, runLive, renderHeader };
  boot();
})();
