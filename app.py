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

def add_watermark(image_file, text, position='bottom-right', font_size=36,
                  color='#FFFFFF', opacity=150, margin=20, angle=0):
    img = Image.open(image_file).convert('RGBA')
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
    
    rgb_color = hex_to_rgb(color)
    fill_color = (rgb_color[0], rgb_color[1], rgb_color[2], opacity)
    
    if angle != 0:
        text_img = Image.new('RGBA', (text_width + 20, text_height + 20), (255, 255, 255, 0))
        text_draw = ImageDraw.Draw(text_img)
        text_draw.text((10, 10), text, font=font, fill=fill_color)
        rotated_text = text_img.rotate(angle, expand=True, resample=Image.BICUBIC)
        
        rw, rh = rotated_text.size
        x, y = calculate_position(img.width, img.height, rw, rh, position, margin)
        txt_layer.paste(rotated_text, (x, y), rotated_text)
    else:
        draw.text((x, y), text, font=font, fill=fill_color)
    
    result = Image.alpha_composite(img, txt_layer)
    
    output = io.BytesIO()
    original_format = img.format if img.format else 'PNG'
    if original_format in ('JPEG', 'JPG'):
        result = result.convert('RGB')
        result.save(output, format='JPEG', quality=95)
        mimetype = 'image/jpeg'
    else:
        result.save(output, format='PNG')
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
    if not text:
        return jsonify({'error': '水印文字不能为空'}), 400
    
    position = request.form.get('position', 'bottom-right')
    if position not in POSITION_MAP:
        return jsonify({'error': '无效的位置参数'}), 400
    
    try:
        font_size = int(request.form.get('font_size', 36))
    except (ValueError, TypeError):
        font_size = 36
    
    color = request.form.get('color', '#FFFFFF')
    try:
        opacity = int(request.form.get('opacity', 150))
        opacity = max(0, min(255, opacity))
    except (ValueError, TypeError):
        opacity = 150
    
    try:
        margin = int(request.form.get('margin', 20))
        margin = max(0, margin)
    except (ValueError, TypeError):
        margin = 20
    
    try:
        angle = int(request.form.get('angle', 0))
    except (ValueError, TypeError):
        angle = 0
    
    try:
        output, mimetype = add_watermark(
            file, text, position, font_size, color, opacity, margin, angle
        )
    except Exception as e:
        return jsonify({'error': f'处理图片时出错: {str(e)}'}), 500
    
    download_name = f'watermarked_{os.path.splitext(file.filename)[0]}.png'
    return send_file(output, mimetype=mimetype, as_attachment=True, download_name=download_name)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
