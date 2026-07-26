#!/usr/bin/env python3
"""Generate a themed policy-rate SVG for the GitHub profile."""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import math
import re
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "policy-profile.config.json"
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


@dataclass
class Series:
    code: str
    label: str
    reference_area: str
    source_series: str
    values: list[tuple[str, float]]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def download_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "policy-profile-generator/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def coerce_rate(value: str) -> float | None:
    cleaned = value.strip()
    if not cleaned or cleaned == "NaN":
        return None
    try:
        result = float(cleaned)
    except ValueError:
        return None
    if math.isnan(result):
        return None
    return result


def read_policy_rates(config: dict[str, Any]) -> tuple[list[Series], str]:
    source = config["source"]
    raw_zip = download_bytes(source["url"])
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
        with archive.open(source["csv_member"]) as member:
            text = io.TextIOWrapper(member, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text)
            source_rows = {
                row["REF_AREA"]: row
                for row in reader
                if row.get("FREQ") == source.get("frequency", "M")
            }

    configured = config["chart"]["areas"]
    month_columns = [key for key in next(iter(source_rows.values())).keys() if MONTH_RE.match(key)]
    latest_source_month = ""
    series_list: list[Series] = []

    for area in configured:
        code = area["code"]
        if code not in source_rows:
            raise SystemExit(f"Configured area {code} not found in BIS source")
        row = source_rows[code]
        values: list[tuple[str, float]] = []
        for month in month_columns:
            rate = coerce_rate(row.get(month, ""))
            if rate is not None:
                values.append((month, rate))
                latest_source_month = max(latest_source_month, month)
        series_list.append(
            Series(
                code=code,
                label=area.get("label", code),
                reference_area=row.get("Reference area", code).strip(),
                source_series=row.get("Series", "").strip(),
                values=values,
            )
        )

    return series_list, latest_source_month


def compact_series(series_list: list[Series], months: int) -> list[Series]:
    all_months = sorted({month for series in series_list for month, _ in series.values})
    keep = set(all_months[-months:])
    compacted: list[Series] = []
    for series in series_list:
        compacted.append(
            Series(
                code=series.code,
                label=series.label,
                reference_area=series.reference_area,
                source_series=series.source_series,
                values=[item for item in series.values if item[0] in keep],
            )
        )
    return compacted


def cache_payload(config: dict[str, Any], series_list: list[Series], latest_source_month: str) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "name": config["source"]["name"],
            "url": config["source"]["url"],
            "latest_source_month": latest_source_month,
        },
        "chart": {
            "title": config["chart"]["title"],
            "subtitle": config["chart"]["subtitle"],
            "months": config["chart"]["months"],
        },
        "series": [
            {
                "code": series.code,
                "label": series.label,
                "reference_area": series.reference_area,
                "source_series": series.source_series,
                "latest": {
                    "month": series.values[-1][0] if series.values else None,
                    "value": series.values[-1][1] if series.values else None,
                },
                "values": [{"month": month, "value": value} for month, value in series.values],
            }
            for series in series_list
        ],
    }


def restore_series(payload: dict[str, Any]) -> tuple[list[Series], str]:
    series_list = []
    for item in payload["series"]:
        series_list.append(
            Series(
                code=item["code"],
                label=item["label"],
                reference_area=item["reference_area"],
                source_series=item.get("source_series", ""),
                values=[(point["month"], float(point["value"])) for point in item["values"]],
            )
        )
    latest = payload.get("source", {}).get("latest_source_month", "")
    return series_list, latest


def apply_config_labels(config: dict[str, Any], series_list: list[Series]) -> list[Series]:
    series_by_code = {series.code: series for series in series_list}
    relabeled: list[Series] = []
    for area in config["chart"]["areas"]:
        code = area["code"]
        if code not in series_by_code:
            raise SystemExit(f"Cached data missing configured area {code}; regenerate without --offline")
        series = series_by_code[code]
        relabeled.append(
            Series(
                code=series.code,
                label=area.get("label", series.label),
                reference_area=series.reference_area,
                source_series=series.source_series,
                values=series.values,
            )
        )
    return relabeled


def nice_tick_step(span: float) -> float:
    if span <= 1.0:
        return 0.25
    if span <= 2.0:
        return 0.5
    if span <= 5.0:
        return 1.0
    return 2.0


def month_label(month: str) -> str:
    year, month_num = month.split("-")
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{names[int(month_num) - 1]} {year}"


def svg_path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    head, *tail = points
    commands = [f"M {head[0]:.2f} {head[1]:.2f}"]
    commands.extend(f"L {x:.2f} {y:.2f}" for x, y in tail)
    return " ".join(commands)


def render_svg(
    config: dict[str, Any],
    series_list: list[Series],
    theme_name: str,
    latest_source_month: str,
) -> str:
    themes = config["themes"]
    if theme_name not in themes:
        raise SystemExit(f"Unknown theme {theme_name}. Available: {', '.join(sorted(themes))}")
    theme = themes[theme_name]
    width = 940
    height = 373
    margin = {"left": 50, "right": 146, "top": 52, "bottom": 62}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    months = sorted({month for series in series_list for month, _ in series.values})
    if not months:
        raise SystemExit("No values available to render")
    month_index = {month: index for index, month in enumerate(months)}
    rates = [value for series in series_list for _, value in series.values]
    min_rate = min(rates)
    max_rate = max(rates)
    y_min = min(0.0, math.floor(min_rate * 2) / 2)
    y_max = math.ceil(max_rate * 2) / 2
    if y_max == y_min:
        y_max += 1.0
    step = nice_tick_step(y_max - y_min)
    y_min = math.floor(y_min / step) * step
    y_max = math.ceil(y_max / step) * step

    def x_for(month: str) -> float:
        denominator = max(1, len(months) - 1)
        return margin["left"] + (month_index[month] / denominator) * plot_w

    def y_for(value: float) -> float:
        return margin["top"] + (y_max - value) / (y_max - y_min) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{html.escape(config["chart"]["title"])}</title>',
        f'<desc id="desc">{html.escape(config["chart"]["subtitle"])}. Source: {html.escape(config["source"]["name"])}.</desc>',
        "<style>",
        "text { font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }",
        ".title { font-size: 28px; font-weight: 700; letter-spacing: 0; }",
        ".subtitle { font-size: 12.5px; }",
        ".title-separator { font-size: 25px; font-weight: 400; }",
        ".axis { font-size: 12px; }",
        ".legend { font-size: 12px; font-weight: 650; }",
        ".latest { font-size: 11px; }",
        ".source { font-size: 10.5px; }",
        "</style>",
        f'<rect width="{width}" height="{height}" fill="{theme["background"]}"/>',
        f'<rect x="{margin["left"]}" y="{margin["top"]}" width="{plot_w}" height="{plot_h}" fill="{theme["plot_background"]}" stroke="{theme["grid"]}" stroke-width="1"/>',
        f'<text class="title" x="{margin["left"]}" y="30" fill="{theme["text"]}">{html.escape(config["chart"]["title"])}</text>',
    ]

    subtitle = config["chart"]["subtitle"]
    if "," in subtitle:
        subtitle_head, subtitle_tail = subtitle.split(",", 1)
        subtitle_lines = [f"{subtitle_head.strip()},", subtitle_tail.strip()]
    else:
        subtitle_lines = [subtitle]
    header_rule_x = 537
    header_detail_x = 553
    parts.append(f'<text class="title-separator" x="{header_rule_x}" y="31" fill="{theme["muted"]}">|</text>')
    for line_index, line in enumerate(subtitle_lines):
        parts.append(
            f'<text class="subtitle" x="{header_detail_x}" y="{19 + line_index * 17}" fill="{theme["muted"]}">{html.escape(line)}</text>'
        )

    y_tick = y_min
    while y_tick <= y_max + 1e-9:
        y = y_for(y_tick)
        parts.append(
            f'<line x1="{margin["left"]}" y1="{y:.2f}" x2="{margin["left"] + plot_w}" y2="{y:.2f}" stroke="{theme["grid"]}" stroke-width="1"/>'
        )
        parts.append(
            f'<text class="axis" x="{margin["left"] - 10}" y="{y + 4:.2f}" text-anchor="end" fill="{theme["muted"]}">{y_tick:g}</text>'
        )
        y_tick += step

    tick_months = [months[0]]
    tick_months.extend(month for month in months if month.endswith("-01") and month not in tick_months)
    for month in tick_months:
        x = x_for(month)
        parts.append(
            f'<line x1="{x:.2f}" y1="{margin["top"]}" x2="{x:.2f}" y2="{margin["top"] + plot_h}" stroke="{theme["grid"]}" stroke-width="1" opacity="0.55"/>'
        )
        label = month[:4] if month.endswith("-01") else month_label(month)
        parts.append(
            f'<text class="axis" x="{x:.2f}" y="{margin["top"] + plot_h + 25}" text-anchor="middle" fill="{theme["muted"]}">{html.escape(label)}</text>'
        )

    colors = theme["colors"]
    latest_rows = []
    for index, series in enumerate(series_list):
        color = colors[index % len(colors)]
        points = [(x_for(month), y_for(value)) for month, value in series.values]
        if len(points) < 2:
            continue
        parts.append(
            f'<path d="{svg_path(points)}" fill="none" stroke="{color}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>'
        )
        latest_month, latest_value = series.values[-1]
        latest_rows.append((series.label, series.reference_area, latest_month, latest_value, color))
        lx, ly = x_for(latest_month), y_for(latest_value)
        parts.append(f'<circle cx="{lx:.2f}" cy="{ly:.2f}" r="3.2" fill="{color}"/>')

    legend_x = margin["left"] + plot_w + 24
    legend_y = margin["top"] + 8
    parts.append(f'<text class="legend" x="{legend_x}" y="{legend_y}" fill="{theme["text"]}">Latest</text>')
    for row_index, (label, reference_area, latest_month, latest_value, color) in enumerate(latest_rows):
        y = legend_y + 24 + row_index * 32
        parts.append(f'<circle cx="{legend_x + 4}" cy="{y - 4}" r="4" fill="{color}"/>')
        parts.append(
            f'<text class="latest" x="{legend_x + 16}" y="{y - 8}" fill="{theme["text"]}">{html.escape(label)} {latest_value:g}%</text>'
        )
        parts.append(
            f'<text class="latest" x="{legend_x + 16}" y="{y + 7}" fill="{theme["muted"]}">{html.escape(reference_area)}</text>'
        )

    axis_label_x = 16
    axis_label_y = margin["top"] + plot_h / 2
    parts.append(
        f'<text class="axis" x="{axis_label_x}" y="{axis_label_y:.2f}" text-anchor="middle" dominant-baseline="middle" transform="rotate(-90 {axis_label_x} {axis_label_y:.2f})" fill="{theme["muted"]}">Rate (%)</text>'
    )

    source_text = f'Source: {config["source"]["name"]} | monthly data through {latest_source_month}'
    footer_y = height - 12
    parts.append(
        f'<text class="source" x="{margin["left"]}" y="{footer_y}" fill="{theme["muted"]}">{html.escape(source_text)}</text>'
    )
    credit = config.get("chart", {}).get("credit", {})
    credit_name = credit.get("name", "")
    credit_profile = credit.get("profile", "")
    credit_detail = credit.get("detail", "")
    credit_url = credit.get("url", "")
    credit_parts = [part for part in [f"Created by {credit_name}" if credit_name else "", credit_profile, credit_detail] if part]
    if credit_parts:
        credit_text = " | ".join(credit_parts)
        text_node = f'<text class="source" x="{width - 28}" y="{footer_y}" text-anchor="end" fill="{theme["muted"]}">{html.escape(credit_text)}</text>'
        if credit_url:
            parts.append(f'<a href="{html.escape(credit_url)}">{text_node}</a>')
        else:
            parts.append(text_node)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_preview(config: dict[str, Any], generated_svgs: list[tuple[str, Path]], output_path: Path) -> None:
    cards = []
    for theme_name, svg_path in generated_svgs:
        rel = svg_path.relative_to(output_path.parent)
        cards.append(
            f"""
      <section class="theme-card">
        <div class="theme-header">
          <h2>{html.escape(theme_name)}</h2>
          <code>{html.escape(str(rel))}</code>
        </div>
        <img src="{html.escape(str(rel))}" alt="Policy rates preview using {html.escape(theme_name)} theme">
      </section>"""
        )
    body = "\n".join(cards)
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Policy Rate Profile Preview</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f3f3ef;
      --text: #151515;
      --muted: #62625d;
      --card: #ffffff;
      --line: #d7d7cf;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      max-width: 1080px;
      margin: 0 auto;
      padding: 28px 20px 44px;
    }}
    header {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 18px;
    }}
    h1, h2, p {{ margin: 0; }}
    h1 {{ font-size: 28px; letter-spacing: 0; }}
    h2 {{ font-size: 14px; letter-spacing: 0; text-transform: uppercase; }}
    p, code {{ color: var(--muted); }}
    code {{ font-size: 12px; }}
    .theme-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      margin-top: 16px;
    }}
    .theme-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }}
    img {{
      display: block;
      width: 100%;
      height: auto;
      border: 1px solid var(--line);
      border-radius: 4px;
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Policy Rate Profile Preview</h1>
        <p>{html.escape(config["chart"]["title"])} / generated from {html.escape(config["source"]["name"])}</p>
      </div>
      <code>selected_theme: {html.escape(config["chart"]["selected_theme"])}</code>
    </header>
{body}
  </main>
</body>
</html>
"""
    write_text(output_path, html_doc)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate profile-ready policy-rate SVG assets.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to config JSON.")
    parser.add_argument("--theme", help="Theme name to render as main output.")
    parser.add_argument("--months", type=int, help="Number of months to keep.")
    parser.add_argument("--offline", action="store_true", help="Use cached data instead of downloading BIS data.")
    parser.add_argument("--preview-all", action="store_true", default=True, help="Render all theme previews.")
    parser.add_argument("--list-themes", action="store_true", help="List available themes and exit.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    config_path = Path(args.config).resolve()
    config = load_json(config_path)
    if args.list_themes:
        print("\n".join(sorted(config["themes"].keys())))
        return 0

    if args.theme:
        config["chart"]["selected_theme"] = args.theme
    if args.months:
        config["chart"]["months"] = args.months

    output = config["output"]
    cache_path = ROOT / output["cache"]
    if args.offline:
        payload = load_json(cache_path)
        series_list, latest_source_month = restore_series(payload)
    else:
        series_list, latest_source_month = read_policy_rates(config)
    series_list = compact_series(series_list, int(config["chart"]["months"]))
    series_list = apply_config_labels(config, series_list)
    if not args.offline:
        payload = cache_payload(config, series_list, latest_source_month)
        write_json(cache_path, payload)

    generated_at = payload.get("generated_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    metadata = {
        "generated_at": generated_at,
        "selected_theme": config["chart"]["selected_theme"],
        "latest_source_month": latest_source_month,
        "series": {
            series.code: {
                "label": series.label,
                "reference_area": series.reference_area,
                "latest_month": series.values[-1][0],
                "latest_value": series.values[-1][1],
                "observations": len(series.values),
            }
            for series in series_list
        },
    }
    write_json(ROOT / output["metadata"], metadata)

    main_theme = config["chart"]["selected_theme"]
    main_svg = render_svg(config, series_list, main_theme, latest_source_month)
    write_text(ROOT / output["svg"], main_svg)

    preview_dir = ROOT / output["preview_dir"]
    generated = []
    for theme_name in sorted(config["themes"]):
        svg = render_svg(config, series_list, theme_name, latest_source_month)
        path = preview_dir / f"policy-rates-{theme_name}.svg"
        write_text(path, svg)
        generated.append((theme_name, path))
    build_preview(config, generated, ROOT / output["preview"])

    print(
        json.dumps(
            {
                "svg": output["svg"],
                "preview": output["preview"],
                "cache": output["cache"],
                "theme": main_theme,
                "latest_source_month": latest_source_month,
                "series_count": len(series_list),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
