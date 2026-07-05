# 修改 src/compliance/shacl_engine.py 的返回值逻辑
from rdflib import Graph
from pyshacl import validate

class ShaclValidationEngine:
    def run_validation(self, data_file, shacl_file):
        data_graph = Graph()
        data_graph.parse(data_file, format="json-ld")
        shacl_graph = Graph()
        shacl_graph.parse(shacl_file, format="turtle")

        conforms, results_graph, results_text = validate(
            data_graph, shacl_graph=shacl_graph, inference='rdfs', abort_on_first=False
        )

        # 核心新增：提取结构化的违规列表
        violations_list = []
        if not conforms:
            query = """
                PREFIX sh: <http://www.w3.org/ns/shacl#>
                SELECT ?focusNode ?message
                WHERE {
                    ?report a sh:ValidationReport ;
                            sh:result ?result .
                    ?result sh:focusNode ?focusNode ;
                            sh:resultMessage ?message .
                }
            """
            for row in results_graph.query(query):
                node_uri = str(row.focusNode)
                # 将 RDF 长 URI 还原为图谱中使用的简写 @id
                node_id = node_uri.replace("http://mythesis.org/instance/", "inst:")
                violations_list.append({
                    "node_id": node_id,
                    "message": str(row.message)
                })

        # 返回三个值：是否合规、文本报告、结构化违规列表
        return conforms, results_text, violations_list