"""
r_wordcloud - A Python port of R's wordcloud package by Ian Fellows.

Faithfully reproduces the Archimedean spiral layout and bounding-box collision
algorithm from https://github.com/ifellows/wordcloud, which gives R wordclouds
their distinctive organic, loosely-packed aesthetic.

Usage:
    from r_wordcloud import wordcloud
    
    # From word frequencies dict
    img = wordcloud({"python": 100, "data": 80, "analysis": 60, ...})
    img.save("cloud.png")
    
    # With RColorBrewer-style palettes
    img = wordcloud(freqs, palette="Dark2", scale=(4, 0.5), rot_per=0.1)
"""

import math
import random
from typing import Optional, Union
from PIL import Image, ImageDraw, ImageFont

# --- RColorBrewer palettes (subset of most useful ones) ---
BREWER_PALETTES = {
    # Qualitative
    "Dark2": ["#1B9E77", "#D95F02", "#7570B3", "#E7298A", "#66A61E", "#E6AB02", "#A6761D", "#666666"],
    "Set1": ["#E41A1C", "#377EB8", "#4DAF4A", "#984EA3", "#FF7F00", "#FFFF33", "#A65628", "#F781BF"],
    "Set2": ["#66C2A5", "#FC8D62", "#8DA0CB", "#E78AC3", "#A6D854", "#FFD92F", "#E5C494", "#B3B3B3"],
    "Set3": ["#8DD3C7", "#FFFFB3", "#BEBADA", "#FB8072", "#80B1D3", "#FDB462", "#B3DE69", "#FCCDE5"],
    "Accent": ["#7FC97F", "#BEAED4", "#FDC086", "#FFFF99", "#386CB0", "#F0027F", "#BF5B17", "#666666"],
    "Paired": ["#A6CEE3", "#1F78B4", "#B2DF8A", "#33A02C", "#FB9A99", "#E31A1C", "#FDBF6F", "#FF7F00"],
    "Pastel1": ["#FBB4AE", "#B3CDE3", "#CCEBC5", "#DECBE4", "#FED9A6", "#FFFFCC", "#E5D8BD", "#FDDAEC"],
    "Pastel2": ["#B3E2CD", "#FDCDAC", "#CBD5E8", "#F4CAE4", "#E6F5C9", "#FFF2AE", "#F1E2CC", "#CCCCCC"],
    # Sequential
    "Blues": ["#F7FBFF", "#DEEBF7", "#C6DBEF", "#9ECAE1", "#6BAED6", "#4292C6", "#2171B5", "#084594"],
    "Greens": ["#F7FCF5", "#E5F5E0", "#C7E9C0", "#A1D99B", "#74C476", "#41AB5D", "#238B45", "#005A32"],
    "Oranges": ["#FFF5EB", "#FEE6CE", "#FDD0A2", "#FDAE6B", "#FD8D3C", "#F16913", "#D94801", "#8C2D04"],
    "Reds": ["#FFF5F0", "#FEE0D2", "#FCBBA1", "#FC9272", "#FB6A4A", "#EF3B2C", "#CB181D", "#99000D"],
    "Purples": ["#FCFBFD", "#EFEDF5", "#DADAEB", "#BCBDDC", "#9E9AC8", "#807DBA", "#6A51A3", "#4A1486"],
    "Greys": ["#FFFFFF", "#F0F0F0", "#D9D9D9", "#BDBDBD", "#969696", "#737373", "#525252", "#252525"],
    "BuGn": ["#F7FCFD", "#E5F5F9", "#CCECE6", "#99D8C9", "#66C2A4", "#41AE76", "#238B45", "#005824"],
    "BuPu": ["#F7FCFD", "#E0ECF4", "#BFD3E6", "#9EBCDA", "#8C96C6", "#8C6BB1", "#88419D", "#6E016B"],
    "YlOrRd": ["#FFFFCC", "#FFEDA0", "#FED976", "#FEB24C", "#FD8D3C", "#FC4E2A", "#E31A1C", "#B10026"],
    "YlGnBu": ["#FFFFD9", "#EDF8B1", "#C7E9B4", "#7FCDBB", "#41B6C4", "#1D91C0", "#225EA8", "#0C2C84"],
    "RdYlGn": ["#D73027", "#F46D43", "#FDAE61", "#FEE08B", "#D9EF8B", "#A6D96A", "#66BD63", "#1A9850"],
    # Diverging
    "RdBu": ["#B2182B", "#D6604D", "#F4A582", "#FDDBC7", "#D1E5F0", "#92C5DE", "#4393C3", "#2166AC"],
    "Spectral": ["#D53E4F", "#F46D43", "#FDAE61", "#FEE08B", "#E6F598", "#ABDDA4", "#66C2A5", "#3288BD"],
}

# Characters with descenders (the R code's "mind your ps and qs")
TAILS = set("gjpqy")


def _has_tails(word: str) -> bool:
    return any(c in TAILS for c in word.lower())


def _get_palette_colors(palette: Union[str, list], skip_light: int = 2) -> list:
    """Get colors from a palette name or list.
    
    For sequential palettes, skip the lightest colors (they're invisible on white).
    This mirrors common R usage: pal <- brewer.pal(9, "BuGn"); pal <- pal[-(1:2)]
    """
    if isinstance(palette, list):
        return palette
    if palette in BREWER_PALETTES:
        colors = BREWER_PALETTES[palette]
        # For sequential palettes, skip lightest colors
        sequential = {"Blues", "Greens", "Oranges", "Reds", "Purples", "Greys",
                      "BuGn", "BuPu", "YlOrRd", "YlGnBu"}
        if palette in sequential and skip_light > 0:
            return colors[skip_light:]
        return colors
    # Fallback
    return ["#1B9E77", "#D95F02", "#7570B3", "#E7298A", "#66A61E", "#E6AB02"]


def _hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _measure_text(draw, word, font):
    """Measure text bounding box, returns (width, height).
    
    Uses textbbox which returns (left, top, right, bottom).
    Offsets can be non-zero (e.g. negative top for ascenders).
    """
    bbox = draw.textbbox((0, 0), word, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _get_text_offset(draw, word, font):
    """Get the (left, top) offset from textbbox — needed for precise drawing."""
    bbox = draw.textbbox((0, 0), word, font=font)
    return bbox[0], bbox[1]


def _is_overlap(x1, y1, w1, h1, boxes):
    """Check if box (x1, y1, w1, h1) overlaps any box in the list.
    
    Direct port of the C++ is_overlap from layout.cpp.
    """
    for (x2, y2, w2, h2) in boxes:
        if x1 < x2:
            ov_x = (x1 + w1) > x2
        else:
            ov_x = (x2 + w2) > x1
        
        if y1 < y2:
            ov = ov_x and ((y1 + h1) > y2)
        else:
            ov = ov_x and ((y2 + h2) > y1)
        
        if ov:
            return True
    return False


def wordcloud(
    frequencies: dict,
    width: int = 800,
    height: int = 800,
    scale: tuple = (4, 0.5),
    min_freq: int = 1,
    max_words: int = 200,
    random_order: bool = False,
    random_color: bool = False,
    rot_per: float = 0.1,
    palette: Union[str, list] = "Dark2",
    background_color: str = "#FFFFFF",
    font_path: Optional[str] = None,
    base_font_size: int = 16,
    theta_step: float = 0.1,
    r_step: float = 0.05,
    margin: int = 2,
    seed: Optional[int] = None,
) -> Image.Image:
    """Generate a word cloud image using the R wordcloud algorithm.
    
    Args:
        frequencies: Dict mapping words to their frequencies.
        width: Image width in pixels.
        height: Image height in pixels.  
        scale: Tuple of (max_cex, min_cex) controlling font size range.
            The R default is (4, 0.5). Higher first value = bigger max word.
        min_freq: Minimum frequency to include a word.
        max_words: Maximum number of words to display.
        random_order: If True, place words in random order; if False, by frequency.
        random_color: If True, assign colors randomly; if False, map to frequency.
        rot_per: Proportion of words to rotate 90 degrees (0.0 to 1.0).
        palette: Color palette name (RColorBrewer) or list of hex colors.
        background_color: Background color as hex string.
        font_path: Path to a .ttf/.otf font file. None = default.
        base_font_size: Base font size that gets multiplied by cex values.
        theta_step: Angular step for spiral (R default: 0.1).
        r_step: Radial step for spiral (R default: 0.05).
        margin: Pixel margin added around each word's bounding box.
        seed: Random seed for reproducibility.
        
    Returns:
        PIL Image object.
    """
    if seed is not None:
        random.seed(seed)
    
    # Get colors
    colors = _get_palette_colors(palette)
    nc = len(colors)
    rgb_colors = [_hex_to_rgb(c) for c in colors]
    
    # Filter and sort words
    words_freqs = [(w, f) for w, f in frequencies.items() if f >= min_freq]
    words_freqs.sort(key=lambda x: x[1], reverse=True)
    words_freqs = words_freqs[:max_words]
    
    if not words_freqs:
        img = Image.new("RGB", (width, height), background_color)
        return img
    
    # Order: by frequency (descending) or random
    if random_order:
        random.shuffle(words_freqs)
    # else: already sorted by frequency desc
    
    words = [w for w, f in words_freqs]
    freqs = [f for w, f in words_freqs]
    max_freq = max(freqs)
    normed_freq = [f / max_freq for f in freqs]
    
    # Compute cex (character expansion) sizes - maps frequency to font scale
    # size = (scale[0] - scale[1]) * normedFreq + scale[1]
    cex_values = [(scale[0] - scale[1]) * nf + scale[1] for nf in normed_freq]
    
    # Create image and drawing context
    img = Image.new("RGB", (width, height), background_color)
    draw = ImageDraw.Draw(img)
    
    # Load fonts at different sizes
    def get_font(cex):
        size = max(1, int(base_font_size * cex))
        try:
            if font_path:
                return ImageFont.truetype(font_path, size)
            else:
                return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
        except (OSError, IOError):
            try:
                return ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", size)
            except (OSError, IOError):
                return ImageFont.load_default()
    
    # Place words using Archimedean spiral
    # Working in normalized coordinates [0, 1] like R, then scale to pixels
    boxes = []  # List of (x, y, w, h) in normalized coords
    placed = []  # List of (word, x_px, y_px, font, rotated, color_rgb)
    
    for i, word in enumerate(words):
        cex = cex_values[i]
        font = get_font(cex)
        
        # Measure text in pixels, convert to normalized coords
        tw_px, th_px = _measure_text(draw, word, font)
        tw_px += margin * 2
        th_px += margin * 2
        
        # Descender compensation ("mind your ps and qs")
        if _has_tails(word):
            th_px = int(th_px + th_px * 0.2)
        
        # Normalized dimensions
        wid = tw_px / width
        ht = th_px / height
        
        # Handle rotation
        rot_word = random.random() < rot_per
        if rot_word:
            wid, ht = ht, wid
        
        # Spiral placement
        r = 0.0
        theta = random.uniform(0, 2 * math.pi)
        placed_ok = False
        
        while True:
            x1 = 0.5 + r * math.cos(theta)
            y1 = 0.5 + r * math.sin(theta)
            
            bx = x1 - 0.5 * wid
            by = y1 - 0.5 * ht
            
            # Check bounds and overlap
            if (bx > 0 and by > 0 and 
                bx + wid < 1 and by + ht < 1 and
                not _is_overlap(bx, by, wid, ht, boxes)):
                
                # Determine color
                if random_color:
                    cc = rgb_colors[random.randint(0, nc - 1)]
                else:
                    ci = min(int(math.ceil(nc * normed_freq[i])), nc) - 1
                    ci = max(0, ci)
                    # Reverse so that high frequency = first color in palette
                    cc = rgb_colors[nc - 1 - ci]
                
                # Convert to pixel coords
                px = int(x1 * width)
                py = int(y1 * height)
                
                placed.append((word, px, py, font, rot_word, cc))
                boxes.append((bx, by, wid, ht))
                placed_ok = True
                break
            
            # Spiral outward
            if r > math.sqrt(0.5):
                # Word doesn't fit
                break
            
            theta += theta_step
            r += r_step * theta_step / (2 * math.pi)
    
    # Render all placed words
    for (word, px, py, font, rotated, color) in placed:
        if rotated:
            # Create temporary image for rotated text with generous padding
            tw_px, th_px = _measure_text(draw, word, font)
            ox, oy = _get_text_offset(draw, word, font)
            pad = max(4, int(th_px * 0.3))  # generous padding for glyphs
            tmp_w = tw_px + pad * 2
            tmp_h = th_px + pad * 2
            txt_img = Image.new("RGBA", (tmp_w, tmp_h), (0, 0, 0, 0))
            txt_draw = ImageDraw.Draw(txt_img)
            txt_draw.text((pad - ox, pad - oy), word, font=font, fill=color + (255,))
            txt_img = txt_img.rotate(90, expand=True)
            # Paste centered at position
            paste_x = px - txt_img.width // 2
            paste_y = py - txt_img.height // 2
            img.paste(txt_img, (paste_x, paste_y), txt_img)
        else:
            tw_px, th_px = _measure_text(draw, word, font)
            ox, oy = _get_text_offset(draw, word, font)
            draw.text(
                (px - tw_px // 2 - ox, py - th_px // 2 - oy),
                word, font=font, fill=color
            )
    
    return img


# --- Convenience functions ---

def wordcloud_from_text(
    text: str,
    stopwords: Optional[set] = None,
    **kwargs
) -> Image.Image:
    """Generate a word cloud from raw text.
    
    Tokenizes, removes stopwords, counts frequencies, then calls wordcloud().
    """
    import re
    
    if stopwords is None:
        # Basic English stopwords
        stopwords = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "from", "is", "was", "are", "were",
            "be", "been", "being", "have", "has", "had", "do", "does", "did",
            "will", "would", "could", "should", "may", "might", "shall",
            "can", "need", "dare", "ought", "used", "it", "its", "this",
            "that", "these", "those", "i", "me", "my", "we", "our", "you",
            "your", "he", "him", "his", "she", "her", "they", "them", "their",
            "what", "which", "who", "whom", "where", "when", "how", "not",
            "no", "nor", "as", "if", "then", "than", "so", "just", "also",
            "about", "up", "out", "into", "over", "after", "before", "between",
            "through", "during", "all", "each", "every", "both", "few",
            "more", "most", "other", "some", "such", "only", "own", "same",
            "very", "s", "t", "will", "don", "now", "d", "m", "o", "re",
            "ve", "y", "ain", "aren", "couldn", "didn", "doesn", "hadn",
            "hasn", "haven", "isn", "ma", "mightn", "mustn", "needn",
            "shan", "shouldn", "wasn", "weren", "won", "wouldn",
        }
    
    # Tokenize
    words_raw = re.findall(r'[a-zA-Z]+', text.lower())
    words_filtered = [w for w in words_raw if w not in stopwords and len(w) > 1]
    
    # Count frequencies
    freq = {}
    for w in words_filtered:
        freq[w] = freq.get(w, 0) + 1
    
    return wordcloud(freq, **kwargs)


if __name__ == "__main__":
    # Demo: create a sample word cloud
    sample_freqs = {
        "Python": 100, "data": 85, "analysis": 70, "machine": 65,
        "learning": 60, "visualization": 55, "cloud": 50, "word": 48,
        "algorithm": 45, "spiral": 42, "beautiful": 40, "layout": 38,
        "frequency": 35, "color": 33, "palette": 30, "text": 28,
        "render": 25, "image": 23, "font": 22, "size": 20,
        "rotation": 18, "overlap": 17, "bounding": 15, "box": 14,
        "placement": 13, "organic": 12, "aesthetic": 11, "natural": 10,
        "spacing": 9, "RColorBrewer": 8, "Archimedean": 7, "collision": 6,
        "detection": 5, "port": 4, "faithful": 3,
    }
    
    img = wordcloud(
        sample_freqs,
        palette="Dark2",
        scale=(6, 0.8),
        rot_per=0.15,
        seed=42,
        width=1024,
        height=1024,
        base_font_size=18,
    )
    img.save("/home/claude/wordcloud_demo.png")
    print("Saved wordcloud_demo.png")
