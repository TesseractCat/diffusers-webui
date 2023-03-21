import torch
from diffusers.utils import logging
from diffusers import (
    StableDiffusionPipeline,
    StableDiffusionImg2ImgPipeline,
    StableDiffusionControlNetPipeline,
    ControlNetModel,
    EulerAncestralDiscreteScheduler
)
from compel import Compel
from PIL import Image

from string import Template
import random
from functools import partial
from collections import namedtuple
import itertools
import time
import json
from urllib.parse import urlparse, parse_qs, unquote, quote
import base64
from io import BytesIO
import mimetypes
import os
from pathlib import Path
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from multipart import MultipartParser

index_template = Template(open("./static/index.html", "r").read())

nothing_template = '''<i id="nothing">Nothing yet...</i>'''

queue_template = Template('''\
<div class="queue"
    style="aspect-ratio: $width/$height;"
    title="$title"
    hx-get="/queue"
    hx-trigger="every 1s [document.getElementById('loading') == null]"
    hx-vals='{"filename": "$filename"}'
    hx-swap="outerHTML"
    onclick="cancel(this);">
</div>\
''')

loading_template = Template('''\
<div id="loading" class="loading"
    style="aspect-ratio: $width/$height;"
    title="$title"
    hx-get="/progress"
    hx-trigger="load delay:0.5s"
    hx-vals='{"filename": "$filename"}'
    hx-swap="outerHTML">
    <div id="loading-bar" style="width: $progress%"></div>
</div>\
''')

result_template = Template('''\
<img src="$filename"
        title="$title"
        style="aspect-ratio: $width/$height;"
        onload="this.style.opacity='1';$onload"
        oncontextmenu="applySettings(event, $settings);"
        onclick="window.open(this.src, '_blank').focus();"></img>\
''')

Pipeline = namedtuple('Pipeline', ['pipeline', 'name', 'settings', 'specialize'])
pipelines = []

pipeline_option_template= Template('''<option value="$name">$name</option>''')

logging.set_verbosity_error()
logging.disable_progress_bar()

print("Loading model...")
txt2img = StableDiffusionPipeline.from_pretrained(
    "./models/stable-diffusion-v1-5",
    torch_dtype=torch.float16,
    local_files_only=True
)
compel = Compel(tokenizer=txt2img.tokenizer, text_encoder=txt2img.text_encoder)
txt2img.safety_checker = None
txt2img.scheduler = EulerAncestralDiscreteScheduler.from_config(txt2img.scheduler.config)
print("Moving to GPU...")
txt2img = txt2img.to("cuda")

print("Loading other pipelines...")
img2img = StableDiffusionImg2ImgPipeline(**txt2img.components)

controlnet = ControlNetModel.from_pretrained(
    "./models/sd-controlnet-scribble",
    torch_dtype=torch.float16,
    local_files_only=True
)
controlnet = controlnet.to("cuda")
txt2img_controlnet = StableDiffusionControlNetPipeline(**txt2img.components, controlnet=controlnet)

pipelines.append(Pipeline(txt2img, 'Text to image', '''
<i>No settings...</i>
''', lambda p,d: partial(p,
                         width=int(d['width']), height=int(d['height'])
                         )))
pipelines.append(Pipeline(img2img, 'Image to image', '''
<label for="initimg">
    <input type="file" id="initimg" name="initimg" accept=".jpg, .jpeg, .png" required>
    <button type="button"
            onclick="this.previousElementSibling.value = '';">&olarr;</button>
</label>
<label for="strength">Strength:
    <input value="0.8" min="0" max="1" type="number" id="strength" name="strength" step="0.1">
</label>
''', lambda p,d: partial(p,
                         image=d['initimg'].resize((int(d['width']), int(d['height'])))
                         )))
pipelines.append(Pipeline(txt2img_controlnet, 'ControlNet [Scribble]', '''
<label for="initimg">
    <input type="file" id="initimg" name="initimg" accept=".jpg, .jpeg, .png" required>
    <button type="button"
            onclick="this.previousElementSibling.value = '';">&olarr;</button>
</label>
''', lambda p,d: partial(p,
                         image=d['initimg'],
                         width=int(d['width']), height=int(d['height'])
                         )))

for p in pipelines:
    p.pipeline.enable_xformers_memory_efficient_attention()
    p.pipeline.set_progress_bar_config(disable=True)

done = {}
queue = []
progress = 0
def update_progress(data, s, t, l):
    global progress
    progress = s/int(data['steps'])
def run(data, filename):
    global done
    global queue
    global progress

    with torch.inference_mode():
        data = data.copy() # Shallow clone because we are modifying seed

        seed = int(data['seed'])
        generator = torch.Generator(device="cuda").manual_seed(seed)
        if seed == -1:
            seed = generator.seed()
        data['seed'] = str(seed)
        print(f"Generating [{data['pipeline']}]/[{seed}]: +{data['positive']} | -{data['negative']}")

        pipeline = next(p for p in pipelines if p.name == data['pipeline'])
        specialized = pipeline.specialize(pipeline.pipeline, data)

        result = specialized(
            prompt_embeds=compel(data['positive']),
            negative_prompt_embeds=compel(data['negative']),
            num_inference_steps=int(data['steps']),
            guidance_scale=float(data['cfgscale']),
            generator=generator,
            callback=partial(update_progress, data)
        )

        image = result.images[0]
        exif = image.getexif()
        primitives = (int, float, bool, str, list, dict) # Only save basic data
        exif[0x9286] = json.dumps({k: v for k, v in data.items() if type(v) in primitives}) # UserComment exif field

        image.save(filename, 'jpeg', progressive=True, quality=90, exif=exif)
        queue.pop(0)
        done[filename] = data

class DreamServer(BaseHTTPRequestHandler):
    def do_GET(self):
        global done
        global queue
        global progress

        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()

            results = []
            files = itertools.islice(
                sorted(Path('./outputs').iterdir(), key=os.path.getctime, reverse=True),
                8
            )
            for filename in files:
                with Image.open(filename) as image:
                    exif = image.getexif()
                    data = json.loads(exif[0x9286])
                    settings = json.dumps(data).replace('"', '&quot;')
                    results.append(result_template.substitute(
                        filename=filename, title=data['title'].replace('"', "&quot;"),
                        width=data['width'], height=data['height'],
                        settings=settings, onload=""
                    ))

            self.wfile.write(index_template.substitute(
                pipelines="\n".join(map(
                    lambda p: pipeline_option_template.substitute(name=p.name),
                    pipelines
                )),
                pipeline_settings=pipelines[0].settings,
                results="\n".join(results) if len(results) > 0 else nothing_template
            ).encode())
        elif os.path.exists("." + unquote(parsed.path)):
            mime_type = mimetypes.guess_type(unquote(parsed.path))[0]
            if mime_type is not None:
                self.send_response(200)
                self.send_header("Content-type", mime_type)
                self.end_headers()
                with open("." + unquote(parsed.path), "rb") as content:
                    self.wfile.write(content.read())
            else:
                self.send_response(404)
        elif parsed.path == "/settings":
            query = parse_qs(parsed.query)
            name = query['pipeline'][0]
            pipeline = next(p for p in pipelines if p.name == name)

            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(pipeline.settings.encode())
        elif parsed.path == "/queue":
            query = parse_qs(parsed.query)
            filename = query['filename'][0]
            data = next(x['data'] for x in queue if x['filename'] == filename)

            if queue[0]['filename'] == filename:
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()

                progress = 0
                self.wfile.write(loading_template.substitute(
                    filename=filename, title=data['title'].replace('"', "&quot;"),
                    width=data['width'], height=data['height'],
                    progress=progress*100,
                ).encode())

                thread = Thread(target = run, args = (data, filename))
                thread.start()
            else:
                self.send_response(204)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b'<br>')
        elif parsed.path == "/cancel":
            self.send_response(204)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b'<br>')

            query = parse_qs(parsed.query)
            filename = query['filename'][0]
            index = next(i for i, x in enumerate(queue) if x['filename'] == filename)
            queue.pop(index)
            print(f"Cancelled queue item [{index}]: {filename}")
        elif parsed.path == "/progress":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            query = parse_qs(parsed.query)
            filename = query['filename'][0]
            data = next((x['data'] for x in queue if x['filename'] == filename), None)

            if data != None:
                self.wfile.write(loading_template.substitute(
                    filename=filename, title=data['title'].replace('"', "&quot;"),
                    width=data['width'], height=data['height'],
                    progress=progress*100,
                ).encode())
            else:
                data = done[filename]
                data['initimg'] = None
                settings = json.dumps(data).replace('"', '&quot;')
                self.wfile.write(result_template.substitute(
                    filename=filename, title=data['title'].replace('"', "&quot;"),
                    width=data['width'], height=data['height'],
                    settings=settings, onload="flashTitle();"
                ).encode())
        else:
            self.send_response(404)

    def do_POST(self):
        global progress

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        if self.path == "/generate":
            content_length = int(self.headers['Content-Length'])
            #data = parse_qs(self.rfile.read(content_length).decode("utf-8"))
            #data = {k: v[0] for k, v in data.items()}
            boundary = self.headers['Content-Type'].split("boundary=")[1]
            data = MultipartParser(self.rfile, boundary.encode(), content_length, charset="utf-8")
            data = {part.name: (Image.open(BytesIO(part.raw)) if part.name == "initimg" else part.value) for part in data}

            data['positive'] = data.get('positive', '')
            data['negative'] = data.get('negative', '')
            data['title'] = f"+{data['positive']} | -{data['negative']}"

            print(f"Queued {data['iterations']} image(s): +{data['positive']} | -{data['negative']}")

            elements = []
            for i in range(int(data['iterations'])):
                fileprompt = data['positive'].replace("'", "").replace('"', "").replace("/", "")[:20]
                filename = f"./outputs/{fileprompt}-{random.getrandbits(64)}.jpg"

                entry = {"data": data, "filename": filename}
                queue.append(entry)

                elements.append(queue_template.substitute(
                    filename=filename, title=data['title'].replace('"', "&quot;"),
                    width=data['width'], height=data['height']
                ))
            elements.reverse()
            self.wfile.write("\n".join(elements).encode())

    def log_request(self, code='-', size='-'):
        return

if __name__ == "__main__":
    # Start server
    dream_server = ThreadingHTTPServer(("0.0.0.0", 9090), DreamServer)
    print("\n* Started Stable Diffusion dream server! Point your browser at http://localhost:9090 or use the host's DNS name or IP address. *")

    try:
        dream_server.serve_forever()
    except KeyboardInterrupt:
        pass

    dream_server.server_close()
