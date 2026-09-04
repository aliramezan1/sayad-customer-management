# -*- coding: utf-8 -*-
import os
from PIL import Image, ImageDraw

for base_dir in ['app/static/icons', 'docs/icons']:
    os.makedirs(base_dir, exist_ok=True)

    size = 512
    img = Image.new('RGBA', (size, size), color=(11, 15, 25, 255))
    draw = ImageDraw.Draw(img)

    # Background gradient approximation
    for r in range(256, 0, -2):
        alpha = int(255 * (1 - (r / 256) * 0.4))
        color = (15 + int((256 - r) * 0.1), 23 + int((256 - r) * 0.2), 42 + int((256 - r) * 0.3), alpha)
        draw.ellipse([size/2 - r, size/2 - r, size/2 + r, size/2 + r], fill=color)

    # Outer circle stroke in emerald
    draw.ellipse([32, 32, size - 32, size - 32], outline=(16, 185, 129, 220), width=8)
    draw.ellipse([44, 44, size - 44, size - 44], outline=(59, 130, 246, 150), width=4)

    # Inner shield
    shield_pts = [
        (256, 90),
        (400, 140),
        (400, 310),
        (256, 430),
        (112, 310),
        (112, 140)
    ]
    draw.polygon(shield_pts, fill=(30, 41, 59, 230), outline=(56, 189, 248, 255), width=6)

    # Checkmark inside shield
    draw.line([(180, 270), (235, 330), (345, 190)], fill=(52, 211, 153, 255), width=22)

    # Small gold star on top
    star_pts = [(256, 115), (263, 135), (285, 135), (267, 148), (274, 168), (256, 155), (238, 168), (245, 148), (227, 135), (249, 135)]
    draw.polygon(star_pts, fill=(251, 191, 36, 255))

    img.save(os.path.join(base_dir, 'icon-512.png'), 'PNG')
    img.save(os.path.join(base_dir, 'icon-maskable.png'), 'PNG')

    # 192x192
    img192 = img.resize((192, 192), Image.Resampling.LANCZOS)
    img192.save(os.path.join(base_dir, 'icon-192.png'), 'PNG')

    # SVG vector icon
    svg_content = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="100%" height="100%">
  <defs>
    <linearGradient id="bg-grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a"/>
      <stop offset="100%" stop-color="#020617"/>
    </linearGradient>
    <linearGradient id="shield-grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1e293b"/>
      <stop offset="100%" stop-color="#0f172a"/>
    </linearGradient>
    <linearGradient id="line-grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8"/>
      <stop offset="100%" stop-color="#10b981"/>
    </linearGradient>
  </defs>
  <rect width="512" height="512" rx="110" fill="url(#bg-grad)"/>
  <circle cx="256" cy="256" r="220" fill="none" stroke="#10b981" stroke-width="6" opacity="0.6"/>
  <polygon points="256,90 400,140 400,310 256,430 112,310 112,140" fill="url(#shield-grad)" stroke="#38bdf8" stroke-width="8" stroke-linejoin="round"/>
  <polyline points="180,270 235,330 345,190" fill="none" stroke="url(#line-grad)" stroke-width="26" stroke-linecap="round" stroke-linejoin="round"/>
  <polygon points="256,115 263,135 285,135 267,148 274,168 256,155 238,168 245,148 227,135 249,135" fill="#fbbf24"/>
</svg>"""
    with open(os.path.join(base_dir, 'icon.svg'), 'w', encoding='utf-8') as f:
        f.write(svg_content)

print('PWA icons created successfully!')
