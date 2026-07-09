import json
import xml.etree.ElementTree as ET
from shapely.wkt import loads as wkt_loads

try:
    import ezdxf
    from ezdxf import bbox
except ImportError:
    print("❌ ezdxf library not found. Please run: pip install ezdxf")


def convert_gt_to_svg(dxf_path, json_path, svg_path):
    """
    【新增功能】
    读取人工标注的 JSON/JSON-LD 文件，并利用原始 DXF 文件的几何包围盒参数，
    将 WKT 物理坐标严格映射转换为对齐的 SVG 文件。
    """
    # 1. 再次读取 DXF 以获取一模一样的缩放系数
    try:
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        ext = bbox.extents(msp)
        if not ext.has_data:
            raise ValueError("DXF 图纸为空或无法获取边界框。")

        xmin, xmax = ext.extmin[0], ext.extmax[0]
        ymin, ymax = ext.extmin[1], ext.extmax[1]

        sx = 140 / (xmax - xmin)
        sy = 140 / (ymax - ymin)
        s = min(sx, sy)
    except Exception as e:
        print(f"Failed to get DXF parameters: {e}")
        return

    # 2. 读取 JSON 文件
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            gt_data = json.load(f)
    except Exception as e:
        print(f"Failed to read annotation file: {e}")
        return

    # 3. 创建半透明的可视化 SVG 根节点
    svg = ET.Element('svg', {
        "xmlns": "http://www.w3.org/2000/svg",
        "style": "background-color:transparent",
        "scale": str(s),
        "viewBox": "0 0 140 140"
    })

    g = ET.SubElement(svg, 'g', id="ground_truth_polygons")

    # 定义标准房间的颜色映射 (RGBA格式以支持半透明叠加)
    color_map = {
        "Bedroom": "rgba(255, 228, 181, 0.6)",  # 浅木色
        "LivingRoom": "rgba(240, 230, 140, 0.6)",  # 浅黄色
        "Kitchen": "rgba(255, 218, 185, 0.6)",  # 浅橙色
        "Bathroom": "rgba(224, 255, 255, 0.6)",  # 浅青色
        "Corridor": "rgba(211, 211, 211, 0.6)",  # 灰色
        "Entrance": "rgba(211, 211, 211, 0.6)",  # 灰色
        "Balcony": "rgba(173, 216, 230, 0.6)"  # 浅蓝色
    }

    # 4. 解析 WKT 坐标并执行数学转换
    # 兼容两种格式：一种是 annotation_helper 输出的 {"rooms": {...}}，一种是直接的 JSON-LD "@graph"
    rooms_data = gt_data.get("rooms", {})
    if not rooms_data and "@graph" in gt_data:
        for node in gt_data["@graph"]:
            if "geo:asWKT" in node:
                wkt_str = node["geo:asWKT"].get("@value", node["geo:asWKT"]) if isinstance(node["geo:asWKT"], dict) else \
                    node["geo:asWKT"]
                sem_type = [t.replace("bldg:", "") for t in node.get("@type", []) if t.startswith("bldg:")]
                rooms_data[node.get("@id")] = {
                    "wkt": wkt_str,
                    "semantic_type": sem_type[0] if sem_type else "Unknown"
                }

    for r_id, r_info in rooms_data.items():
        wkt_str = r_info.get("wkt")
        if not wkt_str:
            continue

        try:
            poly = wkt_loads(wkt_str)
            if poly.is_empty or poly.geom_type not in ['Polygon', 'MultiPolygon']:
                continue

            polys = [poly] if poly.geom_type == 'Polygon' else poly.geoms

            for p in polys:
                coords = list(p.exterior.coords)
                d_str = ""

                # 核心转化推导：由于构建标注时 sys_x = x_cad + offset_x/s - xmin
                # 而 SVG 的转化逻辑为：x_svg = offset_x + s * (x_cad - xmin)
                # 等量代换可得：x_svg = s * sys_x，且 Y 轴需要翻转。
                for i, (sys_x, sys_y) in enumerate(coords):
                    x_svg = sys_x * s
                    y_svg = 140 - (sys_y * s)
                    if i == 0:
                        d_str += f"M {x_svg:.4f},{y_svg:.4f}"
                    else:
                        d_str += f" L {x_svg:.4f},{y_svg:.4f}"
                d_str += " Z"

                sem_type = r_info.get("semantic_type", "Unknown")
                fill_color = color_map.get(sem_type, "rgba(200, 200, 200, 0.4)")

                ET.SubElement(g, 'path', d=d_str, fill=fill_color, stroke="rgb(50,50,50)", **{"stroke-width": "0.15"})

        except Exception as e:
            print(f"Error parsing WKT for {r_id}: {e}")

    # 5. 保存并写入文件
    tree = ET.ElementTree(svg)
    tree.write(svg_path, encoding='utf-8', xml_declaration=True)


if __name__ == "__main__":
    # 独立运行的测试入口示例
    # 您可根据需要修改此处的文件路径
    sample_dxf = "D:\\CS Project\\PyCharm\\cad_rule_checker\\data\\raw\dxf\\南阳名门_1.dxf"
    sample_json = "D:\\CS Project\\PyCharm\\cad_rule_checker\\output\\ground_truth\\南阳名门_1_已标注_ground_truth.jsonld"
    sample_svg = "D:\\CS Project\\PyCharm\\cad_rule_checker\\data\\raw\\svg_gt\\南阳名门_1_gt.svg"

    import os

    if os.path.exists(sample_dxf) and os.path.exists(sample_json):
        print(f"Converting {sample_json} -> {sample_svg}...")
        convert_gt_to_svg(sample_dxf, sample_json, sample_svg)
        print("Conversion complete!")
    else:
        print("💡 Tip: This is a standalone module. Provide valid DXF and JSON file paths for testing.")
