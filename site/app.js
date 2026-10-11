"use strict";

// Renders the results page from data.json (written by `lookml-conformance site`).
// The DOM is built with createElement and textContent only; no data is parsed as HTML.

const REPO = "https://github.com/josephaxisa/lookml-conformance";

// Issues and pull requests filed upstream because of a case. To move into data.json (issue #4).
const UPSTREAM = [
  {
    tool: "node-lookml-parser",
    caseId: "p01",
    url: "https://github.com/fabio-looker/node-lookml-parser/pull/43",
    label: "fabio-looker/node-lookml-parser#43",
    title: "Fix single-semicolon corruption inside ;; blocks",
    status: "submitted",
  },
];

const $ = (selector) => document.querySelector(selector);

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "style") el.style.cssText = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const shortId = (c) => c.id.split("_")[0];
const outcomeOf = (c, tool) => c.verdicts[tool.name]?.outcome ?? "n/a";
const differs = (outcome) => outcome === "fail" || outcome === "error";
const OUTCOME = {
  pass: { cls: "pass", mark: "✓", label: "matches Looker" },
  fail: { cls: "fail", mark: "✗", label: "differs" },
  error: { cls: "error", mark: "✗", label: "adapter error" },
  "n/a": { cls: "na", mark: "–", label: "does not apply" },
};

// ---------------------------------------------------------------- LookML highlighting

const LOOKML_TOKENS = /(#[^\n]*)|("(?:[^"\\]|\\.)*")|(;;)|(\$\{[^}]*\}|@\{[^}]*\})|(\b[a-z_]+(?=:))|(\+[a-z_]+)/g;

function highlight(source) {
  const out = document.createDocumentFragment();
  let last = 0;
  for (const match of source.matchAll(LOOKML_TOKENS)) {
    if (match.index > last) out.append(source.slice(last, match.index));
    const [text, comment, string, terminator, reference] = match;
    const cls = comment ? "tok-c" : string || reference ? "tok-s" : terminator ? "tok-r" : "tok-k";
    out.append(h("span", { class: cls }, text));
    last = match.index + text.length;
  }
  out.append(source.slice(last));
  return out;
}

// ---------------------------------------------------------------- matrix

// Buckets, left to right: no tool matches, exactly one matches, some match, all match.
function bucketOf(c, tools) {
  const applicable = tools.map((t) => outcomeOf(c, t)).filter((o) => o !== "n/a");
  const passed = applicable.filter((o) => o === "pass").length;
  if (passed === 0) return 0;
  if (passed === applicable.length) return 3;
  if (passed === 1) return 1;
  return 2;
}

function passRate(c, tools) {
  const applicable = tools.map((t) => outcomeOf(c, t)).filter((o) => o !== "n/a");
  return applicable.length ? applicable.filter((o) => o === "pass").length / applicable.length : 1;
}

const GROUP = [
  { cls: "none", label: "no tool matches" },
  { cls: "one", label: "one tool matches" },
  { cls: "", label: "" },
  { cls: "all", label: "every tool it applies to matches" },
];

function renderMatrix(data, tools) {
  const order = data.cases.map((c, index) => ({ c, index, bucket: bucketOf(c, tools), rate: passRate(c, tools) }));
  order.sort((a, b) => a.bucket - b.bucket || a.rate - b.rate || a.index - b.index);
  const cases = order.map((o) => o.c);

  const tripped = order.filter((o) => o.bucket !== 3).length;
  $("#results-title").textContent = `${tripped} of ${cases.length} rules trip up at least one tool`;
  $("#results-date").textContent = `released versions, scored ${data.date}`;

  const width = (n) => `${n * 18 + (n - 1) * 3}px`;
  const groups = h("div", { class: "matrix__groups", "aria-hidden": "true" }, h("span", { class: "matrix__lead" }));
  for (let bucket = 0; bucket < 4; bucket++) {
    const n = order.filter((o) => o.bucket === bucket).length;
    if (!n) continue;
    groups.append(h("span", { class: `matrix__group ${GROUP[bucket].cls ? `matrix__group--${GROUP[bucket].cls}` : ""}`, style: `width:${width(n)}` }, GROUP[bucket].label));
  }
  groups.append(h("span", { class: "matrix__score-head" }, "matches"));

  const rows = tools.map((tool) =>
    h(
      "div",
      { class: "matrix__row" },
      h(
        "a",
        { class: "matrix__lead", href: `#tool=${tool.name}`, "aria-label": `${tool.label} (${tool.kind}): show the cases where it differs from Looker` },
        h("span", { class: "kind" }, tool.kind ?? ""),
        h("span", { class: "matrix__name" }, tool.label),
      ),
      cases.map((c) => {
        const o = OUTCOME[outcomeOf(c, tool)];
        return h("span", { class: `cell cell--${o.cls}`, "aria-hidden": "true", "data-case": shortId(c), title: `${shortId(c)} · ${tool.label}: ${o.label}` });
      }),
      h("span", { class: "matrix__score" }, `${tool.score.all.passed}`, h("span", {}, ` / ${tool.score.all.applicable}`), h("span", { class: "sr-only" }, " cases match Looker")),
    ),
  );

  const ids = h(
    "div",
    { class: "matrix__ids", "aria-hidden": "true" },
    h("span", { class: "matrix__lead" }, "case"),
    cases.map((c) => h("span", { class: "matrix__id", "data-case": shortId(c), title: c.title }, shortId(c))),
  );

  // The squares and case ids are mouse shortcuts into the case list. Keyboard and screen reader
  // users reach the same cases through the tool links and the case list, whose rows are
  // full-size buttons, so the squares stay out of the tab order and the accessibility tree.
  $("#matrix").replaceChildren(groups, ...rows, ids);
  $("#matrix").onclick = (event) => {
    const target = event.target.closest("[data-case]");
    if (target) location.hash = `case=${target.dataset.case}`;
  };
}

// ---------------------------------------------------------------- cases

const state = { category: "", tool: "", onlyDiffers: false, onlyFiled: false, open: "" };
const filedFor = (c) => UPSTREAM.filter((u) => u.caseId === shortId(c));

function expectLines(expect) {
  const lines = [];
  for (const [model, out] of Object.entries(expect.models ?? {})) {
    for (const kind of ["views", "explores"]) {
      for (const [name, props] of Object.entries(out[kind] ?? {})) {
        for (const [key, value] of Object.entries(props)) {
          lines.push(`${model}.${name}.${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`);
        }
      }
    }
  }
  if (expect.absent_views?.length) lines.push(`views that must not exist: ${expect.absent_views.join(", ")}`);
  return lines;
}

function issueUrl(data, c, tool) {
  const verdict = c.verdicts[tool.name];
  const page = `${location.origin}${location.pathname}#case=${shortId(c)}`;
  const citation = c.citations[0];
  const head = [
    `[lookml-conformance](${page}) checks how tools resolve LookML projects against Looker. In case \`${c.id}\`, ${tool.label} ${tool.version} resolves the project differently from Looker.`,
    "",
    `**Rule.** ${c.rule}`,
    "",
  ];
  if (citation) head.push(`> ${citation.quote}`, `>`, `> [${citation.label}](${citation.url})`, "");
  head.push("**Difference**", ...verdict.reasons.map((r) => `- ${r}`), "");
  const files = [
    "<details><summary>The minimal LookML project</summary>",
    "",
    ...c.files.flatMap((f) => [`\`${f.path}\``, "```lookml", f.content.trimEnd(), "```", ""]),
    "</details>",
    "",
  ];
  const tail = [
    "**Reproduce**",
    "```",
    `git clone ${REPO} && cd lookml-conformance`,
    "pip install -e . && lookml-conformance setup",
    `lookml-conformance run --adapter ${tool.name} --only ${shortId(c)}`,
    "```",
  ];
  let body = [...head, ...files, ...tail].join("\n");
  if (body.length > 5500) body = [...head, `The project's files are in [the case](${page}).`, "", ...tail].join("\n");
  const title = `LookML resolution differs from Looker: ${c.title}`;
  return `${tool.url.replace(/\/$/, "")}/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
}

function renderDetail(data, tools, c) {
  const left = h(
    "div",
    { class: "detail__left" },
    h("p", { class: "detail__rule" }, h("b", {}, "Rule. "), c.rule),
    c.citations.map((cit) => h("blockquote", { class: "quote" }, `“${cit.quote}”`, h("a", { href: cit.url }, cit.label))),
    c.status === "provisional" && c.provisional?.question ? h("p", { class: "question" }, h("b", {}, "Open question. "), c.provisional.question) : null,
    h(
      "div",
      { class: "files" },
      c.files.map((f) => h("pre", {}, h("span", { class: "path" }, `# ${f.path}`), highlight(f.content.trimEnd()))),
    ),
  );

  const upstream = UPSTREAM.filter((u) => u.caseId === shortId(c));
  const right = h(
    "div",
    { class: "detail__right" },
    h("p", { class: "small" }, "What Looker produces"),
    h("pre", { class: "expect" }, expectLines(c.expect).join("\n")),
    h("p", { class: "small" }, "What each tool produces"),
    h(
      "div",
      { class: "results" },
      tools.map((tool) => {
        const verdict = c.verdicts[tool.name] ?? { outcome: "n/a", reasons: [] };
        const o = OUTCOME[verdict.outcome];
        const filed = upstream.find((u) => u.tool === tool.name);
        return h(
          "div",
          { class: "result" },
          h("span", { class: `mark mark--${o.cls}`, "aria-hidden": "true" }, o.mark),
          h(
            "div",
            {},
            h("span", { class: "result__tool" }, `${tool.label} `, h("span", {}, `${tool.version} · ${o.label}`)),
            verdict.reasons.length ? h("ul", {}, verdict.reasons.map((r) => h("li", {}, r))) : null,
          ),
          differs(verdict.outcome) && tool.url
            ? h(
                "p",
                { class: "result__report" },
                filed
                  ? ["Filed upstream: ", h("a", { href: filed.url }, filed.label)]
                  : h("a", { href: issueUrl(data, c, tool), target: "_blank", rel: "noopener" }, `Report to ${tool.label} `, h("span", { "aria-hidden": "true" }, "↗"), h("span", { class: "sr-only" }, "(opens a prefilled issue in a new tab)")),
              )
            : null,
        );
      }),
    ),
    h(
      "pre",
      { class: "repro" },
      h("span", { class: "c" }, "# reproduce for your tool\n"),
      `lookml-conformance run --only ${shortId(c)} \\\n  --command "python my_adapter.py"`,
    ),
  );

  return h("div", { class: "detail", id: `detail-${shortId(c)}` }, left, right);
}

function visibleCases(data, tools, category = state.category) {
  const tool = tools.find((t) => t.name === state.tool);
  return data.cases.filter((c) => {
    if (category && c.category !== category) return false;
    if (tool && !differs(outcomeOf(c, tool))) return false;
    if (state.onlyDiffers && !tools.some((t) => differs(outcomeOf(c, t)))) return false;
    if (state.onlyFiled && !filedFor(c).some((u) => !tool || u.tool === tool.name)) return false;
    return true;
  });
}

function renderCases(data, tools) {
  // Counts follow the other filters; a category with nothing to show is disabled.
  const matching = visibleCases(data, tools, "");
  const counts = Object.fromEntries(data.categories.map((cat) => [cat.id, matching.filter((c) => c.category === cat.id).length]));
  if (state.category && !counts[state.category]) state.category = "";
  const chip = (id, label, n) =>
    h(
      "button",
      {
        class: "chip",
        type: "button",
        disabled: id !== "" && n === 0,
        "aria-pressed": String(state.category === id),
        onclick: () => {
          state.category = id;
          renderCases(data, tools);
        },
      },
      `${label} `,
      h("span", {}, n),
    );
  $("#chips").replaceChildren(chip("", "All", matching.length), ...data.categories.map((cat) => chip(cat.id, cat.title, counts[cat.id])));
  $("#tool-filter").value = state.tool;
  $("#only-differs").checked = state.onlyDiffers;
  $("#only-filed").checked = state.onlyFiled;

  const shown = visibleCases(data, tools);
  const tool = tools.find((t) => t.name === state.tool);
  const filedCount = UPSTREAM.filter((u) => tool && u.tool === tool.name).length;
  $("#filter-note").textContent = tool
    ? `The ${shown.length} cases where ${tool.label} ${tool.version} differs from Looker${state.category ? ` in ${data.categories.find((c) => c.id === state.category).title.toLowerCase()}` : ""}.${filedCount ? ` ${filedCount} filed upstream.` : ""}`
    : "";

  const table = $("#cases-table");
  table.style.setProperty("--tools", tools.length);
  const head = h(
    "div",
    { class: "cases__head" },
    h("span", {}, "case"),
    h("span", {}, "rule"),
    tools.map((t) => h("span", {}, t.label)),
  );
  const rows = shown.map((c) => {
    const id = shortId(c);
    const open = state.open === id;
    return h(
      "div",
      { class: `case${open ? " is-open" : ""}`, id: `case-${id}` },
      h(
        "button",
        {
          class: "case__summary",
          type: "button",
          "aria-expanded": String(open),
          "aria-controls": `detail-${id}`,
          onclick: () => {
            state.open = open ? "" : id;
            history.replaceState(null, "", open ? location.pathname : `#case=${id}`);
            renderCases(data, tools);
          },
        },
        h("span", { class: "case__id" }, id),
        h(
          "span",
          { class: "case__title" },
          c.title,
          c.status === "provisional" ? h("span", { class: "badge" }, "provisional") : null,
          filedFor(c).length ? h("span", { class: "badge badge--filed", title: filedFor(c).map((u) => `${u.label}: ${u.title}`).join("\n") }, "filed upstream") : null,
        ),
        h(
          "span",
          { class: "case__marks" },
          tools.map((t) => {
            const o = OUTCOME[outcomeOf(c, t)];
            return h(
              "span",
              { class: `mark mark--${o.cls}`, "data-tool": t.label, title: `${t.label}: ${o.label}` },
              h("span", { "aria-hidden": "true" }, o.mark),
              h("span", { class: "sr-only" }, `${t.label}: ${o.label}.`),
            );
          }),
        ),
      ),
      open ? renderDetail(data, tools, c) : null,
    );
  });
  table.replaceChildren(head, ...(rows.length ? rows : [h("p", { class: "empty" }, "No cases match these filters.")]));
}

function applyHash(data, tools, scroll) {
  const params = new URLSearchParams(location.hash.slice(1));
  const toolName = params.get("tool");
  const caseId = params.get("case");
  if (toolName && tools.some((t) => t.name === toolName)) {
    Object.assign(state, { tool: toolName, category: "", onlyDiffers: false, onlyFiled: false, open: "" });
    renderCases(data, tools);
    if (scroll) $("#cases").scrollIntoView();
  } else if (caseId && data.cases.some((c) => shortId(c) === caseId)) {
    const c = data.cases.find((x) => shortId(x) === caseId);
    const tool = tools.find((t) => t.name === state.tool);
    if (tool && !differs(outcomeOf(c, tool))) state.tool = "";
    if (state.category && state.category !== c.category) state.category = "";
    state.onlyDiffers = false;
    state.onlyFiled = false;
    state.open = caseId;
    renderCases(data, tools);
    if (scroll) $(`#case-${caseId}`).scrollIntoView();
  }
}

// ---------------------------------------------------------------- page

function render(data) {
  const tools = [...data.tools].sort(
    (a, b) => b.score.all.passed / b.score.all.applicable - a.score.all.passed / a.score.all.applicable,
  );
  $("#case-count").textContent = data.cases.length;
  $("#cases-meta").textContent = `${data.suite.cases} cases · ${data.suite.citations} quotes from ${data.suite.pages} documentation pages`;
  $("#footer-date").textContent = `Scored ${data.date} against the versions in adapters.json.`;

  const select = $("#tool-filter");
  select.replaceChildren(h("option", { value: "" }, "all tools"), ...tools.map((t) => h("option", { value: t.name }, t.label)));
  select.addEventListener("change", () => {
    state.tool = select.value;
    history.replaceState(null, "", state.tool ? `#tool=${state.tool}` : location.pathname);
    renderCases(data, tools);
  });
  $("#only-differs").addEventListener("change", (e) => {
    state.onlyDiffers = e.target.checked;
    renderCases(data, tools);
  });
  $("#only-filed").addEventListener("change", (e) => {
    state.onlyFiled = e.target.checked;
    renderCases(data, tools);
  });

  renderMatrix(data, tools);
  renderCases(data, tools);
  applyHash(data, tools, true);
  window.addEventListener("hashchange", () => applyHash(data, tools, true));
}

fetch("data.json")
  .then((response) => {
    if (!response.ok) throw new Error(`data.json: HTTP ${response.status}`);
    return response.json();
  })
  .then(render)
  .catch((error) => {
    $("#results").append(h("p", { class: "note" }, `Could not load the results (${error.message}). They are also in `, h("a", { href: `${REPO}/blob/main/results/latest.md` }, "results/latest.md"), "."));
  });
