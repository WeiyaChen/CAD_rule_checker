# src/enricher/semantic_enricher.py
"""语义富化：把"空间类型识别"算法的结果写回 BOT 知识图谱。

本模块现在只是图谱适配器：它负责 JSON-LD 与
:mod:`src.spatial.domain` 领域对象之间的双向转换，真正做识别的算法来自
:mod:`src.spatial` 的注册表。因此替换或新增同类算法时无需改动本文件。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import openai
from shapely.wkt import loads as wkt_loads

from src.config.config import settings
from src.spatial.domain import (
    SOURCE_TEXT_MATCH,
    SpatialComponent,
    SpatialContour,
    SpaceTypePrediction,
    TextAnnotation,
)
from src.spatial.factory import create_space_type_classifier

#: 构件缺少 ``rdfs:label`` 时的占位标签。
UNKNOWN_LABEL = "unknown"


class SemanticEnricher:
    """BOT 基础图谱 → 语义富化图谱。

    Args:
        bot_graph_dict: 第三章生成的 BOT 基础白模 JSON-LD 字典。
        room_texts: 包含 ``{"text": "卧室", "point": (x, y)}`` 的字典列表。
        llm_client: 实例化的大模型 API 客户端（算法需要时使用）。
        llm_model: 大模型名称；``None`` 时读取 ``settings.llm_model``。
        classifier: 已创建的空间类型识别算法实例；``None`` 时按配置创建。
    """

    def __init__(self, bot_graph_dict, room_texts, llm_client=None, llm_model=None, classifier=None):
        self.graph = bot_graph_dict
        self.room_texts = room_texts or []
        self.llm_client = llm_client
        self.llm_model = llm_model or settings.llm_model
        self._classifier = classifier

        # 建立全局字典缓存，加速查询
        self.node_cache = {}
        self.element_cache = {}
        self.space_cache = {}

        self._build_cache()

    # ------------------------------------------------------------------
    # 图谱 → 领域对象
    # ------------------------------------------------------------------
    def _build_cache(self):
        """解析 JSON-LD，构建底层的快速查询索引"""
        for node in self.graph.get("@graph", []):
            node_id = node.get("@id")
            types = node.get("@type", [])

            if isinstance(types, str):
                types = [types]

            self.node_cache[node_id] = node

            if "bot:Element" in types:
                self.element_cache[node_id] = node.get("rdfs:label", UNKNOWN_LABEL)

            if "bot:Space" in types:
                self.space_cache[node_id] = node

    def _resolve_classifier(self):
        """解析要使用的空间类型识别算法（注入优先，否则按配置创建）。"""
        if self._classifier is None:
            self._classifier = create_space_type_classifier(
                llm_client=self.llm_client,
                llm_model=self.llm_model,
            )
        return self._classifier

    @staticmethod
    def _wkt_to_exterior_coords(geo_wkt):
        """把 ``geo:asWKT`` 值还原成外环坐标；解析失败时返回空列表。"""
        if not geo_wkt:
            return []
        wkt_str = geo_wkt.get("@value", "") if isinstance(geo_wkt, dict) else geo_wkt
        if not wkt_str:
            return []
        try:
            return list(wkt_loads(wkt_str).exterior.coords)
        except Exception:
            return []

    def _build_contours(self) -> list[SpatialContour]:
        """按图谱节点顺序构建空间轮廓（顺序决定预测写回顺序，必须稳定）。"""
        contours = []
        for space_id, node in self.space_cache.items():
            contours.append(
                SpatialContour(
                    id=space_id,
                    geometry=self._wkt_to_exterior_coords(node.get("geo:asWKT")),
                    area_sqm=node.get("props:hasArea", 0),
                    elements=[
                        ref.get("@id") for ref in node.get("bot:containsElement", []) if ref.get("@id")
                    ],
                    neighbors=[
                        ref.get("@id") for ref in node.get("bot:adjacentZone", []) if ref.get("@id")
                    ],
                    attributes={"node": node},
                )
            )
        return contours

    def _build_texts(self) -> list[TextAnnotation]:
        """把 ``room_texts`` 转换为领域对象（保留原始坐标，不做数值转换）。"""
        return [
            TextAnnotation(raw_text=item.get("text", ""), point=item["point"])
            for item in self.room_texts
            if item.get("point") is not None
        ]

    def _build_components(self) -> list[SpatialComponent]:
        """把构件节点转换为领域对象，供算法做家具/门窗推理。"""
        components = []
        for element_id, label in self.element_cache.items():
            node_types = self.node_cache.get(element_id, {}).get("@type") or []
            if isinstance(node_types, str):
                node_types = [node_types]
            category = next(
                (t.split(":", 1)[1] for t in node_types if isinstance(t, str) and t.startswith("beo:")),
                "",
            )
            components.append(
                SpatialComponent(
                    uid=element_id,
                    category=category,
                    specific_type=None if label == UNKNOWN_LABEL else label,
                )
            )
        return components

    # ------------------------------------------------------------------
    # 领域对象 → 图谱
    # ------------------------------------------------------------------
    def _node_types(self, node) -> list[str]:
        """取得可变的 ``@type`` 列表（字符串形式会被就地规范化成列表）。"""
        types = node.get("@type")
        if isinstance(types, str):
            types = [types]
            node["@type"] = types
        elif types is None:
            types = []
            node["@type"] = types
        return types

    def _apply_predictions(self, predictions) -> None:
        """按算法返回顺序把预测结果写回图谱节点。"""
        for prediction in predictions:
            node = self.space_cache.get(prediction.contour_id)
            if node is None:
                continue

            types = self._node_types(node)
            for space_type in prediction.types:
                label = f"bldg:{space_type}"
                is_new = label not in types
                if is_new:
                    types.append(label)

                if prediction.source != SOURCE_TEXT_MATCH:
                    if is_new:
                        print(f"  [+] Fuzzy inference completed: {prediction.contour_id} -> {label}")
                    continue

                # 专门为复合空间维护锚点列表，供 ACD 模块切分时使用
                annotation = prediction.annotation
                node.setdefault("props:textAnchors", []).append({
                    "raw_text": annotation.raw_text if annotation else "",
                    "std_label": label,
                    "coordinates": annotation.point if annotation else None,
                })
                hit_text = annotation.raw_text if annotation else ""
                print(
                    f"  [+] Spatial mount successful: {prediction.contour_id} -> {label} "
                    f"(hit text '{hit_text}')"
                )

    # ------------------------------------------------------------------
    # 主管线执行
    # ------------------------------------------------------------------
    def execute_enrichment(self):
        """把图谱交给空间类型识别算法，并把结果写回图谱。"""
        print("\n" + "=" * 50)
        print("🚀 [SemanticEnricher] Multi-modal semantic enrichment pipeline started")
        print("=" * 50)

        contours = self._build_contours()
        predictions: list[SpaceTypePrediction] = self._resolve_classifier().classify(
            contours=contours,
            texts=self._build_texts(),
            components=self._build_components(),
        )
        self._apply_predictions(predictions)

        print("\n[SemanticEnricher] Data enrichment pipeline complete!")
        return self.graph


# =====================================================================
# 独立测试区域
# =====================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Semantic Enricher")
    parser.add_argument("--input", default=str(settings.resolve_project_path(settings.sample_input_jsonld)), help="Input JSON-LD file")
    parser.add_argument("--output", default=None, help="Output JSON-LD file")
    parser.add_argument("--api-key", default=settings.llm_api_key, help="LLM API Key")
    parser.add_argument("--base-url", default=settings.llm_base_url, help="LLM API base URL")
    parser.add_argument("--model", default=settings.llm_model, help="LLM model name")
    parser.add_argument("--classifier-algo", default=None, help="Space type classifier algorithm name")
    args = parser.parse_args()

    test_file = Path(args.input)
    if not test_file.is_absolute():
        test_file = settings.resolve_project_path(test_file)

    if not test_file.exists():
        print(f"❌ ERROR: Test data file not found '{test_file}'")
        sys.exit(1)

    with open(test_file, "r", encoding="utf-8") as f:
        parsed_graph_dict = json.load(f)

    mock_room_texts = [
        {"text": "主卧室", "point": (100, 200)},
        {"text": "Kitchen", "point": (4500, 2100)}
    ]

    my_client = None
    if args.api_key:
        my_client = openai.Client(api_key=args.api_key, base_url=args.base_url)

    enricher = SemanticEnricher(
        parsed_graph_dict,
        mock_room_texts,
        my_client,
        llm_model=args.model,
        classifier=create_space_type_classifier(args.classifier_algo, llm_client=my_client, llm_model=args.model)
        if args.classifier_algo else None,
    )
    final_kg_dict = enricher.execute_enrichment()

    print("\n===== Final Room Semantic Results =====")
    for node in final_kg_dict["@graph"]:
        if "bot:Space" in node.get("@type", []) or any(t.startswith("bldg:") for t in node.get("@type", [])):
            print(f"Room -> ID: {node['@id']}, Type: {node.get('@type')}")

    output_filename = Path(args.output) if args.output else test_file.with_name(test_file.stem + "_semantic.json")
    if not output_filename.is_absolute():
        output_filename = settings.resolve_project_path(output_filename)
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(final_kg_dict, f, ensure_ascii=False, indent=2)
