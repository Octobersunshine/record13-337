import os
import io
from flask import Flask, request, jsonify, send_file, render_template
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'}
FONT_FOLDER = 'fonts'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(FONT_FOLDER, exist_ok=True)

POSITION_MAP = {
    'top-left': (0, 0),
    'top-center': (1, 0),
    'top-right': (2, 0),
    'center-left': (0, 1),
    'center': (1, 1),
    'center-right': (2, 1),
    'bottom-left': (0, 2),
    'bottom-center': (1, 2),
    'bottom-right': (2, 2),
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_font_path():
    font_files = [f for f in os.listdir(FONT_FOLDER) if f.endswith(('.ttf', '.ttc', '.otf'))]
    if font_files:
        return os.path.join(FONT_FOLDER, font_files[0])
    return None

def calculate_position(img_width, img_height, text_width, text_height, position, margin=20):
    col, row = POSITION_MAP.get(position, (1, 2))
    
    x_positions = {
        0: margin,
        1: (img_width - text_width) // 2,
        2: img_width - text_width - margin,
    }
    y_positions = {
        0: margin,
        1: (img_height - text_height) // 2,
        2: img_height - text_height - margin,
    }
    
    return x_positions[col], y_positions[row]

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    return (255, 255, 255)

def rgb_to_luminance(r, g, b):
    return 0.299 * r + 0.587 * g + 0.114 * b

def get_region_luminance(img, x, y, width, height):
    x = max(0, x)
    y = max(0, y)
    width = min(width, img.width - x)
    height = min(height, img.height - y)
    
    if width <= 0 or height <= 0:
        return 128
    
    region = img.crop((x, y, x + width, y + height))
    region_rgb = region.convert('RGB')
    
    pixels = list(region_rgb.getdata())
    total_luminance = 0
    for r, g, b in pixels:
        total_luminance += rgb_to_luminance(r, g, b)
    
    return total_luminance / len(pixels)

def auto_select_color(background_luminance):
    if background_luminance < 128:
        return (255, 255, 255)
    else:
        return (0, 0, 0)

def get_contrast_color(base_luminance):
    if base_luminance < 128:
        return (255, 255, 255), (0, 0, 0)
    else:
        return (0, 0, 0), (255, 255, 255)

def add_text_watermark(img, text, position='bottom-right', font_size=36,
                       color='#FFFFFF', opacity=150, margin=20, angle=0,
                       auto_color=True, stroke=True, stroke_width=2):
    txt_layer = Image.new('RGBA', img.size, (255, 255, 255, 0))
    
    font_path = get_font_path()
    if font_path:
        try:
            font = ImageFont.truetype(font_path, font_size)
        except Exception:
            font = ImageFont.load_default()
    else:
        font = ImageFont.load_default()
    
    draw = ImageDraw.Draw(txt_layer)
    
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x, y = calculate_position(img.width, img.height, text_width, text_height, position, margin)
    
    sample_margin = max(margin - 5, 0)
    bg_luminance = get_region_luminance(
        img, x - sample_margin, y - sample_margin,
        text_width + sample_margin * 2, text_height + sample_margin * 2
    )
    
    if auto_color:
        text_rgb, stroke_rgb = get_contrast_color(bg_luminance)
    else:
        text_rgb = hex_to_rgb(color)
        stroke_rgb = (0, 0, 0) if bg_luminance >= 128 else (255, 255, 255)
    
    fill_color = (text_rgb[0], text_rgb[1], text_rgb[2], opacity)
    stroke_color = (stroke_rgb[0], stroke_rgb[1], stroke_rgb[2], opacity)
    
    if angle != 0:
        text_img = Image.new('RGBA', (text_width + 20, text_height + 20), (255, 255, 255, 0))
        text_draw = ImageDraw.Draw(text_img)
        
        tx, ty = 10, 10
        if stroke:
            for dx in range(-stroke_width, stroke_width + 1):
                for dy in range(-stroke_width, stroke_width + 1):
                    if dx != 0 or dy != 0:
                        text_draw.text((tx + dx, ty + dy), text, font=font, fill=stroke_color)
        text_draw.text((tx, ty), text, font=font, fill=fill_color)
        
        rotated_text = text_img.rotate(angle, expand=True, resample=Image.BICUBIC)
        
        rw, rh = rotated_text.size
        x, y = calculate_position(img.width, img.height, rw, rh, position, margin)
        txt_layer.paste(rotated_text, (x, y), rotated_text)
    else:
        if stroke:
            for dx in range(-stroke_width, stroke_width + 1):
                for dy in range(-stroke_width, stroke_width + 1):
                    if dx != 0 or dy != 0:
                        draw.text((x + dx, y + dy), text, font=font, fill=stroke_color)
        draw.text((x, y), text, font=font, fill=fill_color)
    
    return Image.alpha_composite(img, txt_layer)

def add_logo_watermark(img, logo_file, position='bottom-right',
                       logo_scale=20, logo_opacity=200, logo_margin=30, logo_angle=0):
    logo = Image.open(logo_file).convert('RGBA')
    
    target_width = int(img.width * logo_scale / 100)
    aspect_ratio = logo.height / logo.width
    target_height = int(target_width * aspect_ratio)
    
    logo = logo.resize((target_width, target_height), Image.LANCZOS)
    
    if logo_opacity < 255:
        alpha = logo.split()[3]
        alpha = alpha.point(lambda p: int(p * logo_opacity / 255))
        logo.putalpha(alpha)
    
    if logo_angle != 0:
        logo = logo.rotate(logo_angle, expand=True, resample=Image.BICUBIC)
    
    x, y = calculate_position(img.width, img.height, logo.width, logo.height, position, logo_margin)
    
    logo_layer = Image.new('RGBA', img.size, (255, 255, 255, 0))
    logo_layer.paste(logo, (x, y), logo)
    
    return Image.alpha_composite(img, logo_layer)

def process_watermark(image_file, text=None, logo_file=None,
                      text_position='bottom-right', font_size=36,
                      color='#FFFFFF', text_opacity=150, text_margin=20, text_angle=0,
                      auto_color=True, stroke=True, stroke_width=2,
                      logo_position='top-right', logo_scale=20,
                      logo_opacity=200, logo_margin=30, logo_angle=0):
    img = Image.open(image_file).convert('RGBA')
    
    if logo_file:
        img = add_logo_watermark(
            img, logo_file, logo_position,
            logo_scale, logo_opacity, logo_margin, logo_angle
        )
    
    if text and text.strip():
        img = add_text_watermark(
            img, text, text_position, font_size,
            color, text_opacity, text_margin, text_angle,
            auto_color, stroke, stroke_width
        )
    
    if not text and not logo_file:
        raise ValueError('至少需要提供文字水印或Logo水印')
    
    output = io.BytesIO()
    original_format = Image.open(image_file).format or 'PNG'
    image_file.seek(0)
    
    if original_format in ('JPEG', 'JPG'):
        img = img.convert('RGB')
        img.save(output, format='JPEG', quality=95)
        mimetype = 'image/jpeg'
    else:
        img.save(output, format='PNG')
        mimetype = 'image/png'
    
    output.seek(0)
    return output, mimetype

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/watermark', methods=['POST'])
def watermark_api():
    if 'image' not in request.files:
        return jsonify({'error': '未上传图片文件'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': '未选择文件'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': '不支持的文件格式，支持: png, jpg, jpeg, bmp, gif, webp'}), 400
    
    text = request.form.get('text', '')
    enable_text = request.form.get('enable_text', 'true').lower() == 'true'
    if enable_text and not text.strip():
        return jsonify({'error': '已启用文字水印但水印文字为空'}), 400
    
    enable_logo = request.form.get('enable_logo', 'false').lower() == 'true'
    logo_file = None
    if enable_logo:
        if 'logo' not in request.files or request.files['logo'].filename == '':
            return jsonify({'error': '已启用Logo水印但未上传Logo文件'}), 400
        logo_file = request.files['logo']
        if not allowed_file(logo_file.filename):
            return jsonify({'error': 'Logo文件格式不支持'}), 400
    
    if not enable_text and not enable_logo:
        return jsonify({'error': '请至少启用一种水印类型（文字或Logo）'}), 400
    
    text_position = request.form.get('text_position', 'bottom-right')
    if text_position not in POSITION_MAP:
        return jsonify({'error': '无效的文字位置参数'}), 400
    
    try:
        font_size = int(request.form.get('font_size', 36))
    except (ValueError, TypeError):
        font_size = 36
    
    color = request.form.get('color', '#FFFFFF')
    try:
        text_opacity = int(request.form.get('text_opacity', 150))
        text_opacity = max(0, min(255, text_opacity))
    except (ValueError, TypeError):
        text_opacity = 150
    
    try:
        text_margin = int(request.form.get('text_margin', 20))
        text_margin = max(0, text_margin)
    except (ValueError, TypeError):
        text_margin = 20
    
    try:
        text_angle = int(request.form.get('text_angle', 0))
    except (ValueError, TypeError):
        text_angle = 0
    
    auto_color = request.form.get('auto_color', 'true').lower() == 'true'
    stroke = request.form.get('stroke', 'true').lower() == 'true'
    
    try:
        stroke_width = int(request.form.get('stroke_width', 2))
        stroke_width = max(0, min(5, stroke_width))
    except (ValueError, TypeError):
        stroke_width = 2
    
    logo_position = request.form.get('logo_position', 'top-right')
    if logo_position not in POSITION_MAP:
        return jsonify({'error': '无效的Logo位置参数'}), 400
    
    try:
        logo_scale = int(request.form.get('logo_scale', 20))
        logo_scale = max(1, min(100, logo_scale))
    except (ValueError, TypeError):
        logo_scale = 20
    
    try:
        logo_opacity = int(request.form.get('logo_opacity', 200))
        logo_opacity = max(0, min(255, logo_opacity))
    except (ValueError, TypeError):
        logo_opacity = 200
    
    try:
        logo_margin = int(request.form.get('logo_margin', 30))
        logo_margin = max(0, logo_margin)
    except (ValueError, TypeError):
        logo_margin = 30
    
    try:
        logo_angle = int(request.form.get('logo_angle', 0))
    except (ValueError, TypeError):
        logo_angle = 0
    
    try:
        output, mimetype = process_watermark(
            file,
            text=text if enable_text else None,
            logo_file=logo_file if enable_logo else None,
            text_position=text_position,
            font_size=font_size,
            color=color,
            text_opacity=text_opacity,
            text_margin=text_margin,
            text_angle=text_angle,
            auto_color=auto_color,
            stroke=stroke,
            stroke_width=stroke_width,
            logo_position=logo_position,
            logo_scale=logo_scale,
            logo_opacity=logo_opacity,
            logo_margin=logo_margin,
            logo_angle=logo_angle
        )
    except Exception as e:
        return jsonify({'error': f'处理图片时出错: {str(e)}'}), 500
    
    download_name = f'watermarked_{os.path.splitext(file.filename)[0]}.png'
    return send_file(output, mimetype=mimetype, as_attachment=True, download_name=download_name)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
