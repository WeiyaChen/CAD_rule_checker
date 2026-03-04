from pyshacl import validate
from rdflib import Graph


class ShaclValidationEngine:
    def __init__(self):
        print("启动统一合规审查引擎 (SHACL Engine)...")

    def run_validation(self, data_graph_path, shape_graph_path):
        print(f"正在加载被测数据: {data_graph_path}")
        print(f"正在加载审查规则: {shape_graph_path}")

        # 加载被测数据图谱
        data_graph = Graph()
        data_graph.parse(data_graph_path, format="json-ld")

        # 加载 SHACL 规则图谱
        shape_graph = Graph()
        shape_graph.parse(shape_graph_path, format="turtle")

        # 执行核心验证逻辑
        conforms, results_graph, results_text = validate(
            data_graph,
            shacl_graph=shape_graph,
            inference='rdfs',
            abort_on_first=False,
            meta_shacl=False,
            advanced=True,
            debug=False
        )

        return conforms, results_text