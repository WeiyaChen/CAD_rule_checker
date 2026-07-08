import argparse
import json
import math
import os
import sys
from pathlib import Path

from shapely.geometry import LineString, Polygon
from shapely.wkt import loads

from src.config.config import settings


class GeometryEnricher:
    def __init__(self, graph_dict):
        """
        初始化几何富化器 (内存解耦版)
        :param graph_dict: 输入的 JSON-LD 字典数据
        """
        self.data = graph_dict
        # 直接解析内存字典，不再执行 with open() 读取操作
        self.nodes = {node.get("@id"): node for node in self.data.get("@graph", [])}

    def _extract_wkt(self, node):
        """从节点中安全提取 WKT 字符串"""
        geo_wkt = node.get("geo:asWKT")
        if not geo_wkt:
            return None
        if isinstance(geo_wkt, dict):
            return geo_wkt.get("@value")
        elif isinstance(geo_wkt, str):
            return geo_wkt
        return None

    def _get_mrr_metrics(self, polygon_geom):
        """常规空间：提取几何的最小外接矩形，返回面积、长边、短边"""
        area_sqm = polygon_geom.area / 1_000_000.0
        rect = polygon_geom.minimum_rotated_rectangle

        # 几何退化防范
        if rect.geom_type in ['LineString', 'Point']:
            return round(area_sqm, 2), round(rect.length / 1000.0, 2), 0.0

        coords = list(rect.exterior.coords)
        if len(coords) < 4:
            return round(area_sqm, 2), 0.0, 0.0

        edge1 = math.dist(coords[0], coords[1]) / 1000.0
        edge2 = math.dist(coords[1], coords[2]) / 1000.0

        length = max(edge1, edge2)
        width = min(edge1, edge2)

        return round(area_sqm, 2), round(length, 2), round(width, 2)

    def _get_corridor_clear_width(self, polygon_geom):
        """交通空间：基于纯矢量几何的非相邻边界最小距离算法计算真实通行净宽"""
        if polygon_geom.geom_type != 'Polygon':
            return 0.0

        coords = list(polygon_geom.exterior.coords)
        if len(coords) < 4:
            _, _, width = self._get_mrr_metrics(polygon_geom)
            return width

        edges = []
        for i in range(len(coords) - 1):
            edges.append(LineString([coords[i], coords[i + 1]]))

        min_dist = float('inf')
        found_non_adjacent = False
        num_edges = len(edges)

        # 双重循环计算所有非相邻线段的最短距离
        for i in range(num_edges):
            for j in range(i + 2, num_edges):
                # 排除首尾相接的边（在闭合多边形起点处的相邻边）
                if i == 0 and j == num_edges - 1:
                    continue

                distance = edges[i].distance(edges[j])
                if distance < min_dist:
                    min_dist = distance
                    found_non_adjacent = True

        if found_non_adjacent:
            return round(min_dist / 1000.0, 2)
        else:
            _, _, width = self._get_mrr_metrics(polygon_geom)
            return width

    def _calculate_metrics(self, wkt_str, node_id, node_types):
        """核心数学计算模块：解析 WKT 并根据语义类型调度算子"""
        try:
            polygon = loads(wkt_str)
            if not isinstance(polygon, Polygon):
                return None, None, None

            # 【策略模式】：根据高层语义反向调度底层计算算子
            is_corridor = any("Corridor" in t for t in node_types)

            if is_corridor:
                area_sqm = round(polygon.area / 1_000_000.0, 2)
                calculated_width = self._get_corridor_clear_width(polygon)
                # 交通空间核心关注点为“通行净宽”，长边无意义，此处为兼容接口返回 0.0
                return area_sqm, 0.0, calculated_width
            else:
                area, length, width = self._get_mrr_metrics(polygon)
                return area, length, width

        except Exception as e:
            print(f"  [-] WKT 解析出错: 节点 {node_id} - {e}")
            return None, None, None

    def enrich(self):
        """执行全图谱几何特征计算"""
        print("[GeometryEnricher] 启动几何计算引擎 (基于语义反馈调度的差异化特征提取)...")
        enrich_count = 0

        for node_id, node in self.nodes.items():
            wkt_str = self._extract_wkt(node)
            if not wkt_str: continue

            types = node.get("@type", [])
            if isinstance(types, str): types = [types]

            area, length, width = self._calculate_metrics(wkt_str, node_id, types)
            if area is None: continue

            # 房间/空间节点处理
            if "bot:Space" in types:
                node["props:hasArea"] = area

                # 根据语义区分属性命名，匹配 SHACL 规则接口要求
                is_corridor = any("Corridor" in t for t in types)
                if is_corridor:
                    node["props:clearWidth"] = width  # 过道通行净宽
                else:
                    node["props:hasShortSide"] = width  # 常规空间最小面宽

                enrich_count += 1

            # 门构件节点处理
            elif "beo:Door" in types:
                node["props:clearWidth"] = length  # 门的开口长度通常被识别为 length
                enrich_count += 1

        print(f"[GeometryEnricher] 几何计算完毕！共为 {enrich_count} 个物理构件挂载了数学尺寸。")
        return self.data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="几何富化器")
    parser.add_argument("--input", default=str(settings.resolve_project_path(settings.sample_input_jsonld)), help="输入 JSON-LD 文件")
    parser.add_argument("--output", default=None, help="输出 JSON-LD 文件")
    args = parser.parse_args()

    input_file = Path(args.input)
    if not input_file.is_absolute():
        input_file = settings.resolve_project_path(input_file)

    if input_file.exists():
        print(f"[GeometryEnricher] 独立测试模式：读取 {input_file}")
        with open(input_file, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)

        enricher = GeometryEnricher(raw_data)
        enriched_data = enricher.enrich()

        out_file = Path(args.output) if args.output else input_file.with_name(input_file.stem + "_geo.json")
        if not out_file.is_absolute():
            out_file = settings.resolve_project_path(out_file)

        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(enriched_data, f, ensure_ascii=False, indent=2)
        print(f"[GeometryEnricher] 独立测试模式：保存至 {out_file}")
    else:
        print(f"[GeometryEnricher] 错误：找不到文件 {input_file}")