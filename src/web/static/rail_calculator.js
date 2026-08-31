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

document.addEventListener("DOMContentLoaded", async () => {
  form.addEventListener("submit", calculate);
  resetButton.addEventListener("click", () => window.setTimeout(clearResult, 0));
  await checkHealth();
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
  setCalculating(true);
  try {
    const payload = Object.fromEntries(new FormData(form).entries());
    const response = await fetch("/api/rail-freight-calculator", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "计算器未返回结果。");
    renderResult(result);
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

function renderResult(result) {
  calculatorEmpty.hidden = true;
  calculatorError.hidden = true;
  calculatorResult.hidden = false;
  calculationStatus.textContent = "已完成试算";
  document.querySelector("#fullPriceTotal").textContent = formatYuan(result.totals.fullPriceTotalYuan);
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
  button.querySelector("span").textContent = active ? "正在计算…" : "计算铁路报价";
  calculationStatus.textContent = active ? "计算中" : calculationStatus.textContent;
}

function formatNumber(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(numeric) : value;
}

function formatYuan(value) { return `${formatNumber(value)} 元`; }
function formatYuanOrDash(value) { return value === null || value === undefined ? "—" : formatYuan(value); }
