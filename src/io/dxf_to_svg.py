from locale import normalize

import os
import math
from pathlib import Path
from collections import Counter
import xml.etree.ElementTree as ET

from numpy import cross

try:
    import ezdxf
    from ezdxf import bbox
    from ezdxf import colors
    from ezdxf import path
except ImportError:  # pragma: no cover - optional runtime dependency
    ezdxf = None
    bbox = None
    colors = None
    path = None

from src.config.config import settings


def get_entity_color(entity, override_layer=None):
    """Get the entity color, supporting layer-override logic to handle block references."""
    if colors is None:
        return 0, 0, 0

    # Prefer TrueColor (24-bit)
    if entity.dxf.hasattr("true_color"):
        r, g, b = colors.aci2rgb(entity.dxf.true_color)
        return (r, g, b)

    # If ByLayer or ByBlock, read the final inherited color index
    color_index = entity.dxf.color
    if color_index in (0, 256):  # ByBlock or ByLayer
        try:
            # Prefer the override layer (i.e., the layer where the block lives) for color index lookup
            layer = override_layer if override_layer else entity.dxf.layer
            layer_obj = entity.doc.layers.get(layer)
            if layer_obj is not None:
                color_index = layer_obj.color
        except Exception:
            color_index = 7  # default white

    # Convert the AutoCAD color index to RGB
    r, g, b = colors.aci2rgb(color_index)

    # Brightness calculation
    brightness = (0.299 * r + 0.587 * g + 0.114 * b)

    # Visual optimization: invert white to black on white-background SVGs
    if (r, g, b) == (255, 255, 255):
        return 0, 0, 0

    # Darken overly bright colors
    if brightness > 200:
        factor = 0.5
        r, g, b = int(r * factor), int(g * factor), int(b * factor)

    return (r, g, b)


def convert_dxf_to_svg(dxf_path, svg_path):
    if ezdxf is None or bbox is None or path is None:
        raise ImportError("Missing ezdxf dependency, cannot convert DXF to SVG")

    # Read the DXF file
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    # Background color: white by default
    svg_bg_color = "#FFFFFF"

    # Count the entity types
    types = Counter(e.dxftype() for e in msp)
    for t, n in types.items():
        print(f"{t}: {n}")

    # Compute the bounding box
    ext = bbox.extents(msp)
    xmin, xmax = ext.extmin[0], ext.extmax[0]
    ymin, ymax = ext.extmin[1], ext.extmax[1]

    # Scale coordinates and flip the y-axis
    def scale_point(x, y):
        # Pick the smaller scale so the whole drawing fits
        sx = 140 / (xmax - xmin)
        sy = 140 / (ymax - ymin)
        s = min(sx, sy)
        # Compute the offset to center the drawing
        new_w = s * (xmax - xmin)
        new_h = s * (ymax - ymin)
        offset_x = (140 - new_w) / 2
        offset_y = (140 - new_h) / 2

        # Apply the transform + flip y
        x_new = offset_x + s * (x - xmin)
        y_new = 140 - (offset_y + s * (y - ymin))
        return x_new, y_new

    # Scale lengths
    def scale_length(length):
        # Pick the smaller scale so the whole drawing fits
        sx = 140 / (xmax - xmin)
        sy = 140 / (ymax - ymin)
        s = min(sx, sy)
        length = s * length
        return length

    # Create the SVG root element
    sx = 140 / (xmax - xmin)
    sy = 140 / (ymax - ymin)
    s = min(sx, sy)
    svg = ET.Element('svg', {"xmlns": "http://www.w3.org/2000/svg", "style": f"background-color:{svg_bg_color}", "scale":str(s)})

    # Collect objects by layer
    layer_groups = {}
    def get_layer_group(layer_name):
        if layer_name not in layer_groups:
            layer_groups[layer_name] = ET.SubElement(svg, 'g', id=layer_name)
        return layer_groups[layer_name]

    def process_entities(entities, override_layer=None):
        """Recursively process a collection of entities, deep-traversing block references."""
        for e in entities:
            # 1. Skip entities marked invisible (dynamic block visibility is usually controlled via this attribute)
            if e.dxf.hasattr('invisible') and e.dxf.invisible:
                continue

            # ==========================================================
            # [Fix 1]: compute current_layer upfront, giving the outer container layer absolute priority
            # ==========================================================
            current_layer = override_layer if override_layer else str(e.dxf.layer)

            # ==========================================================
            # [Fix 2]: check current_layer visibility to avoid killing entities whose underlying hard-coded layer is off
            # ==========================================================
            try:
                layer_obj = doc.layers.get(current_layer)
                if layer_obj is not None and (layer_obj.is_off() or layer_obj.is_frozen()):
                    continue
            except Exception:
                pass

            # --- Deep-traversal logic: handle INSERT entities ---
            if e.dxftype() == 'INSERT':
                try:
                    # ==========================================================
                    # [Fix 3]: pass current_layer down to prevent nested child blocks from resetting override_layer
                    # ==========================================================
                    process_entities(e.virtual_entities(), override_layer=current_layer)
                except Exception as ex:
                    print(f"  [-] Failed to explode block {e.dxf.name}: {ex}")
                continue

            # Handle dimension entities (auto-explode into lines, text, and arrows)
            elif e.dxftype() in ('DIMENSION', 'ARC_DIMENSION', 'LARGE_RADIAL_DIMENSION', 'LEADER', 'MULTILEADER'):
                try:
                    process_entities(e.virtual_entities(), override_layer=current_layer)
                except Exception as ex:
                    print(f"  [-] Failed to parse dimension {e.dxftype()}: {ex}")
                continue

            # Get the group for the entity's final layer
            g = get_layer_group(current_layer)
            rgb_r, rgb_g, rgb_b = get_entity_color(e, override_layer=current_layer)
            color_str = f"rgb({rgb_r},{rgb_g},{rgb_b})"
            common_attr = {"fill": "none", "stroke": color_str, "stroke-width": "0.1"}

            # ==========================================================
            # [New logic]: SVG coordinate de-duplication and degenerate-path prevention filter
            # ==========================================================
            def filter_consecutive_points(pts, tol=1e-4):
                """Filter consecutive duplicate or extremely close points to avoid degenerate M x,y L x,y paths."""
                if not pts: return []
                clean_pts = [pts[0]]
                for p in pts[1:]:
                    if abs(p[0] - clean_pts[-1][0]) > tol or abs(p[1] - clean_pts[-1][1]) > tol:
                        clean_pts.append(p)
                return clean_pts

            if e.dxftype() == 'LINE':
                x1, y1 = scale_point(e.dxf.start.x, e.dxf.start.y)
                x2, y2 = scale_point(e.dxf.end.x, e.dxf.end.y)
                # Raise the tolerance to 1e-4 to fully block invisible zero-length lines
                if abs(x1 - x2) > 1e-4 or abs(y1 - y2) > 1e-4:
                    d = f"M {x1:.4f},{y1:.4f} L {x2:.4f},{y2:.4f}"
                    ET.SubElement(g, 'path', d=d, **common_attr)

            elif e.dxftype() == 'LWPOLYLINE':
                try:
                    entity_path = path.make_path(e)
                    raw_points = list(entity_path.flattening(3.0))
                    # 1. Scale the point coordinates
                    scaled_pts = [scale_point(pt.x, pt.y) for pt in raw_points]
                    # 2. De-duplicate consecutive points
                    clean_pts = filter_consecutive_points(scaled_pts)

                    # 3. Only emit a path if at least 2 valid points remain after de-duplication
                    if len(clean_pts) >= 2:
                        d_path = f"M {clean_pts[0][0]:.4f},{clean_pts[0][1]:.4f}"
                        for p in clean_pts[1:]:
                            d_path += f" L {p[0]:.4f},{p[1]:.4f}"
                        if e.closed:
                            d_path += " Z"
                        ET.SubElement(g, 'path', d=d_path, **common_attr)
                except Exception as ex:
                    print(f"  [-] Failed to parse LWPOLYLINE: {ex}")

            elif e.dxftype() == 'SPLINE':
                try:
                    raw_points = list(e.flattening(3.0))
                    scaled_pts = [scale_point(pt.x, pt.y) for pt in raw_points]
                    clean_pts = filter_consecutive_points(scaled_pts)

                    if len(clean_pts) >= 2:
                        d_path = f"M {clean_pts[0][0]:.4f},{clean_pts[0][1]:.4f}"
                        for p in clean_pts[1:]:
                            d_path += f" L {p[0]:.4f},{p[1]:.4f}"
                        if hasattr(e, 'closed') and e.closed:
                            d_path += " Z"
                        ET.SubElement(g, 'path', d=d_path, **common_attr)
                except Exception as ex:
                    print(f"  [-] Failed to flatten SPLINE: {ex}")
                continue

            elif e.dxftype() == 'ARC':
                try:
                    p1_wcs = e.start_point
                    p2_wcs = e.end_point

                    x1, y1 = scale_point(p1_wcs.x, p1_wcs.y)
                    x2, y2 = scale_point(p2_wcs.x, p2_wcs.y)

                    r = scale_length(e.dxf.radius)

                    delta_angle = (e.dxf.end_angle - e.dxf.start_angle) % 360
                    large_arc = 1 if delta_angle > 180 else 0

                    sweep_flag = 1 if e.ocs().uz.z < 0 else 0

                    if abs(x1 - x2) > 1e-4 or abs(y1 - y2) > 1e-4:
                        d_path = f"M {x1:.4f},{y1:.4f} A {r:.4f},{r:.4f} 0 {large_arc} {sweep_flag} {x2:.4f},{y2:.4f}"
                        ET.SubElement(g, 'path', d=d_path, **common_attr)
                except Exception as ex:
                    print(f"  [-] Failed to parse ARC: {ex}")
                continue

            elif e.dxftype() == 'CIRCLE':
                wcs_center = e.ocs().to_wcs(e.dxf.center)
                cx, cy = scale_point(wcs_center.x, wcs_center.y)
                r = scale_length(e.dxf.radius)
                ET.SubElement(g, 'circle', cx=f"{cx:.4f}", cy=f"{cy:.4f}", r=f"{r:.4f}", **common_attr)
                continue

            elif e.dxftype() in ("TEXT", "MTEXT"):
                content = str(e.plain_text() if hasattr(e, 'plain_text') else e.dxf.text)

                if e.dxftype() == "TEXT":
                    wcs_insert = e.ocs().to_wcs(e.dxf.insert)
                else:
                    wcs_insert = e.dxf.insert

                x, y = scale_point(wcs_insert.x, wcs_insert.y)
                height = scale_length(getattr(e.dxf, 'height', getattr(e.dxf, 'char_height', 100)))

                rotation = getattr(e.dxf, 'rotation', 0)
                if e.ocs().uz.z < 0:
                    rotation = -rotation

                text_elem = ET.SubElement(g, 'text', {
                    'x': f"{x:.4f}", 'y': f"{y:.4f}", 'font-size': f"{height:.4f}",
                    'fill': color_str, 'transform': f'rotate({-rotation:.4f} {x:.4f} {y:.4f})'
                })
                text_elem.text = content
                continue

            elif e.dxftype() == "ELLIPSE":
                try:
                    is_full = abs(e.dxf.end_param - e.dxf.start_param) >= (2 * math.pi - 1e-6)

                    if is_full:
                        cx, cy = scale_point(e.dxf.center.x, e.dxf.center.y)
                        vx, vy = e.dxf.major_axis.x, e.dxf.major_axis.y

                        rx = scale_length(math.hypot(vx, vy))
                        ry = rx * e.dxf.ratio

                        svg_angle_deg = math.degrees(math.atan2(-vy, vx))

                        ellipse_attr = {
                            'cx': f"{cx:.4f}",
                            'cy': f"{cy:.4f}",
                            'rx': f"{rx:.4f}",
                            'ry': f"{ry:.4f}",
                            **common_attr
                        }

                        if abs(svg_angle_deg) > 1e-4:
                            ellipse_attr['transform'] = f"rotate({svg_angle_deg:.4f} {cx:.4f} {cy:.4f})"

                        ET.SubElement(g, 'ellipse', ellipse_attr)
                    else:
                        points = list(e.flattening(3.0))

                        if len(points) >= 2:
                            p0 = scale_point(points[0].x, points[0].y)
                            d_path = f"M {p0[0]:.4f},{p0[1]:.4f}"
                            for pt in points[1:]:
                                pn = scale_point(pt.x, pt.y)
                                d_path += f" L {pn[0]:.4f},{pn[1]:.4f}"

                            ET.SubElement(g, 'path', d=d_path, **common_attr)
                except Exception as ex:
                    print(f"  [-] Failed to parse ELLIPSE: {ex}")
                continue

    # Set the viewBox
    viewbox_width = 140
    viewbox_height = 140
    svg.attrib['viewBox'] = f"{0} {0} {viewbox_width} {viewbox_height}"

    # Start recursive processing of the whole drawing
    process_entities(msp)

    # Save the SVG file
    tree = ET.ElementTree(svg)
    write_svg_tree(tree, svg_path)


def write_svg_tree(tree, svg_path):
    output_path = Path(svg_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(tree, ET.ElementTree):
        tree.write(output_path, encoding="utf-8", xml_declaration=True)
    else:
        ET.ElementTree(tree).write(output_path, encoding="utf-8", xml_declaration=True)


def main():
    file_dir = ""
    dxf_dir = os.path.join(settings.dxf_dir, file_dir)
    svg_dir = os.path.join(settings.svg_dir, file_dir)

    os.makedirs(svg_dir, exist_ok=True)

    if not os.path.exists(dxf_dir):
        print(f"❌ Input folder not found: {dxf_dir}")
        return

    dxf_files = [f for f in os.listdir(dxf_dir) if f.lower().endswith('.dxf')]

    if not dxf_files:
        print(f"⚠️ No .dxf files found in {dxf_dir}.")
        return

    print(f"🚀 Starting batch conversion, found {len(dxf_files)} DXF files...\n")

    for idx, file_name in enumerate(dxf_files, 1):
        print(f"[{idx}/{len(dxf_files)}] 🔄 Processing: {file_name}")
        input_path = os.path.join(dxf_dir, file_name)
        base_name = os.path.splitext(file_name)[0]

        if hasattr(svg_dir, "joinpath"):
            output_path = svg_dir / f"{base_name}.svg"
        else:
            output_path = os.path.join(svg_dir, f"{base_name}.svg")

        # try:
        convert_dxf_to_svg(input_path, str(output_path))
        print(f"✅ Conversion successful: {output_path}\n")
        # except Exception as e:
        #     print(f"❌ Conversion failed {file_name}: {e}\n")

    print("🎉 Batch conversion complete!")


if __name__ == "__main__":
    main()