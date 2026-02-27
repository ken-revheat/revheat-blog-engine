"""Image Pipeline — generates branded data visualizations, quote cards, and framework diagrams."""

import io
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv(override=True)

log = logging.getLogger(__name__)


@dataclass
class ImageResult:
    path: str
    alt_text: str
    caption: str
    width: int
    height: int
    format: str  # "png" or "webp"


class ImagePipeline:
    """Generates branded data visualizations for RevHeat blog posts."""

    def __init__(self, brand_config_path="assets/brand/colors.yaml"):
        self.brand = self._load_brand_config(brand_config_path)
        self.output_dir = "output/images"
        os.makedirs(self.output_dir, exist_ok=True)

        # ShortPixel API
        self.shortpixel_key = os.getenv("SHORTPIXEL_API_KEY", "")

        # Try to set up matplotlib with brand styling
        self._setup_matplotlib()
        log.info("ImagePipeline initialized")

    def _load_brand_config(self, path: str) -> dict:
        if os.path.exists(path):
            with open(path) as f:
                return yaml.safe_load(f)
        # Defaults — match revheat.com brand
        return {
            "colors": {
                "primary": "#3b4fe4",
                "secondary": "#243673",
                "accent": "#6e7180",
                "background": "#ffffff",
                "text_dark": "#1a1a1a",
                "text_light": "#ffffff",
                "chart_colors": ["#3b4fe4", "#243673", "#2A9D8F", "#E9C46A", "#1a1a1a"],
            },
            "typography": {
                "heading_font": "Poppins",
                "body_font": "Open Sans",
                "data_font": "Roboto Mono",
            },
            "dimensions": {
                "featured_image": {"width": 1200, "height": 627},
                "square": {"width": 1080, "height": 1080},
                "chart": {"width": 800, "height": 500},
                "infographic": {"width": 800, "height": 1200},
            },
        }

    def _setup_matplotlib(self):
        """Configure matplotlib with brand styling."""
        try:
            import matplotlib
            matplotlib.use("Agg")  # Non-interactive backend
            import matplotlib.pyplot as plt

            colors = self.brand["colors"]
            plt.rcParams.update({
                "figure.facecolor": colors.get("background", "#F1FAEE"),
                "axes.facecolor": colors.get("background", "#F1FAEE"),
                "axes.edgecolor": colors.get("secondary", "#1D3557"),
                "axes.labelcolor": colors.get("text_dark", "#1D3557"),
                "text.color": colors.get("text_dark", "#1D3557"),
                "xtick.color": colors.get("text_dark", "#1D3557"),
                "ytick.color": colors.get("text_dark", "#1D3557"),
                "axes.prop_cycle": plt.cycler(
                    "color", colors.get("chart_colors", ["#E63946"])
                ),
                "figure.dpi": 150,
                "savefig.dpi": 300,
                "savefig.bbox": "tight",
            })
            self._mpl_available = True
        except ImportError:
            self._mpl_available = False
            log.warning("matplotlib not available, chart generation disabled")

    def _hex_to_rgb(self, hex_color: str) -> tuple:
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        """Try to load a TTF font, searching platform-specific paths."""
        import platform

        if bold:
            font_names = ["Montserrat-Bold.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf"]
        else:
            font_names = ["OpenSans-Regular.ttf", "DejaVuSans.ttf", "Arial.ttf", "LiberationSans-Regular.ttf"]

        # Platform-specific font directories
        font_dirs = [
            os.path.join(self.output_dir, "..", "fonts"),  # Bundled fonts
            os.path.join(os.path.dirname(__file__), "..", "assets", "fonts"),
        ]
        if platform.system() == "Darwin":
            font_dirs.extend([
                "/System/Library/Fonts",
                "/Library/Fonts",
                os.path.expanduser("~/Library/Fonts"),
            ])
        elif platform.system() == "Linux":
            font_dirs.extend([
                "/usr/share/fonts/truetype/dejavu",
                "/usr/share/fonts/truetype/liberation",
                "/usr/share/fonts/liberation-sans",      # Amazon Linux 2023
                "/usr/share/fonts/liberation-mono",
                "/usr/share/fonts/google-noto-sans",
                "/usr/share/fonts/dejavu-sans-fonts",
                "/usr/share/fonts/TTF",
                "/usr/share/fonts",
            ])

        for font_dir in font_dirs:
            for name in font_names:
                path = os.path.join(font_dir, name)
                try:
                    return ImageFont.truetype(path, size)
                except (OSError, IOError):
                    continue

        # Try font names directly (relies on system font config / fontconfig)
        for name in font_names:
            try:
                return ImageFont.truetype(name, size)
            except (OSError, IOError):
                continue

        # Last resort — macOS Helvetica or Pillow default
        for fallback in ["/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
            try:
                return ImageFont.truetype(fallback, size)
            except (OSError, IOError):
                continue

        log.warning(f"No TrueType font found, using Pillow default (size={size}, bold={bold})")
        return ImageFont.load_default()

    def generate_data_chart(self, data: dict, chart_type: str, title: str, subtitle: str = "") -> ImageResult:
        """Generate a branded data chart using matplotlib."""
        if not self._mpl_available:
            return self._generate_chart_fallback(data, chart_type, title, subtitle)

        import matplotlib.pyplot as plt

        colors = self.brand["colors"]
        chart_colors = colors.get("chart_colors", ["#E63946", "#457B9D", "#2A9D8F"])
        dims = self.brand["dimensions"]["chart"]
        w_inches = dims["width"] / 100
        h_inches = dims["height"] / 100

        fig, ax = plt.subplots(figsize=(w_inches, h_inches))

        labels = data.get("labels", [])
        values = data.get("values", [])
        unit = data.get("unit", "")
        highlight_idx = data.get("highlight_index")

        bar_colors = [chart_colors[i % len(chart_colors)] for i in range(len(labels))]
        if highlight_idx is not None and 0 <= highlight_idx < len(bar_colors):
            bar_colors[highlight_idx] = colors.get("primary", "#E63946")

        if chart_type in ("bar", "comparison_bar"):
            bars = ax.barh(labels, values, color=bar_colors, edgecolor="white", linewidth=0.5)
            for bar, val in zip(bars, values):
                ax.text(
                    bar.get_width() + max(values) * 0.02,
                    bar.get_y() + bar.get_height() / 2,
                    f"{val}{unit}",
                    va="center",
                    fontsize=10,
                    fontweight="bold",
                    color=colors.get("text_dark", "#1D3557"),
                )
            ax.set_xlabel("")
            ax.invert_yaxis()

        elif chart_type == "line":
            ax.plot(labels, values, color=colors.get("primary", "#E63946"), linewidth=2, marker="o", markersize=8)
            for i, (x, y) in enumerate(zip(labels, values)):
                ax.annotate(f"{y}{unit}", (x, y), textcoords="offset points", xytext=(0, 10), ha="center", fontsize=9)

        elif chart_type == "donut":
            wedges, texts = ax.pie(
                values, labels=labels, colors=bar_colors,
                startangle=90, wedgeprops={"width": 0.4, "edgecolor": "white"},
            )
            if values:
                center_val = data.get("center_stat", f"{values[0]}{unit}")
                ax.text(0, 0, str(center_val), ha="center", va="center", fontsize=20, fontweight="bold")

        elif chart_type == "benchmark":
            bars = ax.barh(labels, values, color=bar_colors, edgecolor="white")
            for bar, val in zip(bars, values):
                ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2, f"{val}{unit}", va="center", fontsize=10, fontweight="bold")
            ax.invert_yaxis()

        else:  # table_graphic or fallback
            ax.bar(labels, values, color=bar_colors, edgecolor="white")
            for i, val in enumerate(values):
                ax.text(i, val + max(values) * 0.02, f"{val}{unit}", ha="center", fontsize=10, fontweight="bold")

        ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
        if subtitle:
            ax.text(
                0.5, 1.02, subtitle,
                transform=ax.transAxes, ha="center", fontsize=9,
                color=colors.get("accent", "#457B9D"), style="italic",
            )

        # Source line
        fig.text(
            0.5, 0.01, "Source: RevHeat Research — 33,000+ companies",
            ha="center", fontsize=7, color=colors.get("accent", "#457B9D"),
        )

        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        # Save
        slug = title.lower().replace(" ", "-")[:40]
        filename = f"chart-{slug}.png"
        filepath = os.path.join(self.output_dir, filename)
        fig.savefig(filepath, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)

        alt_text = self.generate_alt_text({
            "chart_title": title,
            "data_summary": ", ".join(f"{l}: {v}{unit}" for l, v in zip(labels, values)),
            "post_topic": title,
            "source": "RevHeat Research — 33,000+ companies",
        })

        img = Image.open(filepath)
        return ImageResult(
            path=filepath,
            alt_text=alt_text,
            caption=f"{title}. {subtitle}" if subtitle else title,
            width=img.width,
            height=img.height,
            format="png",
        )

    def _generate_chart_fallback(self, data, chart_type, title, subtitle) -> ImageResult:
        """Generate a simple chart using Pillow when matplotlib is unavailable."""
        dims = self.brand["dimensions"]["chart"]
        colors = self.brand["colors"]
        w, h = dims["width"] * 2, dims["height"] * 2  # Retina

        bg = self._hex_to_rgb(colors.get("background", "#F1FAEE"))
        primary = self._hex_to_rgb(colors.get("primary", "#E63946"))
        text_color = self._hex_to_rgb(colors.get("text_dark", "#1D3557"))

        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)
        font_title = self._get_font(36, bold=True)
        font_body = self._get_font(24)

        # Title
        draw.text((w // 2, 40), title, fill=text_color, font=font_title, anchor="mt")
        if subtitle:
            draw.text((w // 2, 90), subtitle, fill=self._hex_to_rgb(colors.get("accent", "#457B9D")), font=font_body, anchor="mt")

        # Simple bar rendering
        labels = data.get("labels", [])
        values = data.get("values", [])
        unit = data.get("unit", "")
        if labels and values:
            max_val = max(values) if values else 1
            bar_area_top = 160
            bar_height = 50
            bar_spacing = 20
            max_bar_width = w - 400

            chart_colors_hex = colors.get("chart_colors", ["#E63946"])
            for i, (label, val) in enumerate(zip(labels, values)):
                y = bar_area_top + i * (bar_height + bar_spacing)
                bar_w = int((val / max_val) * max_bar_width) if max_val > 0 else 0
                c = self._hex_to_rgb(chart_colors_hex[i % len(chart_colors_hex)])

                draw.text((20, y + bar_height // 2), label, fill=text_color, font=font_body, anchor="lm")
                draw.rectangle([300, y, 300 + bar_w, y + bar_height], fill=c)
                draw.text((310 + bar_w, y + bar_height // 2), f"{val}{unit}", fill=text_color, font=font_body, anchor="lm")

        # Source line
        source_font = self._get_font(16)
        draw.text((w // 2, h - 30), "Source: RevHeat Research — 33,000+ companies", fill=self._hex_to_rgb(colors.get("accent", "#457B9D")), font=source_font, anchor="mb")

        slug = title.lower().replace(" ", "-")[:40]
        filename = f"chart-{slug}.png"
        filepath = os.path.join(self.output_dir, filename)
        img.save(filepath, "PNG")

        alt_text = self.generate_alt_text({
            "chart_title": title,
            "data_summary": ", ".join(f"{l}: {v}{unit}" for l, v in zip(labels, values)),
            "post_topic": title,
            "source": "RevHeat Research — 33,000+ companies",
        })

        return ImageResult(path=filepath, alt_text=alt_text, caption=title, width=img.width, height=img.height, format="png")

    def generate_quote_card(self, quote_text: str, author: str = "Ken Lundin") -> ImageResult:
        """Generate a branded quote card image."""
        colors = self.brand["colors"]
        dims = self.brand["dimensions"]["square"]
        w, h = dims["width"] * 2, dims["height"] * 2  # Retina

        navy = self._hex_to_rgb(colors.get("secondary", "#1D3557"))
        white = (255, 255, 255)
        red = self._hex_to_rgb(colors.get("primary", "#E63946"))

        img = Image.new("RGB", (w, h), navy)
        draw = ImageDraw.Draw(img)

        # Red accent bar at top
        draw.rectangle([0, 0, w, 16], fill=red)

        # Quote marks
        font_quote_mark = self._get_font(120, bold=True)
        draw.text((80, 200), "\u201c", fill=red, font=font_quote_mark)

        # Quote text (word-wrap)
        font_quote = self._get_font(48, bold=True)
        self._draw_wrapped_text(draw, quote_text, (120, 360), font_quote, white, max_width=w - 240)

        # Author
        font_author = self._get_font(32)
        draw.text((120, h - 250), f"— {author}", fill=self._hex_to_rgb(colors.get("accent", "#457B9D")), font=font_author)
        font_title = self._get_font(24)
        draw.text((120, h - 200), "Founder & CEO, RevHeat", fill=self._hex_to_rgb(colors.get("accent", "#457B9D")), font=font_title)

        # Red accent bar at bottom
        draw.rectangle([0, h - 16, w, h], fill=red)

        slug = quote_text[:30].lower().replace(" ", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
        filename = f"quote-{slug}.png"
        filepath = os.path.join(self.output_dir, filename)
        img.save(filepath, "PNG")

        return ImageResult(
            path=filepath,
            alt_text=f'Quote: "{quote_text}" — {author}',
            caption=f'"{quote_text}" — {author}',
            width=img.width,
            height=img.height,
            format="png",
        )

    def _draw_wrapped_text(self, draw, text, position, font, fill, max_width):
        """Draw text with word wrapping."""
        x, y = position
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        line_height = font.size + 10 if hasattr(font, "size") else 50
        for line in lines:
            draw.text((x, y), line, fill=fill, font=font)
            y += line_height

    def generate_comparison_graphic(self, before_data: dict, after_data: dict, title: str) -> ImageResult:
        """Generate a before/after comparison graphic."""
        colors = self.brand["colors"]
        dims = self.brand["dimensions"]["featured_image"]
        w, h = dims["width"] * 2, dims["height"] * 2

        bg = self._hex_to_rgb(colors.get("background", "#F1FAEE"))
        navy = self._hex_to_rgb(colors.get("secondary", "#1D3557"))
        red = self._hex_to_rgb(colors.get("primary", "#E63946"))
        teal = self._hex_to_rgb("#2A9D8F")
        white = (255, 255, 255)

        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)

        # Title
        font_title = self._get_font(40, bold=True)
        draw.text((w // 2, 60), title, fill=navy, font=font_title, anchor="mt")

        # Divider line
        mid_x = w // 2
        draw.line([(mid_x, 140), (mid_x, h - 80)], fill=navy, width=4)

        # Before side
        font_heading = self._get_font(36, bold=True)
        font_label = self._get_font(24)
        font_value = self._get_font(48, bold=True)

        draw.text((mid_x // 2, 160), "BEFORE", fill=red, font=font_heading, anchor="mt")
        y = 240
        for key, val in before_data.items():
            draw.text((mid_x // 2, y), key.replace("_", " ").title(), fill=navy, font=font_label, anchor="mt")
            draw.text((mid_x // 2, y + 40), str(val), fill=red, font=font_value, anchor="mt")
            y += 130

        # After side
        draw.text((mid_x + mid_x // 2, 160), "AFTER", fill=teal, font=font_heading, anchor="mt")
        y = 240
        for key, val in after_data.items():
            draw.text((mid_x + mid_x // 2, y), key.replace("_", " ").title(), fill=navy, font=font_label, anchor="mt")
            draw.text((mid_x + mid_x // 2, y + 40), str(val), fill=teal, font=font_value, anchor="mt")
            y += 130

        # Source
        font_source = self._get_font(18)
        draw.text((w // 2, h - 30), "Source: RevHeat Research", fill=self._hex_to_rgb(colors.get("accent", "#457B9D")), font=font_source, anchor="mb")

        filename = "comparison-" + title[:30].lower().replace(" ", "-") + ".png"
        filename = "".join(c for c in filename if c.isalnum() or c in "-.")
        filepath = os.path.join(self.output_dir, filename)
        img.save(filepath, "PNG")

        return ImageResult(
            path=filepath,
            alt_text=f"Before/after comparison: {title}",
            caption=title,
            width=img.width,
            height=img.height,
            format="png",
        )

    def generate_framework_diagram(self, framework_data: dict) -> ImageResult:
        """Generate a framework diagram showing pillar structure."""
        colors = self.brand["colors"]
        w, h = 1600, 1000

        bg = self._hex_to_rgb(colors.get("background", "#F1FAEE"))
        navy = self._hex_to_rgb(colors.get("secondary", "#1D3557"))
        white = (255, 255, 255)
        chart_colors_hex = colors.get("chart_colors", ["#E63946", "#457B9D", "#2A9D8F", "#E9C46A"])

        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)

        title = framework_data.get("title", "Framework")
        elements = framework_data.get("elements", [])

        font_title = self._get_font(36, bold=True)
        font_pillar = self._get_font(28, bold=True)
        font_sub = self._get_font(18)

        draw.text((w // 2, 40), title, fill=navy, font=font_title, anchor="mt")

        if elements:
            col_width = (w - 100) // len(elements)
            for i, elem in enumerate(elements):
                x_center = 50 + i * col_width + col_width // 2
                color = self._hex_to_rgb(chart_colors_hex[i % len(chart_colors_hex)])

                # Pillar box
                box_w, box_h = col_width - 40, 80
                x1 = x_center - box_w // 2
                y1 = 120
                draw.rounded_rectangle([x1, y1, x1 + box_w, y1 + box_h], radius=10, fill=color)
                draw.text((x_center, y1 + box_h // 2), elem["name"], fill=white, font=font_pillar, anchor="mm")

                # Sub-elements
                subs = elem.get("sub", [])
                for j, sub in enumerate(subs):
                    sy = y1 + box_h + 30 + j * 60
                    sub_box_h = 45
                    draw.rounded_rectangle(
                        [x1 + 10, sy, x1 + box_w - 10, sy + sub_box_h],
                        radius=8, fill=white, outline=color, width=2,
                    )
                    draw.text((x_center, sy + sub_box_h // 2), sub, fill=navy, font=font_sub, anchor="mm")

        filename = "framework-diagram.png"
        filepath = os.path.join(self.output_dir, filename)
        img.save(filepath, "PNG")

        return ImageResult(
            path=filepath,
            alt_text=f"Diagram: {title}",
            caption=title,
            width=img.width,
            height=img.height,
            format="png",
        )

    def generate_featured_image(self, title: str, subtitle: str = "", pillar: str = "") -> ImageResult:
        """Generate a clean branded hero image for use as WordPress featured image.

        This creates a simple, professional banner that looks good in the
        WordPress header area — no data charts, no raw markdown, just the
        title on a branded background with a subtle accent bar.
        """
        colors = self.brand["colors"]
        dims = self.brand["dimensions"]["featured_image"]
        w, h = dims["width"] * 2, dims["height"] * 2  # 2400 × 1254

        # Pillar-specific accent colors
        pillar_colors = {
            "people": "#E63946",      # Red
            "performance": "#2A9D8F", # Teal
            "process": "#457B9D",     # Steel blue
            "strategy": "#E9C46A",    # Gold
        }
        accent_hex = pillar_colors.get(pillar.lower(), colors.get("primary", "#E63946"))

        navy = self._hex_to_rgb(colors.get("secondary", "#1D3557"))
        white = (255, 255, 255)
        accent = self._hex_to_rgb(accent_hex)

        img = Image.new("RGB", (w, h), navy)
        draw = ImageDraw.Draw(img)

        # Accent bar at top
        draw.rectangle([(0, 0), (w, 12)], fill=accent)

        # Accent bar at bottom
        draw.rectangle([(0, h - 12), (w, h)], fill=accent)

        # Subtle diagonal accent stripe (background texture)
        for offset in range(-h, w, 300):
            draw.line(
                [(offset, h), (offset + h, 0)],
                fill=(*accent, 30) if len(accent) == 3 else accent,
                width=1,
            )

        # Title text — large and centered
        font_title = self._get_font(72, bold=True)
        # Wrap long titles
        self._draw_wrapped_text(draw, title, (120, h // 2 - 120), font_title, white, max_width=w - 240)

        # Subtitle
        if subtitle:
            font_sub = self._get_font(36)
            draw.text((120, h - 200), subtitle, fill=accent, font=font_sub)

        # RevHeat branding — bottom right
        font_brand = self._get_font(28, bold=True)
        draw.text((w - 60, h - 60), "REVHEAT", fill=accent, font=font_brand, anchor="rb")

        # Save
        slug = title[:40].lower().replace(" ", "-")
        filename = "featured-" + "".join(c for c in slug if c.isalnum() or c in "-.") + ".png"
        filepath = os.path.join(self.output_dir, filename)
        img.save(filepath, "PNG")

        return ImageResult(
            path=filepath,
            alt_text=title,
            caption=f"{title} — RevHeat",
            width=img.width,
            height=img.height,
            format="png",
        )

    def apply_brand_template(self, image_path: str, template_type: str = "chart") -> str:
        """Apply brand watermark and border to an image."""
        colors = self.brand["colors"]
        border_color = self._hex_to_rgb(colors.get("primary", "#E63946"))
        border_width = 4

        img = Image.open(image_path).convert("RGBA")

        # Add border
        bordered = Image.new("RGBA", (img.width + border_width * 2, img.height + border_width * 2), border_color + (255,))
        bordered.paste(img, (border_width, border_width))

        # Resize to target dimensions if needed
        dims = self.brand["dimensions"].get(template_type, {})
        if dims:
            target_w = dims.get("width", bordered.width)
            target_h = dims.get("height", bordered.height)
            if bordered.width != target_w or bordered.height != target_h:
                bordered = bordered.resize((target_w, target_h), Image.LANCZOS)

        output_path = image_path.rsplit(".", 1)[0] + "-branded.png"
        bordered.convert("RGB").save(output_path, "PNG")
        return output_path

    def compress_image(self, image_path: str) -> str:
        """Compress image via ShortPixel API or local Pillow fallback."""
        if self.shortpixel_key:
            try:
                return self._compress_shortpixel(image_path)
            except Exception as e:
                log.warning(f"ShortPixel compression failed, using fallback: {e}")

        return self._compress_pillow(image_path)

    def _compress_shortpixel(self, image_path: str) -> str:
        """Compress via ShortPixel API."""
        with open(image_path, "rb") as f:
            resp = requests.post(
                "https://api.shortpixel.com/v2/reducer.php",
                files={"file": f},
                data={
                    "key": self.shortpixel_key,
                    "lossy": 1,
                    "convertto": "+webp",
                    "resize": 0,
                },
                timeout=60,
            )

        if resp.status_code != 200:
            raise Exception(f"ShortPixel API HTTP error: {resp.status_code}")

        # ShortPixel may return 200 with a JSON error body instead of image bytes.
        # Real image data is always much larger than a few hundred bytes.
        content_type = resp.headers.get("Content-Type", "")

        # Check if the response is JSON (error payload)
        if "application/json" in content_type or "text/" in content_type:
            try:
                err = resp.json()
                err_msg = err if isinstance(err, str) else str(err)
            except Exception:
                err_msg = resp.text[:200]
            raise Exception(f"ShortPixel returned error: {err_msg}")

        # Sanity-check: a valid compressed image should be at least 1 KB
        if len(resp.content) < 1024:
            # Likely an error response disguised as binary — try to decode
            try:
                body_text = resp.content.decode("utf-8", errors="replace")
                raise Exception(f"ShortPixel returned suspiciously small response ({len(resp.content)} bytes): {body_text[:200]}")
            except UnicodeDecodeError:
                raise Exception(f"ShortPixel returned suspiciously small response ({len(resp.content)} bytes)")

        output_path = image_path.rsplit(".", 1)[0] + ".webp"
        with open(output_path, "wb") as f:
            f.write(resp.content)
        original_size = os.path.getsize(image_path)
        new_size = os.path.getsize(output_path)
        log.info(f"ShortPixel: {original_size} -> {new_size} ({100 - new_size*100//original_size}% reduction)")
        return output_path

    def _compress_pillow(self, image_path: str) -> str:
        """Compress using Pillow as fallback."""
        img = Image.open(image_path)
        output_path = image_path.rsplit(".", 1)[0] + ".webp"
        img.save(output_path, "WEBP", quality=85, method=6)
        log.info(f"Pillow compression: {image_path} -> {output_path}")
        return output_path

    def generate_alt_text(self, image_context: dict) -> str:
        """Generate descriptive alt text, max 125 characters."""
        title = image_context.get("chart_title", "")
        summary = image_context.get("data_summary", "")
        source = image_context.get("source", "RevHeat Research")

        alt = f"{title}"
        if summary:
            alt += f": {summary}"
        alt += f". {source}."

        # Truncate to 125 chars
        if len(alt) > 125:
            alt = alt[:122] + "..."
        return alt

    def extract_chart_data_from_draft(self, draft) -> dict:
        """Extract real data points from the draft's markdown comparison table."""
        import re

        content = getattr(draft, "content_markdown", "") or ""
        table_text = getattr(draft, "comparison_table", "") or ""

        # Try to parse the markdown comparison table first
        if table_text:
            rows = [r.strip() for r in table_text.strip().split("\n") if r.strip() and not r.strip().startswith("|--")]
            if len(rows) >= 3:  # header + separator + at least 1 data row
                # Remove separator row (|---|---|...)
                data_rows = [r for r in rows if not re.match(r"^\|[\s\-:]+\|$", r.replace("|", "| ").replace("-", "-"))]
                if len(data_rows) >= 2:
                    header_cells = [c.strip() for c in data_rows[0].split("|") if c.strip()]
                    labels = []
                    values = []
                    for row in data_rows[1:]:
                        cells = [c.strip() for c in row.split("|") if c.strip()]
                        if len(cells) >= 2:
                            labels.append(cells[0])
                            # Extract the numeric value from the last cell (most likely the key metric)
                            last_val = cells[-1] if len(cells) > 2 else cells[1]
                            num = re.search(r"([\d,.]+)", last_val)
                            if num:
                                try:
                                    values.append(float(num.group(1).replace(",", "")))
                                except ValueError:
                                    values.append(0)
                            else:
                                values.append(0)

                    if labels and values and any(v > 0 for v in values):
                        # Detect unit from the values
                        unit = ""
                        if "%" in table_text:
                            unit = "%"
                        elif "$" in table_text:
                            unit = ""  # dollar sign already in label typically

                        return {
                            "labels": labels,
                            "values": values,
                            "unit": unit,
                            "highlight_index": values.index(max(values)) if values else None,
                        }

        # Fallback: extract stat patterns from the content body
        stat_patterns = re.findall(
            r"(?:(\w[\w\s]{3,30}?)(?::\s*|—\s*|–\s*|-\s*))(\d+(?:\.\d+)?)\s*(%|x|\b)",
            content,
        )
        if len(stat_patterns) >= 3:
            labels = [m[0].strip() for m in stat_patterns[:5]]
            values = [float(m[1]) for m in stat_patterns[:5]]
            unit = stat_patterns[0][2] if stat_patterns[0][2] else ""
            return {
                "labels": labels,
                "values": values,
                "unit": unit,
                "highlight_index": values.index(max(values)) if values else None,
            }

        # Last resort: use title-specific generic data
        title = getattr(draft, "title", "").lower()
        if "hiring" in title or "talent" in title or "people" in title:
            return {"labels": ["Wrong Hires", "Adequate Hires", "Top Performers"], "values": [62, 28, 10], "unit": "%", "highlight_index": 2}
        elif "process" in title or "system" in title:
            return {"labels": ["No System", "Partial System", "Full System"], "values": [12, 35, 53], "unit": "% win rate", "highlight_index": 2}
        elif "metric" in title or "performance" in title or "revenue" in title:
            return {"labels": ["Bottom 25%", "Median", "Top 10%"], "values": [350, 650, 1200], "unit": "K/rep", "highlight_index": 2}
        else:
            return {"labels": ["Bottom 25%", "Median", "Top 10%"], "values": [12, 28, 47], "unit": "%", "highlight_index": 2}

    def extract_comparison_data_from_draft(self, draft) -> tuple[dict, dict]:
        """Extract before/after data from the draft's comparison table."""
        import re

        table_text = getattr(draft, "comparison_table", "") or ""
        if not table_text:
            return {"Approach": "Ad-hoc", "Results": "Inconsistent"}, {"Approach": "Systematic", "Results": "Predictable"}

        rows = [r.strip() for r in table_text.strip().split("\n") if r.strip()]
        # Filter separator rows
        data_rows = [r for r in rows if not re.match(r"^\|[\s\-:]+$", r)]

        if len(data_rows) >= 2:
            header_cells = [c.strip() for c in data_rows[0].split("|") if c.strip()]
            before_data = {}
            after_data = {}
            for row in data_rows[1:]:
                cells = [c.strip() for c in row.split("|") if c.strip()]
                if len(cells) >= 3:
                    metric = cells[0]
                    before_data[metric] = cells[1]
                    after_data[metric] = cells[-1]

            if before_data:
                return before_data, after_data

        return {"Approach": "Ad-hoc", "Results": "Inconsistent"}, {"Approach": "Systematic", "Results": "Predictable"}

    def full_pipeline(self, draft) -> list[ImageResult]:
        """Run the full image pipeline for a blog draft.

        IMPORTANT: results[0] becomes the WordPress featured image (hero banner).
        It must be a clean branded image, NOT a data chart.  Data charts and
        comparison graphics are in-content images only.
        """
        results = []

        # 1. Always generate a clean featured / hero image (results[0])
        pillar = getattr(draft, "smartscaling_pillar", "") or ""
        featured = self.generate_featured_image(
            title=getattr(draft, "title", "RevHeat"),
            subtitle=getattr(draft, "meta_description", "")[:100] if hasattr(draft, "meta_description") else "",
            pillar=pillar,
        )
        results.append(featured)

        # 2. Data chart — goes into the post body, not as featured image
        chart_data = self.extract_chart_data_from_draft(draft)
        chart = self.generate_data_chart(
            data=chart_data,
            chart_type="comparison_bar",
            title=getattr(draft, "title", "RevHeat Data Insight"),
            subtitle="Data from 33,000 companies — RevHeat Research",
        )
        results.append(chart)

        # 3. If comparison table exists, generate comparison graphic with real data
        if hasattr(draft, "comparison_table") and draft.comparison_table:
            before_data, after_data = self.extract_comparison_data_from_draft(draft)
            comparison = self.generate_comparison_graphic(
                before_data=before_data,
                after_data=after_data,
                title=getattr(draft, "title", "Comparison"),
            )
            results.append(comparison)

        # 4. If quotable line, generate quote card
        if hasattr(draft, "key_takeaway") and draft.key_takeaway:
            quote_text = draft.key_takeaway[:140]
            quote = self.generate_quote_card(quote_text)
            results.append(quote)

        # Compress all
        for result in results:
            try:
                compressed_path = self.compress_image(result.path)
                result.path = compressed_path
                result.format = "webp"
            except Exception as e:
                log.warning(f"Compression failed for {result.path}: {e}")

        log.info(f"Image pipeline complete: {len(results)} images generated")
        return results
