/*
 * 상품 옵션 생성 도구 (영카트 itemform.php 선택옵션 · 추가옵션).
 * 옵션 행은 textarea 의 JSON 이 원본이다. 도구는 그 위에서 옵션명 · 항목(쉼표 구분)으로 조합 행을 만들고
 * 행마다 추가금액 · 재고수량 · 통보수량 · 사용여부를 고친 뒤 JSON 과 옵션명 칸(it_option_subject ·
 * it_supply_subject)을 다시 쓴다. "JSON 직접 편집"을 켜면 textarea 를 그대로 고친다. 서버가 다시 검사한다.
 */
(() => {
  "use strict";

  const SEP = "\u001e";
  const INTEGER = /^-?\d+$/;

  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    Object.entries(props).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      if (key === "text") node.textContent = value;
      else if (key === "class") node.className = value;
      else if (key === "dataset") Object.assign(node.dataset, value);
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (typeof value === "boolean") node[key] = value;
      else node.setAttribute(key, value);
    });
    children.forEach((child) => child && node.append(child));
    return node;
  }

  function splitValues(text) {
    const values = [];
    String(text || "")
      .split(",")
      .map((part) => part.trim())
      .forEach((value) => {
        if (value && !values.includes(value)) values.push(value);
      });
    return values;
  }

  function combinations(lists) {
    let combos = [[]];
    lists.forEach((values) => {
      combos = combos.flatMap((combo) => values.map((value) => [...combo, value]));
    });
    return combos.map((combo) => combo.join(SEP));
  }

  function toNumberOrRaw(value) {
    const text = String(value ?? "").trim();
    return INTEGER.test(text) ? Number(text) : text;
  }

  function parseRows(text) {
    const source = String(text || "").trim();
    if (!source) return { rows: [] };
    let data;
    try {
      data = JSON.parse(source);
    } catch {
      return { error: "JSON 형식이 올바르지 않습니다." };
    }
    if (!Array.isArray(data)) return { error: "옵션 JSON 은 배열이어야 합니다." };
    const rows = [];
    for (const item of data) {
      if (!item || typeof item !== "object" || Array.isArray(item)) return { error: "옵션 행은 객체여야 합니다." };
      const type = Number(item.io_type ?? 0);
      if (type !== 0 && type !== 1) return { error: "io_type 이 0 · 1 이 아닌 행이 있습니다." };
      rows.push({
        no: Number.isInteger(item.io_no) ? item.io_no : undefined,
        id: String(item.io_id ?? ""),
        type,
        price: String(item.io_price ?? 0),
        stock: String(item.io_stock_qty ?? 0),
        noti: String(item.io_noti_qty ?? 0),
        use: String(item.io_use ?? 1) === "0" ? "0" : "1",
        checked: false,
      });
    }
    return { rows };
  }

  function init(root) {
    const textarea = root.querySelector("textarea");
    const ui = root.querySelector("[data-builder-ui]");
    const rawPanel = root.querySelector("[data-raw-panel]");
    const form = root.closest("form");
    if (!textarea || !ui || !rawPanel) return;

    const maxLevels = Number(root.dataset.maxLevels) || 3;
    const defaultStock = String(Number(root.dataset.defaultStock) || 0);
    const defaultNoti = String(Number(root.dataset.defaultNoti) || 0);
    const subjectInput = form?.querySelector(`[name="${root.dataset.subjectField}"]`);
    const supplyInput = form?.querySelector(`[name="${root.dataset.supplyField}"]`);

    let options = [];
    let supplies = [];
    let rawMode = false;
    let dirty = false; // only an edit made here rewrites the JSON (untouched rows stay as stored)

    const message = el("p", { class: "g5-option-builder__message", role: "status" });
    const rawToggle = el("input", { type: "checkbox", id: `${textarea.id}_raw` });
    const toolbar = el("div", { class: "g5-option-builder__toolbar" }, [
      el("label", { for: rawToggle.id, class: "g5-option-builder__toggle" }, [rawToggle, el("span", { text: "JSON 직접 편집 (고급)" })]),
    ]);
    root.insertBefore(toolbar, ui);
    root.insertBefore(message, ui);

    function say(text, isError = false) {
      message.textContent = text || "";
      message.classList.toggle("is-error", Boolean(isError));
    }

    // --- 선택옵션 입력 --------------------------------------------------------
    const levelInputs = [];
    const levelGrid = el("div", { class: "g5-option-builder__levels" });
    for (let level = 1; level <= maxLevels; level += 1) {
      const name = el("input", { type: "text", class: "g5-option-builder__input", placeholder: level === 1 ? "예: 색상" : "예: 사이즈", "aria-label": `옵션${level} 이름` });
      const values = el("input", { type: "text", class: "g5-option-builder__input g5-option-builder__input--wide", placeholder: "항목을 쉼표로 구분 (예: 빨강,파랑)", "aria-label": `옵션${level} 항목` });
      levelInputs.push({ name, values });
      levelGrid.append(el("div", { class: "g5-option-builder__level" }, [el("span", { class: "g5-option-builder__label", text: `옵션${level}` }), name, values]));
    }

    // --- 추가옵션 입력 --------------------------------------------------------
    const supplyLines = el("div", { class: "g5-option-builder__levels" });
    function addSupplyLine(name = "", values = "") {
      const nameInput = el("input", { type: "text", class: "g5-option-builder__input", value: name, placeholder: "예: 포장", "aria-label": "추가옵션 항목명" });
      const valuesInput = el("input", { type: "text", class: "g5-option-builder__input g5-option-builder__input--wide", value: values, placeholder: "값을 쉼표로 구분 (예: 선물포장,기본포장)", "aria-label": "추가옵션 값" });
      const line = el("div", { class: "g5-option-builder__level", dataset: { supplyLine: "" } }, [
        el("span", { class: "g5-option-builder__label", text: "추가" }),
        nameInput,
        valuesInput,
        el("button", { type: "button", class: "g5-option-builder__btn g5-option-builder__btn--ghost", text: "줄 삭제", onclick: () => line.remove() }),
      ]);
      supplyLines.append(line);
    }

    // --- 행 표 ----------------------------------------------------------------
    function rowTable(kind) {
      const body = el("tbody");
      const all = el("input", { type: "checkbox", "aria-label": "전체 선택" });
      const table = el("table", { class: "g5-option-builder__table" }, [
        el("thead", {}, [
          el("tr", {}, [
            el("th", {}, [all]),
            el("th", { text: kind === 0 ? "옵션" : "추가옵션" }),
            el("th", { text: "추가금액" }),
            el("th", { text: "재고수량" }),
            el("th", { text: "통보수량" }),
            el("th", { text: "사용여부" }),
          ]),
        ]),
        body,
      ]);
      all.addEventListener("change", () => {
        (kind === 0 ? options : supplies).forEach((row) => { row.checked = all.checked; });
        render();
      });
      const bulkPrice = el("input", { type: "number", step: "1", class: "g5-option-builder__input g5-option-builder__input--num", placeholder: "추가금액", "aria-label": "일괄 추가금액" });
      const bulkStock = el("input", { type: "number", step: "1", min: "0", class: "g5-option-builder__input g5-option-builder__input--num", placeholder: "재고", "aria-label": "일괄 재고수량" });
      const bulkNoti = el("input", { type: "number", step: "1", min: "0", class: "g5-option-builder__input g5-option-builder__input--num", placeholder: "통보", "aria-label": "일괄 통보수량" });
      const bulkUse = el("select", { class: "g5-option-builder__input", "aria-label": "일괄 사용여부" }, [
        el("option", { value: "", text: "사용여부 그대로" }),
        el("option", { value: "1", text: "사용함" }),
        el("option", { value: "0", text: "사용안함" }),
      ]);
      const bulk = el("div", { class: "g5-option-builder__bulk" }, [
        el("span", { class: "g5-option-builder__label", text: "선택한 행" }),
        bulkPrice, bulkStock, bulkNoti, bulkUse,
        el("button", {
          type: "button", class: "g5-option-builder__btn", text: "일괄적용",
          onclick: () => {
            const rows = (kind === 0 ? options : supplies).filter((row) => row.checked);
            if (!rows.length) return say("일괄적용할 행을 먼저 선택해 주세요.", true);
            rows.forEach((row) => {
              if (bulkPrice.value !== "") row.price = bulkPrice.value;
              if (bulkStock.value !== "") row.stock = bulkStock.value;
              if (bulkNoti.value !== "") row.noti = bulkNoti.value;
              if (bulkUse.value !== "") row.use = bulkUse.value;
            });
            say(`${rows.length}개 행에 적용했습니다.`);
            render();
          },
        }),
        el("button", {
          type: "button", class: "g5-option-builder__btn g5-option-builder__btn--danger", text: "선택삭제",
          onclick: () => {
            const list = kind === 0 ? options : supplies;
            const kept = list.filter((row) => !row.checked);
            if (kept.length === list.length) return say("삭제할 행을 먼저 선택해 주세요.", true);
            if (kind === 0) options = kept; else supplies = kept;
            say(`${list.length - kept.length}개 행을 지웠습니다.`);
            render();
          },
        }),
      ]);
      return { table, body, all, bulk };
    }

    const optionTable = rowTable(0);
    const supplyTable = rowTable(1);

    function cellInput(row, key, attrs) {
      return el("input", {
        type: "number", step: "1", class: "g5-option-builder__input g5-option-builder__input--num", value: row[key], ...attrs,
        oninput: (event) => { row[key] = event.target.value; sync(); },
      });
    }

    function renderRows(kind) {
      const { body, all } = kind === 0 ? optionTable : supplyTable;
      const rows = kind === 0 ? options : supplies;
      body.replaceChildren();
      if (!rows.length) {
        body.append(el("tr", {}, [el("td", { colspan: "6", class: "g5-option-builder__empty", text: kind === 0 ? "선택옵션이 없습니다." : "추가옵션이 없습니다." })]));
      }
      rows.forEach((row) => {
        const label = row.id.split(SEP).join(kind === 0 ? " > " : " : ");
        const use = el("select", { class: "g5-option-builder__input", "aria-label": `${label} 사용여부`, onchange: (event) => { row.use = event.target.value; sync(); } }, [
          el("option", { value: "1", text: "사용함" }),
          el("option", { value: "0", text: "사용안함" }),
        ]);
        use.value = row.use;
        body.append(el("tr", {}, [
          el("td", {}, [el("input", { type: "checkbox", checked: row.checked, "aria-label": `${label} 선택`, onchange: (event) => { row.checked = event.target.checked; } })]),
          el("td", { class: "g5-option-builder__name", text: label }),
          el("td", {}, [cellInput(row, "price", { "aria-label": `${label} 추가금액` })]),
          el("td", {}, [cellInput(row, "stock", { min: "0", "aria-label": `${label} 재고수량` })]),
          el("td", {}, [cellInput(row, "noti", { min: "0", "aria-label": `${label} 통보수량` })]),
          el("td", {}, [use]),
        ]));
      });
      all.checked = rows.length > 0 && rows.every((row) => row.checked);
    }

    function keepValues(ids, previous, type) {
      const byId = new Map(previous.map((row) => [row.id, row]));
      return ids.map((id) => byId.get(id) || { id, type, price: "0", stock: defaultStock, noti: defaultNoti, use: "1", checked: false });
    }

    function confirmDropped(previous, ids) {
      const dropped = previous.filter((row) => !ids.includes(row.id)).length;
      return !dropped || window.confirm(`기존 옵션 ${dropped}개가 목록에서 빠집니다. 계속할까요?`);
    }

    function generateOptions() {
      const levels = [];
      for (const [index, { name, values }] of levelInputs.entries()) {
        const subject = name.value.trim();
        const list = splitValues(values.value);
        if (!subject && !list.length) continue;
        if (!subject || !list.length) return say(`옵션${index + 1}의 이름과 항목을 모두 입력해 주세요.`, true);
        if (levels.length !== index) return say(`옵션${levels.length + 1}부터 차례로 입력해 주세요.`, true);
        if (/['"]/.test(subject + list.join(""))) return say("옵션명과 항목에는 따옴표를 쓸 수 없습니다.", true);
        levels.push({ subject, list });
      }
      if (!levels.length) return say("옵션1과 옵션1 항목을 입력해 주십시오.", true);
      const ids = combinations(levels.map((level) => level.list));
      if (!confirmDropped(options, ids)) return;
      options = keepValues(ids, options, 0);
      if (subjectInput) subjectInput.value = levels.map((level) => level.subject).join(",");
      say(`선택옵션 ${ids.length}개를 만들었습니다. 저장해야 반영됩니다.`);
      render();
    }

    function generateSupplies() {
      const ids = [];
      for (const line of supplyLines.querySelectorAll("[data-supply-line]")) {
        const [nameInput, valuesInput] = line.querySelectorAll("input");
        const subject = nameInput.value.trim();
        const list = splitValues(valuesInput.value);
        if (!subject && !list.length) continue;
        if (!subject || !list.length) return say("추가옵션 항목명과 값을 모두 입력해 주세요.", true);
        if (/['"]/.test(subject + list.join(""))) return say("추가옵션에는 따옴표를 쓸 수 없습니다.", true);
        list.forEach((value) => {
          const id = `${subject}${SEP}${value}`;
          if (!ids.includes(id)) ids.push(id);
        });
      }
      if (!confirmDropped(supplies, ids)) return;
      supplies = keepValues(ids, supplies, 1);
      say(`추가옵션 ${ids.length}개를 만들었습니다. 저장해야 반영됩니다.`);
      render();
    }

    function fillInputs() {
      const subjects = String(subjectInput?.value || "").split(",");
      levelInputs.forEach(({ name, values }, index) => {
        const parts = [];
        options.forEach((row) => {
          const part = row.id.split(SEP)[index];
          if (part && !parts.includes(part)) parts.push(part);
        });
        name.value = parts.length ? (subjects[index] || "").trim() : "";
        values.value = parts.join(",");
      });
      supplyLines.replaceChildren();
      const groups = new Map();
      supplies.forEach((row) => {
        const [subject, value] = row.id.split(SEP);
        if (!groups.has(subject)) groups.set(subject, []);
        if (value && !groups.get(subject).includes(value)) groups.get(subject).push(value);
      });
      groups.forEach((values, subject) => addSupplyLine(subject, values.join(",")));
      if (!groups.size) addSupplyLine();
    }

    function serialize() {
      return [...options, ...supplies].map((row) => ({
        ...(row.no !== undefined ? { io_no: row.no } : {}),
        io_id: row.id,
        io_type: row.type,
        io_price: toNumberOrRaw(row.price),
        io_stock_qty: toNumberOrRaw(row.stock),
        io_noti_qty: toNumberOrRaw(row.noti),
        io_use: Number(row.use),
      }));
    }

    function sync() {
      if (rawMode) return;
      dirty = true;
      const rows = serialize();
      textarea.value = rows.length ? JSON.stringify(rows, null, 1) : "[]";
      if (!options.length && subjectInput) subjectInput.value = "";
      if (supplyInput) {
        const names = [];
        supplies.forEach((row) => {
          const name = row.id.split(SEP)[0];
          if (!names.includes(name)) names.push(name);
        });
        supplyInput.value = names.join(",");
      }
    }

    function render() {
      renderRows(0);
      renderRows(1);
      sync();
    }

    function load() {
      const parsed = parseRows(textarea.value);
      if (parsed.error) return parsed.error;
      options = parsed.rows.filter((row) => row.type === 0);
      supplies = parsed.rows.filter((row) => row.type === 1);
      fillInputs();
      renderRows(0);
      renderRows(1);
      return "";
    }

    function setRawMode(on) {
      rawMode = on;
      rawToggle.checked = on;
      ui.hidden = on;
      rawPanel.hidden = !on;
    }

    rawToggle.addEventListener("change", () => {
      if (rawToggle.checked) {
        sync();
        setRawMode(true);
        say("JSON 을 직접 고칩니다. 끄면 도구가 JSON 을 다시 읽습니다.");
        return;
      }
      const error = load();
      if (error) {
        setRawMode(true);
        say(`${error} JSON 을 고친 뒤 다시 꺼 주세요.`, true);
        return;
      }
      setRawMode(false);
      sync();
      say("");
    });

    ui.append(
      el("section", { class: "g5-option-builder__section" }, [
        el("h3", { text: "선택옵션" }),
        el("p", { class: "g5-option-builder__note", text: "옵션명과 항목(쉼표 구분)을 넣고 옵션목록생성을 누르면 조합마다 한 행이 생깁니다. 이미 있던 행의 금액 · 재고는 그대로 둡니다." }),
        levelGrid,
        el("div", { class: "g5-option-builder__actions" }, [
          el("button", { type: "button", class: "g5-option-builder__btn", text: "옵션목록생성", onclick: generateOptions }),
        ]),
        optionTable.table,
        optionTable.bulk,
      ]),
      el("section", { class: "g5-option-builder__section" }, [
        el("h3", { text: "추가옵션" }),
        el("p", { class: "g5-option-builder__note", text: "항목명과 값(쉼표 구분)을 넣고 추가옵션목록생성을 누르세요. 추가옵션 금액은 상품 가격과 따로 계산됩니다." }),
        supplyLines,
        el("div", { class: "g5-option-builder__actions" }, [
          el("button", { type: "button", class: "g5-option-builder__btn g5-option-builder__btn--ghost", text: "항목 추가", onclick: () => addSupplyLine() }),
          el("button", { type: "button", class: "g5-option-builder__btn", text: "추가옵션목록생성", onclick: generateSupplies }),
        ]),
        supplyTable.table,
        supplyTable.bulk,
      ]),
    );

    const error = load();
    if (error) {
      setRawMode(true);
      say(`${error} JSON 을 직접 고쳐 주세요.`, true);
    } else {
      setRawMode(false);
    }

    form?.addEventListener("submit", () => { if (dirty) sync(); });
  }

  // form media loads in <head>: wait for the change form
  const start = () => document.querySelectorAll("[data-option-builder]").forEach(init);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
