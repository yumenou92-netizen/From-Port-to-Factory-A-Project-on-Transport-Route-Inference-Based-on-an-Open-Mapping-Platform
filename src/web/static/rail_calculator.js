const form = document.querySelector("#calculatorForm");
const resetButton = document.querySelector("#resetButton");
const serviceDot = document.querySelector("#serviceDot");
const serviceStatus = document.querySelector("#serviceStatus");
const calculationStatus = document.querySelector("#calculationStatus");
const calculatorEmpty = document.querySelector("#calculatorEmpty");
const calculatorResult = document.querySelector("#calculatorResult");
const calculatorError = document.querySelector("#calculatorError");
const lineItems = document.querySelector("#calculatorLineItems");
const warnings = document.querySelector("#calculatorWarnings");
const ledgerBody = document.querySelector("#ledgerBody");
const ledgerEmpty = document.querySelector("#ledgerEmpty");
const exportXlsxButton = document.querySelector("#exportXlsxButton");
const exportCsvButton = document.querySelector("#exportCsvButton");
const localFreightRows = document.querySelector("#localFreightRows");
const addLocalFreightButton = document.querySelector("#addLocalFreightButton");

// 台账输入字段（key 与表单 name / 台账列一致）
const LEDGER_INPUT_FIELDS = [
  "northStation",
  "southStation",
  "customerFactory",
  "loadTons",
  "discountRatio",
  "totalFreightYuan",
  "electrifiedKm",
  "stampTaxYuan",
  "jingjiuDiversionYuan",
  "railConstructionFundAdjustedBaseYuan",
  "originHandlingAdjustedYuan",
  "destinationHandlingAdjustedYuan",
  "pickupDeliveryAdjustedYuan",
  "otherAdjustedYuan",
];

// 当前编辑中的台账序号；null = 追加模式
let editingSeq = null;

document.addEventListener("DOMContentLoaded", async () => {
  form.addEventListener("submit", calculate);
  resetButton.addEventListener("click", () => {
    cancelEditing();
    resetLocalFreightRows();
    window.setTimeout(clearResult, 0);
  });
  addLocalFreightButton.addEventListener("click", () => addLocalFreightRow("0"));
  resetLocalFreightRows();
  exportXlsxButton.addEventListener("click", () => downloadLedger("xlsx"));
  exportCsvButton.addEventListener("click", () => downloadLedger("csv"));
  await checkHealth();
  await loadLedger();
});

async function checkHealth() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) throw new Error("服务未就绪");
    serviceDot.classList.add("ready");
    serviceStatus.textContent = "本地计算器已连接";
  } catch {
    serviceDot.classList.add("error");
    serviceStatus.textContent = "本地模型未连接";
  }
}

async function calculate(event) {
  event.preventDefault();
  clearError();
  if (!validateStations()) return;
  setCalculating(true);
  try {
    const payload = Object.fromEntries(new FormData(form).entries());
    payload.localFreightBases = collectLocalFreightBases();
    const response = await fetch("/api/rail-freight-calculator", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "计算器未返回结果。");
    renderResult(result);
    await saveToLedger(payload, result);
  } catch (error) {
    calculatorResult.hidden = true;
    calculatorEmpty.hidden = true;
    calculatorError.hidden = false;
    calculatorError.textContent = error.message;
    calculationStatus.textContent = "需修正输入";
  } finally {
    setCalculating(false);
  }
}

function validateStations() {
  const north = form.elements.northStation.value.trim();
  const south = form.elements.southStation.value.trim();
  if (!north || !south) {
    calculatorResult.hidden = true;
    calculatorEmpty.hidden = true;
    calculatorError.hidden = false;
    calculatorError.textContent = "北方站点和南方站点为必填项，请先填写。";
    calculationStatus.textContent = "需修正输入";
    form.elements.northStation.focus();
    return false;
  }
  return true;
}

async function saveToLedger(payload, result) {
  const record = {
    northStation: (payload.northStation || "").trim(),
    southStation: (payload.southStation || "").trim(),
    customerFactory: (payload.customerFactory || "").trim(),
    loadTons: payload.loadTons,
    discountRatio: payload.discountRatio,
    totalFreightYuan: payload.totalFreightYuan,
    electrifiedKm: payload.electrifiedKm,
    stampTaxYuan: payload.stampTaxYuan || "0",
    jingjiuDiversionYuan: payload.jingjiuDiversionYuan || "0",
    railConstructionFundAdjustedBaseYuan: payload.railConstructionFundAdjustedBaseYuan || "0",
    originHandlingAdjustedYuan: payload.originHandlingAdjustedYuan || "0",
    destinationHandlingAdjustedYuan: payload.destinationHandlingAdjustedYuan || "0",
    pickupDeliveryAdjustedYuan: payload.pickupDeliveryAdjustedYuan || "0",
    otherAdjustedYuan: payload.otherAdjustedYuan || "0",
    fullPriceTotalYuan: result.totals.fullPriceTotalYuan,
    userFullPriceTotalYuan: result.totals.userFullPriceTotalYuan,
    localFreightAdjustedTotalYuan: result.totals.localFreightAdjustedTotalYuan,
    adjustedTotalYuan: result.totals.adjustedTotalYuan,
    inputLoadUnitPriceYuanPerTon: result.totals.inputLoadUnitPriceYuanPerTon,
    workbookUnitPriceYuanPerTon: result.totals.originalWorkbookUnitPriceYuanPerTon,
  };
  if (editingSeq !== null) {
    record.seq = editingSeq;
    await postJson("/api/rail-ledger/update", record);
    cancelEditing();
  } else {
    await postJson("/api/rail-ledger", record);
  }
  await loadLedger();
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let message = "保存台账失败。";
    try {
      const body = await response.json();
      if (body.error) message = body.error;
    } catch { /* ignore */ }
    throw new Error(message);
  }
}

async function loadLedger() {
  let records = [];
  try {
    const response = await fetch("/api/rail-ledger", { cache: "no-store" });
    const body = await response.json();
    records = body.records || [];
  } catch (error) {
    console.error("加载台账失败", error);
  }
  renderLedger(records);
}

function resetLocalFreightRows() {
  localFreightRows.replaceChildren();
  addLocalFreightRow("0");
  addLocalFreightRow("0");
}

function addLocalFreightRow(value = "0") {
  const row = document.createElement("div");
  row.className = "local-freight-row";
  const label = document.createElement("label");
  const span = document.createElement("span");
  span.className = "local-freight-name";
  span.append(document.createTextNode("地方运费折算基数 "));
  const em = document.createElement("em");
  em.textContent = "按下浮率折算";
  span.append(em);
  const input = document.createElement("input");
  input.type = "number";
  input.min = "0";
  input.step = "0.01";
  input.value = value;
  label.append(span, input);
  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "mini-button remove-local-freight";
  removeButton.textContent = "删除";
  removeButton.setAttribute("aria-label", "删除此行地方运费");
  removeButton.addEventListener("click", () => removeLocalFreightRow(row));
  row.append(label, removeButton);
  localFreightRows.append(row);
  reindexLocalFreightRows();
}

function removeLocalFreightRow(row) {
  const count = localFreightRows.querySelectorAll(".local-freight-row").length;
  if (count <= 1) {
    window.alert("至少保留一项地方运费。");
    return;
  }
  row.remove();
  reindexLocalFreightRows();
}

function reindexLocalFreightRows() {
  localFreightRows.querySelectorAll(".local-freight-row").forEach((row, index) => {
    const span = row.querySelector(".local-freight-name");
    if (span && span.firstChild) span.firstChild.textContent = `地方运费${index + 1}折算基数 `;
  });
}

function collectLocalFreightBases() {
  return [...localFreightRows.querySelectorAll("input[type=number]")]
    .map((input) => input.value.trim())
    .filter((text) => text !== "");
}

function renderLedger(records) {
  ledgerBody.replaceChildren();
  ledgerEmpty.hidden = records.length > 0;
  if (records.length === 0) return;
  records.forEach((record) => {
    const row = document.createElement("tr");
    if (Number(record.seq) === editingSeq) row.className = "editing";
    const cells = [
      String(record.seq ?? ""),
      formatText(record.savedAt),
      formatText(record.northStation),
      formatText(record.southStation),
      formatText(record.customerFactory),
      formatNumber(record.loadTons),
      formatPercent(record.discountRatio),
      formatYuan(record.totalFreightYuan),
      formatYuan(record.fullPriceTotalYuan),
      formatYuan(record.userFullPriceTotalYuan),
      formatYuan(record.localFreightAdjustedTotalYuan),
      formatYuan(record.adjustedTotalYuan),
      formatNumber(record.inputLoadUnitPriceYuanPerTon) + " 元/吨",
    ];
    cells.forEach((value, index) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      if (index >= 5) cell.className = "numeric";
      row.append(cell);
    });
    const actionCell = document.createElement("td");
    const actions = document.createElement("div");
    actions.className = "ledger-actions-row";
    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.textContent = Number(record.seq) === editingSeq ? "取消编辑" : "编辑";
    editButton.addEventListener("click", () => {
      if (editingSeq === Number(record.seq)) cancelEditing();
      else startEditing(record);
    });
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "danger";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => deleteLedgerRecord(Number(record.seq)));
    actions.append(editButton, deleteButton);
    actionCell.append(actions);
    row.append(actionCell);
    ledgerBody.append(row);
  });
}

function startEditing(record) {
  editingSeq = Number(record.seq);
  LEDGER_INPUT_FIELDS.forEach((key) => {
    const input = form.elements[key];
    if (input) input.value = record[key] ?? "";
  });
  form.querySelector(".run-button span").textContent = "保存修改";
  calculationStatus.textContent = `正在编辑台账第 ${editingSeq} 条`;
  window.scrollTo({ top: 0, behavior: "smooth" });
  renderLedgerFromCache(record.seq);
}

function cancelEditing() {
  if (editingSeq === null) return;
  editingSeq = null;
  form.querySelector(".run-button span").textContent = "计算铁路报价";
  if (calculationStatus.textContent.startsWith("正在编辑台账")) {
    calculationStatus.textContent = "已完成试算";
  }
  refreshLedgerHighlight();
}

function refreshLedgerHighlight() {
  [...ledgerBody.querySelectorAll("tr")].forEach((row) => {
    const seqCell = row.querySelector("td");
    if (!seqCell) return;
    const seq = Number(seqCell.textContent);
    const isEditing = editingSeq !== null && seq === editingSeq;
    row.classList.toggle("editing", isEditing);
    const editButton = row.querySelector(".ledger-actions-row button");
    if (editButton) editButton.textContent = isEditing ? "取消编辑" : "编辑";
  });
}

function renderLedgerFromCache(seq) {
  // 轻量刷新高亮，避免整表重查
  refreshLedgerHighlight();
}

async function deleteLedgerRecord(seq) {
  if (!window.confirm(`确认删除台账第 ${seq} 条记录？此操作不可撤销。`)) return;
  try {
    await postJson("/api/rail-ledger/delete", { seq });
    if (editingSeq === seq) cancelEditing();
    await loadLedger();
  } catch (error) {
    window.alert(error.message);
  }
}

function downloadLedger(format) {
  const anchor = document.createElement("a");
  anchor.href = `/api/rail-ledger/export?format=${format}`;
  anchor.download = "";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}

function renderResult(result) {
  calculatorEmpty.hidden = true;
  calculatorError.hidden = true;
  calculatorResult.hidden = false;
  calculationStatus.textContent = "已完成试算";
  document.querySelector("#fullPriceTotal").textContent = formatYuan(result.totals.fullPriceTotalYuan);
  document.querySelector("#userFullPriceTotal").textContent = formatYuan(result.totals.userFullPriceTotalYuan);
  document.querySelector("#adjustedTotal").textContent = formatYuan(result.totals.adjustedTotalYuan);
  document.querySelector("#inputLoadUnitPrice").textContent = `${formatNumber(result.totals.inputLoadUnitPriceYuanPerTon)} 元/吨`;
  document.querySelector("#workbookUnitPrice").textContent = `${formatNumber(result.totals.originalWorkbookUnitPriceYuanPerTon)} 元/吨`;
  lineItems.replaceChildren(...result.lines.map(makeLine));
  warnings.replaceChildren(...result.warnings.map((warning) => {
    const item = document.createElement("li");
    item.textContent = warning;
    return item;
  }));
}

function makeLine(line) {
  const row = document.createElement("tr");
  const values = [
    line.name,
    formatYuanOrDash(line.fullPriceYuan),
    formatYuanOrDash(line.dividedBy0991Yuan),
    formatYuanOrDash(line.dividedBy09911Yuan),
    formatYuanOrDash(line.adjustedYuan),
    line.note || "—",
  ];
  values.forEach((value, index) => {
    const cell = document.createElement("td");
    cell.textContent = value;
    if (index > 0 && index < 5) cell.className = "numeric";
    row.append(cell);
  });
  return row;
}

function clearResult() {
  calculatorResult.hidden = true;
  calculatorError.hidden = true;
  calculatorEmpty.hidden = false;
  calculationStatus.textContent = "待计算";
}

function clearError() { calculatorError.hidden = true; }

function setCalculating(active) {
  const button = form.querySelector(".run-button");
  button.disabled = active;
  button.querySelector("span").textContent = active ? "正在计算…" : (editingSeq !== null ? "保存修改" : "计算铁路报价");
  calculationStatus.textContent = active ? "计算中" : calculationStatus.textContent;
}

function formatNumber(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(numeric) : formatText(value);
}

function formatPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return formatText(value);
  return `${(numeric * 100).toFixed(2)}%`;
}

function formatYuan(value) { return `${formatNumber(value)} 元`; }
function formatYuanOrDash(value) { return value === null || value === undefined ? "—" : formatYuan(value); }
function formatText(value) { return value === null || value === undefined || value === "" ? "—" : String(value); }
