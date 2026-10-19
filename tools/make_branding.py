"""Rebuild exact vector branding and desktop icon assets."""
from pathlib import Path
import cairosvg
from PIL import Image
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'imagecraft/ui/assets'
ASSETS.mkdir(parents=True, exist_ok=True)
MARK = '''<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256"><rect x="8" y="8" width="240" height="240" rx="54" fill="#122333"/><path d="M62 100V66h34M160 66h34v34M194 156v34h-34M96 190H62v-34" fill="none" stroke="#2dd4bf" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/><path d="M78 128q50-64 100 0-50 64-100 0Z" fill="none" stroke="#f0f6fa" stroke-width="9"/><circle cx="128" cy="128" r="18" fill="#2dd4bf"/><circle cx="128" cy="128" r="7" fill="#122333"/></svg>'''
(ASSETS/'visiondb-craft-mark.svg').write_text(MARK)
LOGO = '''<svg xmlns="http://www.w3.org/2000/svg" width="720" height="176" viewBox="0 0 720 176"><svg x="0" y="0" width="176" height="176" viewBox="0 0 256 256">'''+MARK.split('viewBox="0 0 256 256">')[1].removesuffix('</svg>')+'''</svg><text x="200" y="86" font-family="DejaVu Sans,Arial,sans-serif" font-size="52" font-weight="700" fill="#f0f6fa">VisionDB</text><text x="202" y="137" font-family="DejaVu Sans,Arial,sans-serif" font-size="35" letter-spacing="8" fill="#2dd4bf">CRAFT</text></svg>'''
(ASSETS/'visiondb-craft-logo.svg').write_text(LOGO)
cairosvg.svg2png(bytestring=MARK.encode(),write_to=str(ASSETS/'visiondb-craft.png'),output_width=1024,output_height=1024)
cairosvg.svg2png(bytestring=LOGO.encode(),write_to=str(ASSETS/'visiondb-craft-logo.png'),output_width=1440,output_height=352)
im=Image.open(ASSETS/'visiondb-craft.png'); im.save(ASSETS/'visiondb-craft.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
old=ASSETS/'ImageCraft.ico'
if old.exists():old.unlink()
