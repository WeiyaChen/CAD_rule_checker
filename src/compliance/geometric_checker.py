import json
import math
from shapely.wkt import loads

from src.config.config import settings


class GeometryChecker:
    def __init__(self, jsonld_path):
        self.filepath = jsonld_path
        # 使用原生 json 库读取，完美保留上下文和嵌套结构
        with open(self.filepath, 'r', encoding='utf-8') as f:
            self.data = json.load(f)
        print("几何特征审查器初始化完毕，已成功加载原始 JSON-LD 结构。")

    def enrich_bedroom_short_side(self):
        # 直接遍历 @graph 数组寻找目标节点
        for node in self.data.get("@graph", []):
            node_types = node.get("@type", [])
            # 兼容 @type 是单字符串或列表的情况
            if isinstance(node_types, str):
                node_types = [node_types]

            # 锁定具有卧室类型特征的节点并提取多边形字符串
            if "props:卧室" in node_types and "props:geometryWKT" in node:
                room_uri = node.get("@id")
                wkt_string = node.get("props:geometryWKT")

                try:
                    # 几何推演与特征计算逻辑
                    polygon = loads(wkt_string)
                    obb = polygon.minimum_rotated_rectangle
                    x, y = obb.exterior.coords.xy

                    edge1 = math.hypot(x[1] - x[0], y[1] - y[0])
                    edge2 = math.hypot(x[2] - x[1], y[2] - y[1])
                    short_side = round(min(edge1, edge2), 1)

                    # 直接在原字典实体中新增属性项，确保原有结构零破坏
                    node["props:shortSideWidth"] = short_side
                    print(f"节点 {room_uri} 计算得出短边净宽为 {short_side}mm，已追加至属性。")

                except Exception as e:
                    print(f"节点 {room_uri} 的几何多边形解析出现异常: {e}")

    def save_enriched_graph(self):
        # 按原有两格缩进的标准格式写回文件
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        print("数据富化完成，已在完全保留原结构的基础上覆盖保存至原文件。")

    def run_all_enrichments(self):
        print("\n--- 开始执行全流程几何特征推演 ---")
        self.enrich_bedroom_short_side()
        self.save_enriched_graph()


if __name__ == "__main__":
    checker = GeometryChecker(settings.output_jsonld_dir / "floorplan.jsonld")
    checker.run_all_enrichments()