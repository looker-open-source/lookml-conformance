"use strict";

// Renders the results page from data.json (written by `lookml-conformance site`).
// The DOM is built with createElement and textContent only; no data is parsed as HTML.

const OUTCOME_LABEL = { pass: "pass", fail: "fail", error: "error", "n/a": "n/a" };
const OUTCOME_CLASS = { pass: "pass", fail: "fail", error: "error", "n/a": "na" };
const EXAMPLE_CASE = "r03_two_models_refine_one_view_differently";

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

const pct = ({ passed, applicable }) => (applicable ? Math.round((100 * passed) / applicable) : 0);
// Score colours: under 50% red, 50 to 79% yellow, 80% and up green.
const tier = (rate) => (rate < 50 ? "low" : rate < 80 ? "mid" : "high");
const isLineageTool = (tool) => tool.kind !== "Parser";

function tally(data, toolName, cases) {
  const verdicts = cases.map((c) => c.verdicts[toolName]).filter((v) => v && v.outcome !== "n/a");
  return { passed: verdicts.filter((v) => v.outcome === "pass").length, applicable: verdicts.length };
}

// ---------------------------------------------------------------- LookML highlighting

const LOOKML_TOKENS = /(#[^\n]*)|("(?:[^"\\]|\\.)*")|(;;)|(\$\{[^}]*\}|@\{[^}]*\})|(\b[a-z_]+(?=:))|(\+[a-z_]+)/g;

function highlight(source) {
  const out = document.createDocumentFragment();
  let last = 0;
  for (const match of source.matchAll(LOOKML_TOKENS)) {
    if (match.index > last) out.append(source.slice(last, match.index));
    const [text, comment, string, terminator, reference, key, refinement] = match;
    const cls = comment ? "tok-c" : string ? "tok-s" : terminator ? "tok-r" : reference ? "tok-s" : key ? "tok-k" : refinement ? "tok-k" : "tok-p";
    out.append(h("span", { class: cls }, text));
    last = match.index + text.length;
  }
  out.append(source.slice(last));
  return out;
}

function fileBlock(file) {
  return h("div", { class: "file" }, h("div", { class: "file__name" }, file.path), h("pre", {}, h("code", {}, highlight(file.content))));
}

// ---------------------------------------------------------------- hero, stats, impact

function renderHero(data) {
  const tools = [...data.tools].sort((a, b) => pct(b.score.all) - pct(a.score.all));
  $("#hero-lede").textContent =
    "LookML defines the metrics behind an organization's reporting, and catalogs, lineage tools and AI assistants " +
    "all depend on reading it the way Looker does. " +
    `This suite turns that behavior into ${data.suite.cases} small, testable cases, each tied to a quoted rule.`;

  const board = $("#hero-board");
  board.replaceChildren(
    h("div", { class: "board__title" }, h("h3", {}, "Cases passed"), h("span", {}, `scored ${data.date}`)),
    ...tools.map((tool) => {
      const rate = pct(tool.score.all);
      const fill = h("span", { "data-width": `${rate}%` });
      return h(
        "div",
        { class: "bar-row" },
        h("div", { class: "bar-row__name" }, tool.label, h("small", {}, `${tool.kind} · ${tool.version}`)),
        h("div", { class: `bar tier--${tier(rate)}`, role: "img", "aria-label": `${tool.label}: ${rate}%` }, fill),
        h("div", { class: "bar-row__pct" }, `${rate}%`),
      );
    }),
  );
  requestAnimationFrame(() => board.querySelectorAll("[data-width]").forEach((el) => (el.style.width = el.dataset.width)));

  const applicable = data.cases.reduce(
    (sum, c) => sum + Object.values(c.verdicts).filter((v) => v.outcome !== "n/a").length,
    0,
  );
  const stats = [
    ["Cases", data.suite.cases],
    ["Verbatim doc quotes", data.suite.citations],
    ["Looker doc pages cited", data.suite.pages],
    ["Tools scored", data.tools.length],
    ["Verdicts", applicable],
  ];
  $("#stats").replaceChildren(...stats.map(([label, value]) => h("div", {}, h("dt", {}, label), h("dd", {}, value))));
}

function renderImpact(data) {
  const lineage = data.tools.filter(isLineageTool);
  const inCategory = (category) => data.cases.filter((c) => c.category === category);

  const refinements = inCategory("refinements");
  const bestRefinements = Math.max(...lineage.map((t) => tally(data, t.name, refinements).passed));

  const scopeCases = data.cases.filter((c) => ["r03_two_models_refine_one_view_differently", "m01_model_without_the_refinement_sees_the_base"].includes(c.id));
  const scopeFailures = lineage.filter((t) => scopeCases.some((c) => c.verdicts[t.name]?.outcome === "fail")).length;

  const extendsCases = inCategory("extends");
  const extendsTotals = lineage.map((t) => tally(data, t.name, extendsCases));
  const extendsPassed = extendsTotals.reduce((s, t) => s + t.passed, 0);
  const extendsApplicable = extendsTotals.reduce((s, t) => s + t.applicable, 0);

  const lineageCases = inCategory("lineage");
  const bestLineage = Math.max(...lineage.map((t) => tally(data, t.name, lineageCases).passed));

  const cards = [
    {
      big: [bestRefinements, ` / ${refinements.length}`],
      title: "Refinements",
      text: `The strongest lineage tool passes ${bestRefinements} of the ${refinements.length} refinement cases. Getting them right means applying refinements in include order, per model, merging fields parameter by parameter and honoring final: yes.`,
    },
    {
      big: [lineage.length - scopeFailures, ` / ${lineage.length}`],
      title: "Model scope",
      text: `When two models refine the same view differently, Looker gives each model its own version of the view. ${lineage.length - scopeFailures} of ${lineage.length} lineage tools keep the versions apart; the others report one version for both models.`,
    },
    {
      big: [extendsPassed, ` / ${extendsApplicable}`],
      title: "Extends",
      text: `Across the lineage tools, ${extendsPassed} of ${extendsApplicable} extends results pass. Views that extend several views, or gain extends through a refinement, need their parents merged in priority order.`,
    },
    {
      big: [bestLineage, ` / ${lineageCases.length}`],
      title: "Derived table lineage",
      text: `The strongest lineage tool passes ${bestLineage} of the ${lineageCases.length} lineage cases. They cover \${view.SQL_TABLE_NAME} references, chains of derived tables, references to refined views and native derived tables.`,
    },
  ];
  $("#impact-cards").replaceChildren(
    ...cards.map((card) =>
      h("article", { class: `impact__card card tier--${tier(pct({ passed: card.big[0], applicable: Number(card.big[1].replace(/\D/g, "")) }))}` }, h("div", { class: "impact__big" }, card.big[0], h("small", {}, card.big[1])), h("h3", {}, card.title), h("p", {}, card.text)),
    ),
  );
}

// ---------------------------------------------------------------- example case

function resolvedValue(caseData, toolName, model, view, expected) {
  const verdict = caseData.verdicts[toolName];
  if (!verdict || verdict.outcome === "pass") return { value: expected, ok: true };
  const prefix = `${model}.${view}.sql_table_name: expected `;
  const reason = verdict.reasons.find((r) => r.startsWith(prefix));
  if (!reason) return { value: expected, ok: true };
  const got = reason.split(", got ").pop();
  return { value: got.replace(/^'|'$/g, ""), ok: false };
}

const includesOf = (file) => [...file.content.matchAll(/include:\s*"([^"]+)"/g)].map((m) => m[1].replace(/^\//, ""));
const includedBy = (model, path) => includesOf(model).some((inc) => path === inc || path.startsWith(`${inc}.`));

function renderExample(data) {
  const example = data.cases.find((c) => c.id === EXAMPLE_CASE);
  if (!example) {
    $("#example").remove();
    return;
  }
  $("#example-id").textContent = example.id;
  $("#example-title").textContent = example.title;
  $("#example-rule").textContent = example.rule;

  const models = Object.keys(example.expect.models);
  const expected = Object.fromEntries(models.map((m) => [m, example.expect.models[m].views.orders.sql_table_name]));
  const modelFile = Object.fromEntries(models.map((m) => [m, example.files.find((f) => f.path === `${m}.model.lkml`)]));
  const others = example.files.filter((f) => !Object.values(modelFile).includes(f));
  const own = Object.fromEntries(
    models.map((m) => [m, others.filter((f) => includedBy(modelFile[m], f.path) && models.every((n) => n === m || !includedBy(modelFile[n], f.path)))]),
  );
  const shared = others.filter((f) => !models.some((m) => own[m].includes(f)));
  const baseFile = shared.find((f) => /^view:\s*orders\b/m.test(f.content));
  const base = baseFile?.content.match(/sql_table_name:\s*([^\s;]+)/)?.[1];

  $("#example-setup").textContent =
    `Both models include the same orders view${base ? ` (table ${base})` : ""}. Each also includes its own refinement ` +
    `that points orders at a different table, so Looker resolves orders differently in each model.`;
  $("#example-files").replaceChildren(
    h("div", { class: "project__shared" }, h("p", { class: "project__label" }, "Shared by both models"), ...shared.map(fileBlock)),
    h(
      "div",
      { class: "project__models" },
      ...models.map((m) =>
        h(
          "div",
          { class: "project__model" },
          h("p", { class: "project__label" }, `Model ${m}`, h("span", {}, `orders → ${expected[m]}`)),
          fileBlock(modelFile[m]),
          ...own[m].map(fileBlock),
        ),
      ),
    ),
  );

  const explain = (m, value) => {
    if (value === base) return "refinement not applied";
    const from = models.find((n) => n !== m && expected[n] === value);
    return from ? `got model ${from}'s refinement` : "";
  };
  const table = $("#example-table");
  table.replaceChildren(
    h("thead", {}, h("tr", {}, h("th", {}, "Tool"), ...models.map((m) => h("th", {}, `Model ${m}`)))),
    h(
      "tbody",
      {},
      h("tr", { class: "is-looker" }, h("td", {}, "Looker (expected)"), ...models.map((m) => h("td", { "data-label": `Model ${m}` }, h("code", {}, expected[m])))),
      ...data.tools.map((tool) =>
        h(
          "tr",
          {},
          h("td", {}, tool.label),
          ...models.map((m) => {
            const { value, ok } = resolvedValue(example, tool.name, m, "orders", expected[m]);
            const note = ok ? "" : explain(m, value);
            return h(
              "td",
              { class: ok ? "cell-ok" : "cell-bad", "data-label": `Model ${m}` },
              h("span", { class: "cell__mark", "aria-label": ok ? "pass" : "fail" }, ok ? "✓" : "✗"),
              h("code", {}, value),
              note ? h("small", {}, note) : null,
            );
          }),
        ),
      ),
    ),
  );
  const citation = example.citations[0];
  $("#example-quote").replaceChildren(h("p", {}, `“${citation.quote}”`), h("a", { href: citation.url }, citation.label));
}

// ---------------------------------------------------------------- scoreboard

function renderTools(data) {
  const lineage = data.tools.filter(isLineageTool);
  $("#results-lede").textContent =
    `Released versions scored on ${data.date}. Rates count applicable cases only; ` +
    `a case is not applicable when a tool does not produce that output at all, such as explores read from the Looker API. ` +
    `${lineage.length} of ${data.tools.length} tools build lineage from LookML.`;

  $("#tools").replaceChildren(
    ...data.tools.map((tool) => {
      const rate = pct(tool.score.all);
      const rows = data.categories.map((category) => {
        const t = tally(data, tool.name, data.cases.filter((c) => c.category === category.id));
        if (!t.applicable) return null;
        return h(
          "div",
          { class: "tool__row" },
          h("span", {}, category.title),
          h("div", { class: `mini tier--${tier(pct(t))}` }, h("span", { style: `width:${pct(t)}%` })),
          h("b", {}, `${t.passed}/${t.applicable}`),
        );
      });
      return h(
        "article",
        { class: "tool card" },
        h(
          "div",
          { class: "tool__head" },
          h(
            "div",
            {},
            h("div", { class: "tool__name" }, tool.url ? h("a", { href: tool.url }, tool.label) : tool.label),
            h("div", { class: "tool__meta" }, `${tool.kind} · ${tool.language}`),
            h("div", { class: "tool__meta" }, `${tool.score.all.passed} of ${tool.score.all.applicable} cases`),
          ),
          h("div", { class: `ring tier--${tier(rate)}`, style: `--p:${rate}` }, h("span", {}, `${rate}%`)),
        ),
        h(
          "div",
          { class: "tool__rows" },
          h("div", { class: "tool__row" }, h("span", {}, "Confirmed"), h("div", { class: `mini tier--${tier(pct(tool.score.confirmed))}` }, h("span", { style: `width:${pct(tool.score.confirmed)}%` })), h("b", {}, `${tool.score.confirmed.passed}/${tool.score.confirmed.applicable}`)),
          h("div", { class: "tool__row" }, h("span", {}, "Provisional"), h("div", { class: `mini tier--${tier(pct(tool.score.provisional))}` }, h("span", { style: `width:${pct(tool.score.provisional)}%` })), h("b", {}, `${tool.score.provisional.passed}/${tool.score.provisional.applicable}`)),
        ),
        h("div", { class: "tool__rows" }, rows),
        tool.package ? h("div", { class: "pkg" }, tool.package) : null,
      );
    }),
  );
}

// ---------------------------------------------------------------- matrix

const state = { category: "all", confirmedOnly: false, failingOnly: false };

function renderFilters(data) {
  const options = [{ id: "all", title: "All" }, ...data.categories];
  const chips = options.map((option) =>
    h(
      "button",
      {
        class: "chip",
        type: "button",
        "aria-pressed": String(option.id === state.category),
        onclick: () => {
          state.category = option.id;
          chips.forEach((chip, i) => chip.setAttribute("aria-pressed", String(options[i].id === state.category)));
          renderMatrix(data);
        },
      },
      option.title,
    ),
  );
  $("#category-chips").replaceChildren(...chips);
  $("#only-confirmed").addEventListener("change", (event) => {
    state.confirmedOnly = event.target.checked;
    renderMatrix(data);
  });
  $("#only-failing").addEventListener("change", (event) => {
    state.failingOnly = event.target.checked;
    renderMatrix(data);
  });
}

function pill(outcome) {
  return h("span", { class: `pill pill--${OUTCOME_CLASS[outcome]}`, title: OUTCOME_LABEL[outcome] }, outcome === "pass" ? "✓" : outcome === "fail" ? "✗" : outcome === "error" ? "!" : "–");
}

function visibleCases(data) {
  return data.cases.filter(
    (c) =>
      (state.category === "all" || c.category === state.category) &&
      (!state.confirmedOnly || c.status === "confirmed") &&
      (!state.failingOnly || Object.values(c.verdicts).some((v) => v.outcome === "fail" || v.outcome === "error")),
  );
}

function renderMatrix(data) {
  const cases = visibleCases(data);
  const table = $("#matrix");
  const head = h("thead", {}, h("tr", {}, h("th", {}, "Case"), ...data.tools.map((t) => h("th", {}, t.label))));
  const body = h("tbody");
  if (!cases.length) {
    body.append(h("tr", {}, h("td", { colspan: data.tools.length + 1, class: "empty" }, "No cases match these filters.")));
  }
  for (const category of data.categories) {
    const members = cases.filter((c) => c.category === category.id);
    if (!members.length) continue;
    body.append(h("tr", { class: "group" }, h("td", { colspan: data.tools.length + 1 }, category.title)));
    for (const c of members) {
      body.append(
        h(
          "tr",
          {
            class: "case-row",
            tabindex: "0",
            onclick: () => openCase(data, c.id),
            onkeydown: (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openCase(data, c.id);
              }
            },
          },
          h(
            "td",
            {},
            h("span", { class: "case-title" }, c.title, " ", c.status === "provisional" ? h("span", { class: "badge badge--provisional" }, "provisional") : null),
            h("span", { class: "case-id" }, c.id),
          ),
          ...data.tools.map((t) => h("td", {}, pill(c.verdicts[t.name]?.outcome ?? "n/a"))),
        ),
      );
    }
  }
  const foot = h(
    "tfoot",
    {},
    h("tr", {}, h("td", {}, `Passed (${cases.length} cases shown)`), ...data.tools.map((t) => {
      const result = tally(data, t.name, cases);
      return h("td", {}, `${result.passed}/${result.applicable}`);
    })),
  );
  table.replaceChildren(head, body, foot);
}

// ---------------------------------------------------------------- case drawer

function openCase(data, id) {
  const c = data.cases.find((item) => item.id === id);
  if (!c) return;
  const drawer = $("#drawer");
  const tools = Object.fromEntries(data.tools.map((t) => [t.name, t]));
  $("#drawer-body").replaceChildren(
    h("p", { class: "eyebrow eyebrow--muted" }, data.categories.find((k) => k.id === c.category)?.title ?? c.category, " · ", h("code", {}, c.id)),
    h("h2", { id: "drawer-title" }, c.title),
    h("span", { class: `badge badge--${c.status}` }, c.status),
    h("section", {}, h("h4", {}, "Rule"), h("p", {}, c.rule)),
    h(
      "section",
      {},
      h("h4", {}, "Looker documentation"),
      ...c.citations.map((citation) => h("blockquote", { class: "quote" }, h("p", {}, `“${citation.quote}”`), h("a", { href: citation.url }, citation.label))),
      c.rationale ? h("p", { class: "muted", style: "margin-top:12px" }, c.rationale) : null,
      c.provisional
        ? h("div", { class: "callout" }, h("strong", {}, "Open question. "), c.provisional.question, h("br"), h("strong", {}, "Pinned to: "), c.provisional.pinned_to)
        : null,
      c.invalid_in_looker ? h("div", { class: "callout" }, "Looker rejects this project. A tool may report an error but must not produce the forbidden result.") : null,
    ),
    h("section", {}, h("h4", {}, "LookML project"), ...c.files.map(fileBlock)),
    h("section", {}, h("h4", {}, "Expected resolution"), h("pre", { class: "json" }, JSON.stringify(c.expect, null, 2))),
    h(
      "section",
      {},
      h("h4", {}, "Verdicts"),
      h(
        "div",
        { class: "verdicts" },
        ...Object.entries(c.verdicts).map(([name, verdict]) =>
          h(
            "div",
            { class: "verdict" },
            h("div", { class: "verdict__head" }, pill(verdict.outcome), tools[name]?.label ?? name, h("span", { class: "muted", style: "font-weight:500" }, OUTCOME_LABEL[verdict.outcome])),
            verdict.reasons.length ? h("ul", {}, ...verdict.reasons.map((r) => h("li", {}, r))) : null,
          ),
        ),
      ),
    ),
  );
  drawer.hidden = false;
  document.body.style.overflow = "hidden";
  if (location.hash !== `#case/${id}`) history.replaceState(null, "", `#case/${id}`);
  drawer.querySelector(".drawer__close").focus();
}

function closeCase() {
  const drawer = $("#drawer");
  if (drawer.hidden) return;
  drawer.hidden = true;
  document.body.style.overflow = "";
  if (location.hash.startsWith("#case/")) history.replaceState(null, "", "#cases");
}

// ---------------------------------------------------------------- boot

async function main() {
  const response = await fetch("data.json");
  const data = await response.json();
  renderHero(data);
  renderImpact(data);
  renderExample(data);
  renderTools(data);
  renderFilters(data);
  renderMatrix(data);
  $("#method-note").textContent =
    `${data.suite.confirmed} cases are confirmed: the expectation follows from the quoted documentation. ` +
    `${data.suite.provisional} are provisional: the documentation leaves the behavior open, so the case names the open question ` +
    `and the public source its expectation is pinned to, until it is checked on a Looker instance.`;
  $("#footer-date").textContent = `Scorecard from ${data.date} · ${data.tools.map((t) => `${t.label} ${t.version}`).join(" · ")}`;

  document.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeCase));
  document.addEventListener("keydown", (event) => event.key === "Escape" && closeCase());
  const fromHash = () => {
    const match = location.hash.match(/^#case\/(.+)$/);
    if (match) openCase(data, decodeURIComponent(match[1]));
  };
  window.addEventListener("hashchange", fromHash);
  fromHash();
}

main().catch((error) => {
  document.querySelector("main").prepend(h("p", { class: "wrap empty" }, `Could not load data.json: ${error}`));
});
