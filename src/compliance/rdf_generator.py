from rdflib import Graph, Literal, RDF, URIRef, Namespace
from rdflib.namespace import XSD

# 定义命名空间 (类似于 Python 的 import，用于缩写 URI)
EX = Namespace("http://example.org/cad-checker/")


class FloorPlanRDFGenerator:
    def __init__(self):
        self.g = Graph()
        self.g.bind("ex", EX)  # 绑定前缀，让输出的 TTL 文件更易读

    def _map_label_to_class(self, label):
        """
        辅助函数：将中文/英文的标签映射为标准的本体类名
        """
        label = label.lower()
        if "bed" in label or "卧" in label:
            return EX.Bedroom
        elif "living" in label or "起居" in label or "厅" in label:
            return EX.LivingRoom
        elif "kitchen" in label or "厨" in label:
            return EX.Kitchen
        elif "bath" in label or "卫" in label:
            return EX.Bathroom
        elif "entry" in label or "玄关" in label:
            return EX.Entryway
        else:
            return EX.Room  # 默认兜底类型

    def generate_phase1_data(self, rooms_data, project_name="my_apartment"):
        """
        生成第一阶段的 TTL 数据
        Args:
            rooms_data: 你的识图结果 list [{'id':..., 'label':...}]
        """
        # 1. 创建户型的主节点
        # 假设我们检查的是一个 ID 为 project_name 的户型
        apt_node = EX[project_name]
        self.g.add((apt_node, RDF.type, EX.Apartment))

        # 2. 遍历所有识别出的房间
        for room in rooms_data:
            # 构建房间的唯一 URI，例如 http://example.org/cad-checker/room_0
            # 建议使用 room['id'] 保证唯一性
            room_node = EX[f"room_{room.get('id', 'unknown')}"]

            # A. 确定房间类型 (Class)
            # 例如: ex:room_0 a ex:Bedroom
            room_class = self._map_label_to_class(room.get('label', ''))
            self.g.add((room_node, RDF.type, room_class))

            # B. 建立户型与房间的关系
            # 例如: ex:my_apartment ex:hasSpace ex:room_0
            self.g.add((apt_node, EX.hasSpace, room_node))

            # (可选) 存储原始标签方便调试
            self.g.add((room_node, EX.hasLabel, Literal(room.get('label', ''), datatype=XSD.string)))

        return self.g

    def save_to_file(self, filename="floorplan_data.ttl"):
        self.g.serialize(destination=filename, format="turtle")
        print(f"✅ 数据已保存至 {filename}")