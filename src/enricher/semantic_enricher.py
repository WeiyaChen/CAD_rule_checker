import argparse
import json
import os
import re
import sys
import time

# --- 新增 Shapely 依赖用于计算几何相交 ---
from shapely.wkt import loads as wkt_loads
from shapely.geometry import Point

# 引入标准的 openai 库（支持 OpenAI, DeepSeek, 智谱等所有兼容接口）
# pip install openai
import openai

from src.config.config import settings


class SemanticEnricher:
    def __init__(self, bot_graph_dict, room_texts, llm_client=None, llm_model=None):
        """
        初始化语义富化引擎
        Args:
            bot_graph_dict (dict): 第三章生成的 BOT 基础白模 JSON-LD 字典
            room_texts (list): 包含 {"text": "卧室", "point": (x, y)} 的字典列表
            llm_client: 实例化的大模型 API 客户端
        """
        self.graph = bot_graph_dict
        self.room_texts = room_texts or []
        self.llm_client = llm_client
        self.llm_model = llm_model or settings.llm_model

        # 建立全局字典缓存，加速查询
        self.element_cache = {}
        self.space_cache = {}

        self._build_cache()

    def _build_cache(self):
        """解析 JSON-LD，构建底层的快速查询索引"""
        for node in self.graph.get("@graph", []):
            node_id = node.get("@id")
            types = node.get("@type", [])

            if isinstance(types, str):
                types = [types]

            if "bot:Element" in types:
                self.element_cache[node_id] = node.get("rdfs:label", "unknown")

            if "bot:Space" in types:
                self.space_cache[node_id] = node

    def _extract_context_for_llm(self, target_space_ids=None):
        """
        剥离冗余几何坐标，提炼大模型所需的“纯文本推理上下文”
        :param target_space_ids: 可选，如果提供，则仅提取指定房间的上下文
        """
        inference_tasks = {}

        for room_id, node in self.space_cache.items():
            if target_space_ids is not None and room_id not in target_space_ids:
                continue

            area = node.get("props:hasArea", 0)
            contains_refs = node.get("bot:containsElement", [])
            furniture_labels = []

            for ref in contains_refs:
                element_id = ref.get("@id")
                label = self.element_cache.get(element_id)
                if label and "door" not in label.lower() and "window" not in label.lower() and label != "unknown":
                    furniture_labels.append(label)

            adjacent_refs = node.get("bot:adjacentZone", [])
            neighbor_ids = [ref.get("@id") for ref in adjacent_refs]

            inference_tasks[room_id] = {
                "area_sqm": area,
                "furniture": furniture_labels,
                "neighbors": neighbor_ids
            }

        return inference_tasks

    def _build_prompt(self, context_data, is_cleaning_task=False):
        """根据任务类型构建不同的提示词"""
        context_str = json.dumps(context_data, ensure_ascii=False, indent=2)

        # 任务A：如果是文本清洗任务
        if is_cleaning_task:
            return (
                f"请将以下图纸的原始OCR文本映射为标准建筑空间类型字典。\n"
                f"可选项: Bedroom, LivingRoom, Kitchen, Bathroom, Balcony, Corridor, Entrance, Garden, DiningRoom, ElevatorShaft, StorageRoom, Stairwell, Cloakroom, StudyRoom, SunRoom, WaterRoom, ElectricalRoom, VentilationRoom\n"
                f"先验知识：'更衣'对应的是Cloakroom\n"
                f"如果无法识别，请设为 'Unknown'。仅返回 JSON 格式，键为原文本，值为标准类型。\n"
                f"原始文本: {context_str}"
            )

        # 任务B：如果是模糊推理任务
        prompt_path = settings.prompt_config_dir
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                template = f.read()
            return template.replace("{context_data}", context_str)
        else:
            return f"推断以下房间功能(返回JSON)：\n{context_str}"

    def _parse_llm_response(self, raw_text):
        """健壮的 JSON 解析器"""
        try:
            pattern = '`' * 3 + r'(?:json)?\n?(.*?)\n?' + '`' * 3
            clean_text = re.sub(pattern, r'\1', raw_text, flags=re.DOTALL).strip()
            return json.loads(clean_text)
        except json.JSONDecodeError as e:
            print(f"大模型返回的 JSON 格式解析失败！原始内容:\n{raw_text}")
            return {}

    def _call_real_llm(self, prompt, fallback_result):
        """封装调用真实大模型的逻辑，并计算执行耗时"""
        if self.llm_client:
            try:
                # 记录调用前的时间戳
                start_time = time.time()

                response = self.llm_client.chat.completions.create(
                    model=self.llm_model,
                    messages=[
                        {"role": "system",
                         "content": "你是一位顶级的建筑信息模型（BIM）数据合规审查专家。请必须以严格的JSON格式输出结果。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"}
                )

                # 记录调用后的时间戳并计算耗时
                end_time = time.time()
                elapsed_time = end_time - start_time
                print(f"  [+] 大模型调用成功，推理耗时: {elapsed_time:.2f} 秒")

                return response.choices[0].message.content
            except Exception as e:
                print(f"  ⚠️ API 调用失败: {e}，将降级使用沙盒数据。")
        return fallback_result

    # =======================================================
    # 新增流水线阶段 1：清洗 OCR 文本
    # =======================================================
    def _stage1_clean_texts(self):
        """利用大模型将零散的中英文或缩写清洗为标准建筑类型"""
        if not self.room_texts:
            return []

        unique_texts = list(set([t["text"] for t in self.room_texts if t.get("text", "").strip()]))
        if not unique_texts:
            return []

        print("[Stage 1] 正在请求大模型清洗原始文本标注...")
        prompt = self._build_prompt(unique_texts, is_cleaning_task=True)
        # 降级兜底的清洗字典
        fallback_json = '{"次卧": "Bedroom", "主卫": "Bathroom", "餐客厅": "LivingRoom"}'

        raw_result = self._call_real_llm(prompt, fallback_json)
        # 👇 加上这一行，强制打印大模型的原始输出
        print(f"  [Debug] 大模型真实返回内容: {raw_result}")
        text_mapping = self._parse_llm_response(raw_result)

        cleaned_texts = []
        for item in self.room_texts:
            raw_txt = item.get("text", "")
            std_label = text_mapping.get(raw_txt, "Unknown")
            if std_label != "Unknown":
                cleaned_texts.append({
                    "point": item["point"],
                    "std_label": std_label,
                    "raw_text": raw_txt
                })
        return cleaned_texts

    # =======================================================
    # 新增流水线阶段 2：执行点在多边形内的空间匹配
    # =======================================================
    def _stage2_spatial_matching(self, cleaned_texts):
        """遍历图谱房间多边形，判断文字坐标是否落在其内部"""
        print("[Stage 2] 开始执行几何坐标与房间多边形的空间相交匹配...")
        matched_spaces = set()

        for space_id, node in self.space_cache.items():
            # 提取空间的 WKT 几何多边形
            geo_wkt = node.get("geo:asWKT")
            if not geo_wkt: continue

            wkt_str = geo_wkt.get("@value", "") if isinstance(geo_wkt, dict) else geo_wkt

            try:
                poly = wkt_loads(wkt_str)
                # 遍历所有有效文字，寻找落在该多边形内的点
                for txt_item in cleaned_texts:
                    pt = Point(txt_item["point"])
                    if poly.contains(pt):
                        label = f"bldg:{txt_item['std_label']}"

                        if isinstance(node.get("@type"), str):
                            node["@type"] = [node["@type"]]
                        if label not in node["@type"]:
                            node["@type"].append(label)

                        # ==========================================
                        # 新增：将原始文字标签与坐标点富化至图谱节点属性中
                        # ==========================================
                        # 专门为复合空间维护锚点列表，供 ACD 模块切分时使用
                        if "props:textAnchors" not in node:
                            node["props:textAnchors"] = []
                        node["props:textAnchors"].append({
                            "raw_text": txt_item['raw_text'],
                            "std_label": f"bldg:{txt_item['std_label']}",
                            "coordinates": txt_item['point']
                        })

                        matched_spaces.add(space_id)
                        print(f"  [+] 空间挂载成功: {space_id} -> {label} (基于坐标命中文字 '{txt_item['raw_text']}')")
            except Exception as e:
                pass  # 忽略畸形的 WKT 解析错误

        return matched_spaces

    # =======================================================
    # 主管线执行
    # =======================================================
    def execute_enrichment(self):
        """主引擎执行函数 (三段式流水线)"""
        print("\n" + "=" * 50)
        print("🚀 [SemanticEnricher] 多模态语义富化管线启动")
        print("=" * 50)

        # 阶段 1 & 2：精确匹配
        cleaned_texts = self._stage1_clean_texts()
        matched_space_ids = self._stage2_spatial_matching(cleaned_texts)

        # 阶段 3：对于没有文字标注的房间，执行基于上下文的模糊推理
        unmatched_space_ids = [sid for sid in self.space_cache.keys() if sid not in matched_space_ids]

        if unmatched_space_ids:
            print(f"\n[Stage 3] 发现 {len(unmatched_space_ids)} 个无文本空间，准备启动常识推理...")
            context_data = self._extract_context_for_llm(target_space_ids=unmatched_space_ids)

            prompt = self._build_prompt(context_data, is_cleaning_task=False)
            fallback_json = '{"inst:Space_001": ["Corridor"], "inst:Space_002": ["Bathroom"]}'

            raw_result = self._call_real_llm(prompt, fallback_json)
            inferred_room_types = self._parse_llm_response(raw_result)

            for room_id, bldg_types in inferred_room_types.items():
                if room_id in self.space_cache:
                    target_node = self.space_cache[room_id]
                    if isinstance(target_node["@type"], str):
                        target_node["@type"] = [target_node["@type"]]
                    if isinstance(bldg_types, str):
                        bldg_types = [bldg_types]

                    for bldg_type in bldg_types:
                        semantic_label = f"bldg:{bldg_type}"
                        if semantic_label not in target_node["@type"]:
                            target_node["@type"].append(semantic_label)
                            print(f"  [+] 模糊推理补全: {room_id} -> {semantic_label}")

        print("\n[SemanticEnricher] 数据富化流水线执行完毕！")
        return self.graph


# =====================================================================
# 独立测试区域
# =====================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="语义富化器")
    parser.add_argument("--input", default=str(settings.resolve_project_path(settings.sample_input_jsonld)), help="输入 JSON-LD 文件")
    parser.add_argument("--output", default=None, help="输出 JSON-LD 文件")
    parser.add_argument("--api-key", default=settings.llm_api_key, help="大模型 API Key")
    parser.add_argument("--base-url", default=settings.llm_base_url, help="大模型接口地址")
    parser.add_argument("--model", default=settings.llm_model, help="大模型模型名")
    args = parser.parse_args()

    test_file = Path(args.input)
    if not test_file.is_absolute():
        test_file = settings.resolve_project_path(test_file)

    if not test_file.exists():
        print(f"❌ 错误: 找不到测试数据文件 '{test_file}'")
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

    enricher = SemanticEnricher(parsed_graph_dict, mock_room_texts, my_client, llm_model=args.model)
    final_kg_dict = enricher.execute_enrichment()

    print("\n===== 最终房间语义结果 =====")
    for node in final_kg_dict["@graph"]:
        if "bot:Space" in node.get("@type", []) or any(t.startswith("bldg:") for t in node.get("@type", [])):
            print(f"房间检测 -> ID: {node['@id']}, 类型: {node.get('@type')}")

    output_filename = Path(args.output) if args.output else test_file.with_name(test_file.stem + "_semantic.json")
    if not output_filename.is_absolute():
        output_filename = settings.resolve_project_path(output_filename)
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(final_kg_dict, f, ensure_ascii=False, indent=2)