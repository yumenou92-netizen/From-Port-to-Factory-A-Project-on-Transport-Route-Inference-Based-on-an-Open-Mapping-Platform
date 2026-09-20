const state = {
  result: null,
  activeRoute: "lowestCost",
  map: null,
  markers: null,
  routeLayers: [],
  pointById: new Map(),
  nodeInfoMap: new Map(),
  infoWindow: null,
  popupClickGuard: false,
  openPopup: null,
  tooltipNodeId: null,
};

const shippingColors = {
  lowestCost: "#e05530",
  fastestTime: "#2d6a4f",
};

const elements = {
  form: document.querySelector("#routeForm"),
  runButton: document.querySelector(".run-button"),
  serviceDot: document.querySelector("#serviceDot"),
  serviceStatus: document.querySelector("#serviceStatus"),
  mapFallback: document.querySelector("#mapFallback"),
  mapLoading: document.querySelector("#mapLoading"),
  emptyState: document.querySelector("#emptyState"),
  emptyStateTitle: document.querySelector("#emptyStateTitle"),
  emptyStateDesc: document.querySelector("#emptyStateDesc"),
  retryButton: document.querySelector("#retryButton"),
  routeResult: document.querySelector("#routeResult"),
  logToggle: document.querySelector("#logToggle"),
  logBody: document.querySelector("#logBody"),
  messageList: document.querySelector("#messageList"),
  edgeCount: document.querySelector("#edgeCount"),
  errorChecklist: document.querySelector("#errorChecklist"),
  packageType: document.querySelector("#packageType"),
  quantityUnit: document.querySelector("#quantityUnit"),
  containerTypeField: document.querySelector("#containerTypeField"),
  transportPreference: document.querySelector("#transportPreference"),
  formFields: [...document.querySelectorAll("#routeForm input, #routeForm select")],
  cards: [...document.querySelectorAll(".route-card")],
  routeCards: {
    lowestCost: {
      pathNames: document.querySelector("#pathNamesLowestCost"),
      totalCost: document.querySelector("#totalCostLowestCost"),
      totalTime: document.querySelector("#totalTimeLowestCost"),
      unitCost: document.querySelector("#unitCostLowestCost"),
      segmentList: document.querySelector("#segmentListLowestCost"),
    },
    fastestTime: {
      pathNames: document.querySelector("#pathNamesFastestTime"),
      totalCost: document.querySelector("#totalCostFastestTime"),
      totalTime: document.querySelector("#totalTimeFastestTime"),
      unitCost: document.querySelector("#unitCostFastestTime"),
      segmentList: document.querySelector("#segmentListFastestTime"),
    },
  },
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  bindInteractions();
  syncFieldIndicators();
  await Promise.all([checkHealth(), initializeTencentMap()]);
}

function bindInteractions() {
  elements.form.addEventListener("submit", runRoute);
  elements.form.addEventListener("input", syncFieldIndicators);
  elements.packageType.addEventListener("change", syncOrderCompatibility);
  elements.transportPreference.addEventListener("change", syncTransportPreference);
  syncTransportPreference();
  syncOrderCompatibility();

  const selectRoute = (routeId) => {
    state.activeRoute = routeId;
    elements.cards.forEach((card) => {
      card.classList.toggle("active", card.dataset.route === routeId);
    });
    renderMapRoutes();
  };

  elements.cards.forEach((card) => {
    card.addEventListener("click", () => selectRoute(card.dataset.route));
  });

  elements.logToggle.addEventListener("click", () => {
    const expanded = elements.logBody.hidden;
    elements.logBody.hidden = !expanded;
    elements.logToggle.textContent = expanded ? "收起明细" : "展开明细";
    elements.logToggle.setAttribute("aria-expanded", String(expanded));
  });

  elements.retryButton.addEventListener("click", () => {
    elements.form.requestSubmit();
  });
}

function syncOrderCompatibility() {
  const isContainer = elements.packageType.value === "集装箱";
  elements.quantityUnit.value = isContainer ? "箱" : "吨";
  elements.quantityUnit.disabled = true;
  elements.containerTypeField.hidden = !isContainer;
}

function syncTransportPreference() {
  const preference = elements.transportPreference.value;
  if (preference === "散粮") elements.packageType.value = "散粮";
  if (preference === "铁路") elements.packageType.value = "集装箱";
  elements.packageType.disabled = preference !== "混合";
  syncOrderCompatibility();
  syncFieldIndicators();
}

function syncFieldIndicators() {
  elements.formFields.forEach((field) => {
    const hasValue = field.value.trim().length > 0;
    field.closest("label")?.classList.toggle("has-value", hasValue);
  });
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) throw new Error("服务未就绪");
    elements.serviceDot.classList.add("ready");
    elements.serviceStatus.textContent = "本地模型已连接";
  } catch {
    elements.serviceDot.classList.add("error");
    elements.serviceStatus.textContent = "本地模型未连接";
  }
}

async function initializeTencentMap() {
  try {
    const response = await fetch("/api/config", { cache: "no-store" });
    const config = await response.json();
    if (!config.tencentMapJsKey) {
      showMapFallback("未配置腾讯地图浏览器 Key", "模型仍可运行，地图底座暂不加载。");
      return;
    }
    await loadTencentScript(config.tencentMapJsKey);
    const center = new TMap.LatLng(25.2, 112.8);
    state.map = new TMap.Map(document.querySelector("#map"), {
      center,
      zoom: 6.2,
      viewMode: "2D",
      baseMap: {
        type: "vector",
        features: ["base", "point", "label"],
      },
    });
    elements.mapFallback.classList.add("hidden");
    state.map.on("click", () => {
      if (state.popupClickGuard) return;
      closeNodePopup();
    });
    state.map.on("drag", updateNodePopupPosition);
    state.map.on("zoom_changed", updateNodePopupPosition);
    state.map.on("center_changed", updateNodePopupPosition);
    if (state.result) renderMapRoutes();
    if (config.mapKeyMode === "shared_local_key") {
      appendMessage(
        "地图使用本地共享 Key 加载；若控制台未开通 JavaScript API GL 或域名白名单，地图会降级。",
        "warning",
      );
    }
  } catch {
    showMapFallback(
      "腾讯地图底座加载失败",
      "请核对 Key 是否开通 JavaScript API GL，以及 localhost 是否在域名白名单内。",
    );
  }
}

function loadTencentScript(key) {
  return new Promise((resolve, reject) => {
    if (window.TMap) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.charset = "utf-8";
    script.src = `https://map.qq.com/api/gljs?v=1.exp&key=${encodeURIComponent(key)}`;
    script.onload = resolve;
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

async function runRoute(event) {
  event.preventDefault();
  setLoading(true);
  resetMessages();
  const formData = new FormData(elements.form);
  const payload = Object.fromEntries(formData.entries());
  // Disabled form controls are intentionally omitted by FormData.  The unit
  // selector is display-only because package type determines the legal unit,
  // so put the derived value back into the request explicitly.
  payload.quantityUnit = elements.packageType.value === "集装箱" ? "箱" : "吨";
  payload.packageType = elements.packageType.value;
  payload.transportPreference = elements.transportPreference.value;
  if (elements.packageType.value !== "集装箱") delete payload.containerType;
  try {
    const response = await fetch("/api/route", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "模型未返回可用路线。");
    }
    state.result = result;
    state.activeRoute = "lowestCost";
    elements.cards.forEach((card) => {
      card.classList.toggle("active", card.dataset.route === "lowestCost");
    });
    renderResult();
  } catch (error) {
    state.result = null;
    clearMapRoutes();
    elements.edgeCount.textContent = "本次未形成搜索图";
    elements.emptyState.hidden = false;
    elements.routeResult.hidden = true;
    elements.emptyStateTitle.textContent = "本次测算未完成";
    elements.emptyStateDesc.textContent = error.message;
    elements.errorChecklist.hidden = false;
    elements.retryButton.hidden = false;
    appendMessage(error.message, "error");
    expandLog();
  } finally {
    setLoading(false);
  }
}

function renderResult() {
  elements.emptyState.hidden = true;
  elements.routeResult.hidden = false;
  elements.retryButton.hidden = true;
  elements.errorChecklist.hidden = true;
  const info = state.result.runInfo;
  elements.edgeCount.textContent = `${info.graphEdgeCount} 条边进入搜索图`;
  if (state.result.planningFamily === "rail_container") {
    appendMessage(
      `当前订单按集装箱/箱筛选铁路方案；已准入铁路干线 ${info.trunkAdmissionCount || 0} 条。`,
      "info",
    );
  } else {
    appendMessage(
      `散船干线 ${info.bulkShippingEdgeCount} 条；汽运 ${info.truckEdgeCount} 条；驳船 ${info.bargeEdgeCount} 条。`,
      "info",
    );
  }
  if (info.routeGeometryMode === "mixed_by_segment") {
    appendMessage(
      "地图口径：散船与驳船由实际端点接入最近的已维护航线控制点；汽运使用与本次测算相同的腾讯驾车道路折线。",
      "info",
    );
  }
  if (info.routeGeometryMode === "rail_geometry_unavailable") {
    appendMessage("铁路费用和时效可按正式数据测算；真实铁路几何尚未接入，地图不绘制虚构线路。", "warning");
  }
  if (info.routeControlPointCount) {
    appendMessage(
      `航线示意已加载 ${info.routeControlPointSource}，共 ${info.routeControlPointCount} 个散船/驳船控制点。`,
      "info",
    );
  }
  if (info.preciseRoadGeometryCount < info.truckEdgeCount) {
    appendMessage(
      `本次 ${info.truckEdgeCount} 条汽运候选中有 ${info.truckEdgeCount - info.preciseRoadGeometryCount} 条未取得腾讯道路折线；这些边不以端点直线冒充真实道路。`,
      "warning",
    );
  }
  if (info.bargePlaceholderCapabilityCount) {
    appendMessage(
      `${info.bargePlaceholderCapabilityCount} 条驳船边仍使用 demo_placeholder 端点能力标签。`,
      "warning",
    );
  }
  (state.result.candidateDecisions || []).forEach((decision) => {
    const statusLabel = {
      included: "已入图",
      excluded: "已排除",
      not_selected: "未入选",
      shortlisted: "待构边",
    }[decision.status] || decision.status;
    appendMessage(
      `候选南港 ${decision.name}：${statusLabel}（${decision.stage}）— ${decision.reason}`,
      decision.status === "included" ? "ok" : "muted",
    );
  });
  info.warnings.forEach((warning) => appendMessage(warning, "warning"));
  renderRoutes();
  collapseLog();
}

function expandLog() {
  elements.logBody.hidden = false;
  elements.logToggle.textContent = "收起明细";
  elements.logToggle.setAttribute("aria-expanded", "true");
}

function collapseLog() {
  elements.logBody.hidden = true;
  elements.logToggle.textContent = "展开明细";
  elements.logToggle.setAttribute("aria-expanded", "false");
}

function renderRoutes() {
  if (!state.result) return;
  ["lowestCost", "fastestTime"].forEach((routeId) => {
    const route = state.result.routes[routeId];
    const card = elements.routeCards[routeId];
    card.pathNames.textContent = (route.pathNames || []).join(" → ") || route.message || "未形成完整路线";
    card.totalCost.textContent = route.totalCostYuan == null ? "—" : `${formatNumber(route.totalCostYuan)} 元`;
    card.totalTime.textContent = route.totalTimeHours == null ? "—" : formatDays(route.totalTimeHours);
    card.unitCost.textContent =
      route.unitCostYuan == null
        ? "—"
        : `${formatNumber(route.unitCostYuan)} ${unitCostLabel()}`;
    card.segmentList.replaceChildren(
      ...(route.segments || []).map((segment) => renderSegment(segment)),
    );
  });
  renderMapRoutes();
}

function renderSegment(segment) {
  const item = document.createElement("li");
  const index = document.createElement("span");
  index.className = "segment-index";
  index.textContent = segment.segmentNo;
  const copy = document.createElement("div");
  copy.className = "segment-copy";
  const title = document.createElement("strong");
  title.textContent = `${modeLabel(segment.transportMode)} · ${segment.fromName} → ${segment.toName}`;
  const meta = document.createElement("span");
  meta.className = "segment-meta";
  meta.textContent = `${formatCostWithUnit(segment.costYuan)} · ${formatDays(segment.timeHours)} · ${segment.ruleId}/${segment.ruleVersion}`;
  copy.append(title, meta);
  segment.costComponents.forEach((component) => {
    const line = document.createElement("span");
    line.className = "component-line";
    line.textContent = `${componentLabel(component.type)} ${formatCostWithUnit(component.amountYuan)} · ${sourceLabel(component.sourceType)}`;
    copy.append(line);
  });
  item.append(index, copy);
  return item;
}

function renderMapRoutes() {
  if (!state.map || !state.result) return;
  clearMapRoutes();

  const routeEntries = [
    ["lowestCost", state.result.routes.lowestCost, "#e05530"],
    ["fastestTime", state.result.routes.fastestTime, "#2d6a4f"],
  ];
  routeEntries.sort(([leftId], [rightId]) => {
    if (leftId === state.activeRoute) return 1;
    if (rightId === state.activeRoute) return -1;
    return 0;
  });
  const uniquePoints = new Map();
  routeEntries.forEach(([, route]) => {
    (route.points || []).forEach((point) => uniquePoints.set(point.nodeId, point));
  });
  state.pointById = uniquePoints;
  state.nodeInfoMap = buildNodeInfoMap(state.result);

  state.markers = new TMap.MultiMarker({
    map: state.map,
    styles: {
      node: new TMap.MarkerStyle({
        width: 22,
        height: 28,
        anchor: { x: 11, y: 28 },
        cursor: "pointer",
      }),
    },
    geometries: [...uniquePoints.values()].map((point) => ({
      id: point.nodeId,
      styleId: "node",
      position: new TMap.LatLng(point.latitude, point.longitude),
      properties: { title: point.name },
    })),
  });

  state.markers.on("click", (event) => {
    state.popupClickGuard = true;
    setTimeout(() => {
      state.popupClickGuard = false;
    }, 0);
    const geometry = event.geometry;
    const info = state.nodeInfoMap.get(geometry.id);
    if (info) showNodePopup(info, geometry.position);
  });

  state.markers.on("mousemove", (event) => {
    const geometry = event.geometry;
    if (!geometry) return;
    showNodeTooltip(geometry);
  });

  state.markers.on("mouseout", closeNodeTooltip);

  const boundsPoints = [...uniquePoints.values()];
  routeEntries.forEach(([id, route, color]) => {
    (route.segments || []).forEach((segment) => {
      const geometry = segment.geometry;
      if (!geometry || !Array.isArray(geometry.points) || geometry.points.length < 2) return;
      const isActive = state.activeRoute === id;
      const isSchematic = geometry.isSchematic;
      const isShipping = segment.transportStage === "north_to_south";
      const segmentColor = isShipping ? shippingColors[id] : color;
      const styleId = `${id}-${segment.segmentNo}-${geometry.kind}`;
      const paths = geometry.points.map(
        (point) => new TMap.LatLng(point.latitude, point.longitude),
      );
      boundsPoints.push(...geometry.points);
      const styleOptions = {
        color: segmentColor,
        width: isActive ? (isSchematic ? 6 : 7) : isSchematic ? 3 : 3.5,
        borderWidth: isActive ? 1 : 0,
        borderColor: "rgba(255,255,255,.92)",
        lineCap: "round",
      };
      if (geometry.kind === "bulk_shipping_schematic") {
        styleOptions.dashArray = [14, 10];
      } else if (geometry.kind === "barge_schematic") {
        styleOptions.dashArray = [7, 7];
      }
      const layer = new TMap.MultiPolyline({
        map: state.map,
        enableGeodesic: isSchematic,
        styles: {
          [styleId]: new TMap.PolylineStyle(styleOptions),
        },
        geometries: [
          {
            id: styleId,
            styleId,
            paths,
            properties: {
              routeObjective: id,
              transportMode: segment.transportMode,
              geometrySource: geometry.source,
            },
          },
        ],
      });
      state.routeLayers.push(layer);
    });
  });

  if (boundsPoints.length) {
    const latitudes = boundsPoints.map((point) => point.latitude);
    const longitudes = boundsPoints.map((point) => point.longitude);
    const southwest = new TMap.LatLng(
      Math.min(...latitudes),
      Math.min(...longitudes),
    );
    const northeast = new TMap.LatLng(
      Math.max(...latitudes),
      Math.max(...longitudes),
    );
    state.map.fitBounds(new TMap.LatLngBounds(southwest, northeast), {
      padding: 90,
    });
  }
}

function clearMapRoutes() {
  if (state.markers) {
    state.markers.setMap(null);
    state.markers = null;
  }
  state.routeLayers.forEach((layer) => layer.setMap(null));
  state.routeLayers = [];
  closeNodePopup();
  closeNodeTooltip();
}

function buildNodeInfoMap(result) {
  const infoMap = new Map();
  if (!result) return infoMap;

  const reference = result.routes?.lowestCost || result.routes?.fastestTime;
  const pathPoints = reference?.points || [];

  // 候选南港：直线距离 + 末段方式
  (result.candidates || []).forEach((candidate) => {
    infoMap.set(candidate.nodeId, {
      name: candidate.name,
      role: "southPort",
      straightLineKmToFactory: candidate.straightLineKmToFactory,
      lastMileModes: candidate.lastMileModes,
    });
  });

  // 候选决策：入选状态 + 原因
  (result.candidateDecisions || []).forEach((decision) => {
    const info = infoMap.get(decision.nodeId);
    if (info) info.decision = decision;
  });

  // 中转港（路径经过的非南港节点）
  (result.intermediatePorts || []).forEach((port) => {
    if (!infoMap.has(port.nodeId)) {
      infoMap.set(port.nodeId, { name: port.name, role: "transferPort" });
    }
  });

  // 路径起点 = 出发北港
  if (pathPoints.length) {
    const origin = pathPoints[0];
    infoMap.set(origin.nodeId, {
      name: origin.name,
      role: "origin",
    });
  }

  // 路径终点 = 客户工厂（优先标记，覆盖候选/中转的角色）
  if (pathPoints.length > 1) {
    const destination = pathPoints[pathPoints.length - 1];
    infoMap.set(destination.nodeId, {
      name: destination.name,
      role: "customer",
      destinationRequested: result.request?.destination,
    });
  }

  // 兜底：路径上任何未识别的节点
  pathPoints.forEach((point) => {
    if (!infoMap.has(point.nodeId)) {
      infoMap.set(point.nodeId, { name: point.name, role: "transit" });
    }
  });

  return infoMap;
}

function showNodePopup(info, position) {
  closeNodePopup();
  closeNodeTooltip();
  const popup = document.createElement("div");
  popup.className = "node-popup";

  const roleMeta = {
    origin: { label: "出发北港", cls: "role-origin" },
    customer: { label: "客户工厂", cls: "role-customer" },
    southPort: { label: "候选南港", cls: "role-port" },
    transferPort: { label: "中转港", cls: "role-transfer" },
    transit: { label: "运输节点", cls: "role-transit" },
  };
  const meta = roleMeta[info.role] || roleMeta.transit;

  const role = document.createElement("span");
  role.className = `node-popup-role ${meta.cls}`;
  role.textContent = meta.label;

  const name = document.createElement("strong");
  name.className = "node-popup-name";
  name.textContent = info.name;

  const close = document.createElement("button");
  close.className = "node-popup-close";
  close.type = "button";
  close.setAttribute("aria-label", "关闭");
  close.textContent = "×";
  close.addEventListener("click", closeNodePopup);

  popup.append(role, close, name);

  const rows = [];

  if (info.role === "customer") {
    rows.push(["角色", "路径终点"]);
  }
  if (info.role === "origin") {
    rows.push(["角色", "路径起点"]);
  }
  if (info.role === "southPort") {
    rows.push([
      "距工厂直线",
      info.straightLineKmToFactory
        ? `${formatNumber(info.straightLineKmToFactory)} km`
        : "—",
    ]);
    rows.push([
      "末段方式",
      (info.lastMileModes || []).join(" / ") || "—",
    ]);
    if (info.decision) {
      const statusLabel = {
        included: "已入图",
        excluded: "已排除",
        not_selected: "未入选",
        shortlisted: "待构边",
      }[info.decision.status] || info.decision.status;
      rows.push(["决策", statusLabel]);
      if (info.decision.reason) {
        rows.push(["原因", info.decision.reason]);
      }
    }
  }
  if (info.role === "transferPort") {
    rows.push(["角色", "路径中转"]);
  }
  rows.push([
    "坐标",
    `${Number(position.lat).toFixed(4)}, ${Number(position.lng).toFixed(4)}`,
  ]);

  const list = document.createElement("dl");
  list.className = "node-popup-meta";
  rows.forEach(([label, value]) => {
    const item = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    item.append(dt, dd);
    list.append(item);
  });
  popup.append(list);

  state.openPopup = { info, position };
  document.querySelector(".map-stage").appendChild(popup);
  positionNodePopup(popup, position);
}

function positionNodePopup(popup, position) {
  const pixel = state.map.projectToContainer(position);
  const stageRect = document.querySelector(".map-stage").getBoundingClientRect();
  const popupRect = popup.getBoundingClientRect();
  let left = pixel.getX() + 16;
  let top = pixel.getY() - popupRect.height - 14;
  left = Math.max(10, Math.min(left, stageRect.width - popupRect.width - 10));
  top = Math.max(10, top);
  popup.style.left = `${left}px`;
  popup.style.top = `${top}px`;
}

function updateNodePopupPosition() {
  if (!state.openPopup) return;
  const popup = document.querySelector(".node-popup");
  if (!popup) return;
  positionNodePopup(popup, state.openPopup.position);
}

function closeNodePopup() {
  state.openPopup = null;
  document.querySelectorAll(".node-popup").forEach((popup) => popup.remove());
}

const roleLabel = (role) =>
  ({
    origin: "出发北港",
    customer: "客户工厂",
    southPort: "候选南港",
    transferPort: "中转港",
    transit: "运输节点",
  })[role] || "运输节点";

function showNodeTooltip(geometry) {
  if (state.tooltipNodeId === geometry.id) return;
  const info = state.nodeInfoMap.get(geometry.id);
  if (!info) return;
  closeNodeTooltip();
  state.tooltipNodeId = geometry.id;

  const tooltip = document.createElement("div");
  tooltip.className = "node-tooltip";
  const name = document.createElement("strong");
  name.textContent = info.name;
  const role = document.createElement("span");
  role.className = `tt-${info.role}`;
  role.textContent = roleLabel(info.role);
  tooltip.append(name, role);

  document.querySelector(".map-stage").appendChild(tooltip);
  const pixel = state.map.projectToContainer(geometry.position);
  const stageRect = document.querySelector(".map-stage").getBoundingClientRect();
  const tipRect = tooltip.getBoundingClientRect();
  let left = pixel.getX() - tipRect.width / 2;
  let top = pixel.getY() - tipRect.height - 12;
  left = Math.max(6, Math.min(left, stageRect.width - tipRect.width - 6));
  top = Math.max(6, top);
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function closeNodeTooltip() {
  state.tooltipNodeId = null;
  document.querySelectorAll(".node-tooltip").forEach((tooltip) => tooltip.remove());
}

function showMapFallback(title, detail) {
  elements.mapFallback.querySelector("strong").textContent = title;
  elements.mapFallback.querySelector("span").textContent = detail;
  elements.mapFallback.classList.remove("hidden");
}

function setLoading(loading) {
  elements.runButton.disabled = loading;
  elements.runButton.querySelector("span").textContent = loading
    ? "正在调用模型与地图"
    : "运行双目标测算";
  elements.mapLoading.hidden = !loading;
}

function resetMessages() {
  elements.messageList.replaceChildren();
}

function appendMessage(message, type = "info") {
  const item = document.createElement("li");
  item.className = type;
  item.textContent = message;
  elements.messageList.append(item);
}

function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number)
    ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(number)
    : value;
}

function formatDays(hours) {
  const value = Number(hours);
  if (!Number.isFinite(value)) return "—";
  return `${formatNumber(value / 24)} 天`;
}

function unitCostLabel() {
  const quantityUnit = state.result?.request?.quantityUnit;
  return quantityUnit === "吨" ? "元/吨" : `元/${quantityUnit || "单位"}`;
}

function formatCostWithUnit(costYuan) {
  const quantity = Number(state.result?.request?.quantity);
  const cost = Number(costYuan);
  const totalCost = Number.isFinite(cost) ? `${formatNumber(cost)} 元` : costYuan;
  if (!Number.isFinite(quantity) || quantity <= 0 || !Number.isFinite(cost)) {
    return totalCost;
  }
  return `${totalCost}（${formatNumber(cost / quantity)} ${unitCostLabel()}）`;
}

function modeLabel(mode) {
  return mode === "散船" ? "散船干线" : mode;
}

function componentLabel(type) {
  return {
    bulk_shipping_freight: "散船运费",
    south_port_operation_fee: "码头作业费",
    barge_freight: "驳船运费",
  }[type] || type;
}

function sourceLabel(type) {
  return {
    real_data: "真实业务数据",
    regional_proxy: "同区域最近码头代理",
    demo_placeholder: "演示占位",
    confirmed_rule: "已确认规则",
  }[type] || type;
}
