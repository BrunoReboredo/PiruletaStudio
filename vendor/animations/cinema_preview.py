"""Small live compositor for the fixed stadium movies, without a Blender render."""
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from . import cinema


class Preview:
    def __init__(self):
        self.capture = None
        self.path = None
        self.next_frame = -1
        self.assets = {}

    def close(self):
        if self.capture is not None:
            self.capture.release()
        self.capture = None
        self.path = None
        self.assets.clear()

    def frame(self, project, seconds, size=(960, 540)):
        path = project['video']
        if self.path != path:
            self.close()
            self.capture = cv2.VideoCapture(path)
            if not self.capture.isOpened():
                raise ValueError('No se puede abrir el vídeo incluido del estadio.')
            self.path = path
        fps = self.capture.get(cv2.CAP_PROP_FPS)
        index = min(round((seconds+float(project.get('trim_start', 0)))*fps), int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))-1)
        if index != self.next_frame:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, index))
        ok, frame = self.capture.read()
        if not ok:
            raise ValueError('No se puede leer este fotograma del estadio.')
        self.next_frame = index+1
        frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
        out = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32)
        for item in project['elements']:
            if not item.get('enabled', True) or not item['start'] <= seconds < item['end']:
                continue
            fade = item['fade']
            opacity = min(1, (seconds-item['start'])/fade, (item['end']-seconds)/fade) if fade else 1
            if opacity <= 0:
                continue
            if item['kind'] == 'image':
                source = Path(item['path'])
                if not source.is_file():
                    continue
                key = (str(source), source.stat().st_mtime_ns)
                if key not in self.assets:
                    with Image.open(source) as im:
                        im = im.convert('RGBA')
                        im.thumbnail((1024, 1024))
                        self.assets[key] = np.array(im)
            else:
                text = cinema.text_value(item['text'], project['variables'])
                key = (text, item['color'], item.get('layout_role', ''))
                if key not in self.assets:
                    lines = text.splitlines() or ['']
                    line_height = 130
                    image_height = 150 if len(lines) == 1 else line_height*len(lines)+20
                    im = Image.new('RGBA', (1344, image_height))
                    draw = ImageDraw.Draw(im)
                    font_path = Path('C:/Windows/Fonts/arialbd.ttf')
                    font_size = 92
                    font = ImageFont.truetype(str(font_path), font_size) if font_path.is_file() else ImageFont.load_default(size=font_size)
                    while max(draw.textbbox((0, 0), line, font=font)[2] for line in lines) > 1300 and font_size > 14:
                        font_size -= 2
                        font = ImageFont.truetype(str(font_path), font_size) if font_path.is_file() else ImageFont.load_default(size=font_size)
                    for number, line in enumerate(lines):
                        y = image_height/2 + (number-(len(lines)-1)/2)*line_height
                        draw.text((672, y), line, font=font, anchor='mm', fill=item['color'], stroke_width=3, stroke_fill=(0, 0, 0, 160))
                    if item.get('layout_role', '').startswith('players_') and im.getbbox():
                        # Blender crops generated text to its visible bounds.
                        im = im.crop(im.getbbox())
                    self.assets[key] = np.array(im)
            im = self.assets[key]
            h, w = im.shape[:2]
            corners = np.float32(cinema.corners_at(item, seconds))*np.float32([size[0]/100, size[1]/100])
            matrix = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [0, h], [w, h]]), corners)
            x0 = max(0, int(np.floor(corners[:, 0].min()))-2)
            y0 = max(0, int(np.floor(corners[:, 1].min()))-2)
            x1 = min(size[0], int(np.ceil(corners[:, 0].max()))+2)
            y1 = min(size[1], int(np.ceil(corners[:, 1].max()))+2)
            if x1 <= x0 or y1 <= y0:
                continue
            matrix = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], dtype=np.float64) @ matrix
            rgba = cv2.warpPerspective(im, matrix, (x1-x0, y1-y0))
            alpha = rgba[:, :, 3:4].astype(np.float32)*(opacity/255)
            out[y0:y1, x0:x1] = out[y0:y1, x0:x1]*(1-alpha)+rgba[:, :, :3]*alpha
        if len(self.assets) > 80:
            self.assets.clear()
        return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
