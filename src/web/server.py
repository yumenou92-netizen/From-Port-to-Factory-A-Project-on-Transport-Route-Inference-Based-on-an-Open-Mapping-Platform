from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PACKAGE_DIR = PROJECT_ROOT / ".python_packages"
if LOCAL_PACKAGE_DIR.exists() and str(LOCAL_PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_PACKAGE_DIR))

from src.application.route_planning import (
    EdgeGeometryTrace,
    RoutePlanningRequest,
    RoutePlanningResponse,
    RoutePlanningService,
)
from src.data.loaders import DataLoadError, data_dir_from_env, load_real_data_bundle
from src.demos.leader_full_flow import (
    FullFlowDemoError,
    plan_full_flow,
)
from src.dev.runtime_env import RuntimeEnvError, load_runtime_env
from src.domain.route_request import RouteRequest, RouteRequestError
from src.domain.rail_freight_calculator import (
    RailFreightCalculatorError,
    RailFreightCalculatorInput,
    calculate_rail_freight_workbook,
)
from src.geo.coordinate_provider import LocalFirstCoordinateProvider
from src.geo.tencent_map_provider import (
    TencentMapCoordinateProvider,
    TencentMapDrivingRouteProvider,
    TencentMapProviderError,
)
from src.geo.distance_provider import GeoPoint
from src.web.route_geometry import (
    SchematicRouteGeometry,
    build_barge_schematic,
    build_bulk_shipping_schematic,
)
from src.web.route_control_points import (
    RouteControlPointNetwork,
    find_route_control_point_file,
    load_route_control_point_network,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_REQUEST_BYTES = 64 * 1024


@dataclass
class RouteWebContext:
    bundle: Any
    route_control_points: RouteControlPointNetwork | None = None

    @classmethod
    def load(cls) -> "RouteWebContext":
        load_runtime_env()
        bundle = load_real_data_bundle(data_dir_from_env())
        route_control_points = None
        control_point_file = find_route_control_point_file(bundle.data_dir)
        if control_point_file is not None:
            route_control_points = load_route_control_point_network(
                control_point_file
            )
        return cls(
            bundle=bundle,
            route_control_points=route_control_points,
        )

    def calculate(self, payload: dict[str, Any]) -> dict[str, Any]:
        web_request = parse_route_web_request(payload)
        registry = self.bundle.node_registry
        service = RoutePlanningService(
            lambda request: plan_full_flow(
                request,
                bundle=self.bundle,
                coordinate_provider_factory=lambda region: (
                    LocalFirstCoordinateProvider(
                        registry,
                        fallback_provider=TencentMapCoordinateProvider.from_env(
                            region=region
                        ),
                    )
                ),
                road_route_provider=TencentMapDrivingRouteProvider.from_env(),
            )
        )
        result = service.plan(web_request)
        return serialize_full_flow_result(
            result,
            route_control_points=self.route_control_points,
        )


class RouteWebHandler(BaseHTTPRequestHandler):
    server_version = "PortRouteDemo/0.1"

    @property
    def context(self) -> RouteWebContext:
        return self.server.context  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(
                {
                    "status": "ok",
                    "service": "port-route-leader-demo",
                }
            )
            return
        if path == "/api/config":
            map_key = os.environ.get("TENCENT_MAP_JS_KEY") or os.environ.get(
                "TENCENT_MAP_API_KEY",
                "",
            )
            self._send_json(
                {
                    "tencentMapJsKey": map_key,
                    "mapKeyMode": (
                        "dedicated_js_key"
                        if os.environ.get("TENCENT_MAP_JS_KEY")
                        else "shared_local_key"
                        if map_key
                        else "missing"
                    ),
                    "routeGeometryMode": "mixed_by_segment",
                },
                no_store=True,
            )
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/api/route", "/api/rail-freight-calculator"}:
            self._send_json(
                {"error": "接口不存在。"},
                status=HTTPStatus.NOT_FOUND,
            )
            return
        content_length = _safe_int(self.headers.get("Content-Length"))
        if content_length is None or content_length < 0:
            self._send_json(
                {"error": "缺少有效的 Content-Length。"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        if content_length > MAX_REQUEST_BYTES:
            self._send_json(
                {"error": "请求体过大。"},
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON 对象。")
            if path == "/api/route":
                result = self.context.calculate(payload)
            else:
                result = serialize_rail_freight_calculator_result(
                    parse_rail_freight_calculator_request(payload)
                )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            RouteRequestError,
            RailFreightCalculatorError,
            FullFlowDemoError,
            TencentMapProviderError,
            DataLoadError,
        ) as exc:
            self._send_json(
                {
                    "error": str(exc),
                    "status": "manual_review",
                },
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
            return
        except Exception:
            self._send_json(
                {
                    "error": "运行失败；服务端已阻止输出未脱敏的异常信息。",
                    "status": "error",
                },
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        self._send_json(result, no_store=True)

    def log_message(self, format: str, *args: object) -> None:
        # Keep the local console useful without ever logging request bodies or keys.
        message = format % args
        print(f"[route-web] {self.address_string()} {message}")

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        candidate = (STATIC_DIR / relative).resolve()
        static_root = STATIC_DIR.resolve()
        if static_root not in candidate.parents and candidate != static_root:
            self._send_json(
                {"error": "非法静态资源路径。"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        if not candidate.is_file():
            self._send_json(
                {"error": "页面不存在。"},
                status=HTTPStatus.NOT_FOUND,
            )
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(
        self,
        payload: dict[str, Any],
        *,
        status: HTTPStatus = HTTPStatus.OK,
        no_store: bool = False,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if no_store else "no-cache")
        self.end_headers()
        self.wfile.write(body)


class RouteWebServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        context: RouteWebContext,
    ) -> None:
        super().__init__(server_address, RouteWebHandler)
        self.context = context


def parse_route_web_request(payload: dict[str, Any]) -> RoutePlanningRequest:
    transport_mode = _optional_text(payload.get("transportMode"))
    if transport_mode and transport_mode != "散船":
        raise ValueError("当前展示页仅开放北港至南港散船运输；铁路和船铁联运仍为后续接口。")
    origin = _required_text(payload.get("origin"), "出发北港")
    destination = _required_text(payload.get("destination"), "客户工厂")
    south_port = _optional_text(payload.get("southPort"))
    region = _optional_text(payload.get("region")) or "全国"
    request = RouteRequest(
        quantity=_required_text(payload.get("quantity"), "重量"),
        quantity_unit=_required_text(payload.get("quantityUnit"), "计费单位"),
        package_type=_required_text(payload.get("packageType"), "打包方式"),
        commodity=_required_text(payload.get("commodity"), "粮食品种"),
        trade_type=_optional_text(payload.get("tradeType")) or "内贸",
    )
    return RoutePlanningRequest(
        origin=origin,
        destination=destination,
        south_port=south_port,
        region=region,
        request=request,
    )


def parse_rail_freight_calculator_request(
    payload: dict[str, Any],
) -> RailFreightCalculatorInput:
    """Parse calculator inputs without allowing implicit defaults from routing."""

    return RailFreightCalculatorInput(
        load_tons=_required_decimal(payload.get("loadTons"), "整车装载吨数"),
        total_freight_yuan=_required_decimal(payload.get("totalFreightYuan"), "运费"),
        discount_ratio=_required_decimal(payload.get("discountRatio"), "下浮率"),
        electrified_km=_required_decimal(payload.get("electrifiedKm"), "电气化里程"),
        stamp_tax_yuan=_optional_decimal(payload.get("stampTaxYuan"), Decimal("0.5"), "印花税"),
        jingjiu_diversion_yuan=_optional_decimal(payload.get("jingjiuDiversionYuan"), Decimal("0"), "京九分流"),
        rail_construction_fund_adjusted_base_yuan=_optional_decimal(payload.get("railConstructionFundAdjustedBaseYuan"), Decimal("0"), "铁建基金折算基数"),
        local_freight_1_adjusted_base_yuan=_optional_decimal(payload.get("localFreight1AdjustedBaseYuan"), Decimal("0"), "地方运费1折算基数"),
        local_freight_2_adjusted_base_yuan=_optional_decimal(payload.get("localFreight2AdjustedBaseYuan"), Decimal("0"), "地方运费2折算基数"),
        origin_handling_adjusted_yuan=_optional_decimal(payload.get("originHandlingAdjustedYuan"), Decimal("0"), "发站装卸费"),
        destination_handling_adjusted_yuan=_optional_decimal(payload.get("destinationHandlingAdjustedYuan"), Decimal("0"), "到站装卸费"),
        pickup_delivery_adjusted_yuan=_optional_decimal(payload.get("pickupDeliveryAdjustedYuan"), Decimal("0"), "取送车费"),
        other_adjusted_yuan=_optional_decimal(payload.get("otherAdjustedYuan"), Decimal("0"), "其他费"),
    )


def serialize_rail_freight_calculator_result(
    values: RailFreightCalculatorInput,
) -> dict[str, Any]:
    """Return a calculator-only result; it is never a route-planning result."""

    result = calculate_rail_freight_workbook(values)
    return {
        "status": "resolved",
        "scope": "workbook_reproduction_only",
        "inputs": {
            "loadTons": str(values.load_tons),
            "totalFreightYuan": str(values.total_freight_yuan),
            "discountRatio": str(values.discount_ratio),
            "electrifiedKm": str(values.electrified_km),
        },
        "lines": [
            {
                "name": line.name,
                "fullPriceYuan": _decimal_text(line.full_price_yuan),
                "dividedBy0991Yuan": _decimal_text(line.divided_by_0991_yuan),
                "dividedBy09911Yuan": _decimal_text(line.divided_by_09911_yuan),
                "adjustedYuan": _decimal_text(line.adjusted_yuan),
                "note": line.note,
            }
            for line in result.lines
        ],
        "totals": {
            "fullPriceTotalYuan": str(result.full_price_total_yuan),
            "adjustedTotalYuan": str(result.adjusted_total_yuan),
            "originalWorkbookUnitPriceYuanPerTon": str(result.original_workbook_unit_price_yuan_per_ton),
            "inputLoadUnitPriceYuanPerTon": str(result.input_load_unit_price_yuan_per_ton),
        },
        "warnings": list(result.warnings),
    }


def serialize_full_flow_result(
    result: RoutePlanningResponse,
    *,
    route_control_points: RouteControlPointNetwork | None = None,
) -> dict[str, Any]:
    points = {
        result.origin_resolution.node_id
        or result.recommendations.lowest_cost.path_node_ids[0]: {
            "nodeId": result.origin_resolution.node_id
            or result.recommendations.lowest_cost.path_node_ids[0],
            "name": result.origin_resolution.canonical_name or result.origin_name,
            "longitude": float(result.origin_resolution.longitude),
            "latitude": float(result.origin_resolution.latitude),
        },
        result.destination_resolution.node_id
        or result.recommendations.lowest_cost.path_node_ids[-1]: {
            "nodeId": result.destination_resolution.node_id
            or result.recommendations.lowest_cost.path_node_ids[-1],
            "name": result.destination_resolution.canonical_name
            or result.destination_name,
            "longitude": float(result.destination_resolution.longitude),
            "latitude": float(result.destination_resolution.latitude),
        },
    }
    for port in result.candidate_ports:
        points[port.node_id] = {
            "nodeId": port.node_id,
            "name": port.name,
            "longitude": float(port.point.longitude),
            "latitude": float(port.point.latitude),
        }
    for port in result.intermediate_ports:
        points[port.node_id] = {
            "nodeId": port.node_id,
            "name": port.name,
            "longitude": float(port.point.longitude),
            "latitude": float(port.point.latitude),
        }
    return {
        "status": "resolved",
        "request": {
            "origin": result.origin_name,
            "destination": result.destination_name,
            "southPort": result.selected_south_port,
            "quantity": str(result.request.quantity),
            "quantityUnit": result.request.quantity_unit,
            "packageType": result.request.package_type,
            "commodity": result.request.commodity,
            "tradeType": result.request.trade_type,
        },
        "routes": {
            "lowestCost": _serialize_route(
                result.recommendations.lowest_cost,
                result,
                points,
                route_control_points=route_control_points,
            ),
            "fastestTime": _serialize_route(
                result.recommendations.fastest_time,
                result,
                points,
                route_control_points=route_control_points,
            ),
        },
        "candidates": [
            {
                **points[port.node_id],
                "straightLineKmToFactory": str(
                    port.straight_line_km_to_factory
                ),
                "lastMileModes": list(
                    result.south_to_customer_options_by_port.get(port.node_id, ())
                ),
            }
            for port in result.candidate_ports
        ],
        "candidateDecisions": [
            {
                "nodeId": decision.node_id,
                "name": decision.name,
                "status": decision.status,
                "stage": decision.stage,
                "reason": decision.reason,
                "evidence": list(decision.evidence),
            }
            for decision in result.candidate_decisions
        ],
        "intermediatePorts": [
            points[port.node_id]
            for port in result.intermediate_ports
        ],
        "runInfo": {
            "graphEdgeCount": result.graph_edge_count,
            "bulkShippingEdgeCount": result.trunk_edge_count,
            "truckEdgeCount": result.truck_edge_count,
            "bargeEdgeCount": result.barge_edge_count,
            "operationFeeIncludedCount": result.port_operation_fee_included_count,
            "operationFeeNotApplicableCount": (
                result.port_operation_fee_not_applicable_count
            ),
            "bargePlaceholderCapabilityCount": (
                result.barge_placeholder_capability_count
            ),
            "warnings": list(result.warnings),
            "routeGeometryMode": "mixed_by_segment",
            "routeControlPointSource": (
                route_control_points.source_file.name
                if route_control_points is not None
                else None
            ),
            "routeControlPointCount": (
                route_control_points.point_count
                if route_control_points is not None
                else 0
            ),
            "preciseRoadGeometryCount": sum(
                1
                for geometry in result.edge_geometries.values()
                if geometry.kind == "tencent_driving_polyline"
                and not geometry.is_schematic
            ),
        },
    }


def _unit_cost_yuan(route: Any, result: RoutePlanningResponse) -> str | None:
    """总费用 ÷ 订单数量，得到折合单价（元/单位，如元/吨）。"""
    quantity = Decimal(str(result.request.quantity))
    if quantity <= 0:
        return None
    return str(route.total_cost_yuan / quantity)


def _serialize_route(
    route: Any,
    result: RoutePlanningResponse,
    points: dict[str, dict[str, Any]],
    *,
    route_control_points: RouteControlPointNetwork | None = None,
) -> dict[str, Any]:
    return {
        "status": route.status,
        "totalCostYuan": str(route.total_cost_yuan),
        "unitCostYuan": _unit_cost_yuan(route, result),
        "totalTimeHours": str(route.total_time_hours),
        "pathNodeIds": list(route.path_node_ids),
        "pathNames": [
            result.node_names.get(node_id, node_id)
            for node_id in route.path_node_ids
        ],
        "points": [
            points[node_id]
            for node_id in route.path_node_ids
            if node_id in points
        ],
        "segments": [
            {
                "segmentNo": segment.segment_no,
                "fromNodeId": segment.from_node_id,
                "toNodeId": segment.to_node_id,
                "fromName": result.node_names.get(
                    segment.from_node_id,
                    segment.from_node_id,
                ),
                "toName": result.node_names.get(
                    segment.to_node_id,
                    segment.to_node_id,
                ),
                "transportMode": segment.transport_mode,
                "transportStage": segment.transport_stage,
                "edgeRole": segment.edge_role,
                "timeScope": segment.time_scope,
                "costYuan": str(segment.cost_yuan),
                "timeHours": str(segment.time_hours),
                "ruleId": segment.cost_rule_id,
                "ruleVersion": segment.cost_rule_version,
                "costComponents": [
                    {
                        "type": component.component_type,
                        "amountYuan": str(component.amount_yuan),
                        "sourceType": component.source_type,
                        "ruleId": component.rule_id,
                        "ruleVersion": component.rule_version,
                        "detail": component.calculation_detail,
                    }
                    for component in segment.cost_components
                ],
                "sourceExplanation": result.edge_sources[
                    segment.edge_key
                ].explanation,
                "geometry": _serialize_segment_geometry(
                    segment,
                    result,
                    points,
                    route_control_points=route_control_points,
                ),
            }
            for segment in route.segments
        ],
    }


def _serialize_segment_geometry(
    segment: Any,
    result: RoutePlanningResponse,
    points: dict[str, dict[str, Any]],
    *,
    route_control_points: RouteControlPointNetwork | None = None,
) -> dict[str, Any]:
    if segment.transport_mode == "散船":
        endpoints = _segment_endpoints(segment, points)
        if endpoints is None:
            return _unavailable_geometry("散船段缺少可用于地图展示的端点坐标。")
        origin, destination = endpoints
        geometry = build_bulk_shipping_schematic(
            origin,
            destination,
            destination_name=result.node_names.get(
                segment.to_node_id,
                segment.to_node_id,
            ),
            control_point_network=route_control_points,
        )
        return _serialize_schematic_geometry(geometry)

    if segment.transport_mode == "汽运":
        geometry = result.edge_geometries.get(segment.edge_key)
        if geometry is None:
            return _unavailable_geometry(
                "腾讯本次未返回可用道路折线；保留费用和时效结果，但不绘制端点直线冒充真实道路。"
            )
        return _serialize_edge_geometry(geometry)

    if segment.transport_mode == "驳船":
        endpoints = _segment_endpoints(segment, points)
        if endpoints is None:
            return _unavailable_geometry("驳船段缺少可用于地图展示的端点坐标。")
        return _serialize_schematic_geometry(
            build_barge_schematic(
                *endpoints,
                control_point_network=route_control_points,
            )
        )

    return _unavailable_geometry(
        f"运输方式 {segment.transport_mode} 尚未配置地图几何。"
    )


def _segment_endpoints(
    segment: Any,
    points: dict[str, dict[str, Any]],
) -> tuple[GeoPoint, GeoPoint] | None:
    origin = points.get(segment.from_node_id)
    destination = points.get(segment.to_node_id)
    if origin is None or destination is None:
        return None
    return (
        GeoPoint(
            longitude=Decimal(str(origin["longitude"])),
            latitude=Decimal(str(origin["latitude"])),
        ),
        GeoPoint(
            longitude=Decimal(str(destination["longitude"])),
            latitude=Decimal(str(destination["latitude"])),
        ),
    )


def _serialize_edge_geometry(geometry: EdgeGeometryTrace) -> dict[str, Any]:
    return {
        "kind": geometry.kind,
        "source": geometry.source,
        "isSchematic": geometry.is_schematic,
        "message": geometry.message,
        "points": [_serialize_geo_point(point) for point in geometry.points],
    }


def _serialize_schematic_geometry(
    geometry: SchematicRouteGeometry,
) -> dict[str, Any]:
    return {
        "kind": geometry.kind,
        "source": geometry.source,
        "isSchematic": geometry.is_schematic,
        "message": geometry.message,
        "points": [_serialize_geo_point(point) for point in geometry.points],
    }


def _serialize_geo_point(point: GeoPoint) -> dict[str, float]:
    return {
        "longitude": float(point.longitude),
        "latitude": float(point.latitude),
    }


def _unavailable_geometry(message: str) -> dict[str, Any]:
    return {
        "kind": "unavailable",
        "source": "unavailable",
        "isSchematic": False,
        "message": message,
        "points": [],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="港口路径规划本地前端服务")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="显式允许绑定非本机回环地址；默认禁止，避免本地 Key 被局域网访问。",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not args.allow_network:
        raise SystemExit("非本机地址需要显式添加 --allow-network。")
    try:
        context = RouteWebContext.load()
    except (RuntimeEnvError, DataLoadError) as exc:
        raise SystemExit(f"前端服务未启动：{exc}") from exc
    server = RouteWebServer((args.host, args.port), context)
    print(f"港口路径规划展示页：http://{args.host}:{args.port}")
    print("本地配置已加载；敏感值不会写入源码或控制台。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{field_name}不能为空。")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_decimal(value: object, field_name: str) -> Decimal:
    text = _required_text(value, field_name)
    try:
        return Decimal(text)
    except Exception:
        raise ValueError(f"{field_name}必须是数值。") from None


def _optional_decimal(value: object, default: Decimal, field_name: str) -> Decimal:
    if value is None or str(value).strip() == "":
        return default
    try:
        return Decimal(str(value).strip())
    except Exception:
        raise ValueError(f"{field_name}必须是数值。") from None


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _safe_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
