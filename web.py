import torch
from diffusers import StableDiffusionPipeline, StableDiffusionImg2ImgPipeline, EulerAncestralDiscreteScheduler
from compel import Compel
from PIL import Image

import random
from functools import partial
import time
import json
from urllib.parse import urlparse, parse_qs, unquote, quote
import base64
from io import BytesIO
import mimetypes
import os
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from multipart import MultipartParser

print("Loading model...")
pipe = StableDiffusionPipeline.from_pretrained(
    "./models/stable-diffusion-v1-5",
    torch_dtype=torch.float16,
    local_files_only=True
)
compel = Compel(tokenizer=pipe.tokenizer, text_encoder=pipe.text_encoder)
pipe.safety_checker = None
pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
pipe.set_progress_bar_config(disable=True)
print("Moving to GPU...")
pipe = pipe.to("cuda")
pipe.enable_xformers_memory_efficient_attention()

img2img_pipe = StableDiffusionImg2ImgPipeline(**pipe.components)
img2img_pipe.set_progress_bar_config(disable=True)

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
        print(f"Generating [{seed}]: +{data['positive']} | -{data['negative']}")
        result = None
        if 'initimg' not in data:
            result = pipe(
                prompt_embeds=compel(data['positive']),
                negative_prompt_embeds=compel(data['negative']),
                width=int(data['width']),
                height=int(data['height']),
                num_inference_steps=int(data['steps']),
                guidance_scale=float(data['cfgscale']),
                generator=generator,
                callback=partial(update_progress, data)
            )
        else:
            result = img2img_pipe(
                image=data['initimg'],
                prompt_embeds=compel(data['positive']),
                negative_prompt_embeds=compel(data['negative']),
                num_inference_steps=int(data['steps']),
                guidance_scale=float(data['cfgscale']),
                generator=generator,
                callback=partial(update_progress, data)
            )
        image = result.images[0]
        image.save(filename, 'jpeg', progressive=True, quality=90)
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
            with open("./static/index.html", "rb") as content:
                self.wfile.write(content.read())
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
        elif parsed.path == "/queue":
            query = parse_qs(parsed.query)
            filename = query['filename'][0]
            data = next(x['data'] for x in queue if x['filename'] == filename)

            if queue[0]['filename'] == filename:
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()

                progress = 0
                self.wfile.write(f'''\
                <div class="loading"
                    style="aspect-ratio: {data['width']}/{data['height']};"
                    title="{data['title'].replace('"', "&quot;")}"
                    hx-get="/progress"
                    hx-trigger="load delay:0.5s"
                    hx-vals='{{"filename": "{filename}"}}'
                    hx-swap="outerHTML">
                    <div id="loading-bar" style="width: {progress*100}%"></div>
                </div>\
                '''.encode())

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
                self.wfile.write(f'''\
                <div id="loading" class="loading"
                    style="aspect-ratio: {data['width']}/{data['height']};"
                    title="{data['title'].replace('"', "&quot;")}"
                    hx-get="/progress"
                    hx-trigger="load delay:0.5s"
                    hx-vals='{{"filename": "{filename}"}}'
                    hx-swap="outerHTML">
                    <div id="loading-bar" style="width: {progress*100}%"></div>
                </div>\
                '''.encode())
            else:
                data = done[filename]
                data['initimg'] = None
                settings = json.dumps(data).replace('"', '&quot;')
                self.wfile.write(f'''\
                <img src="{filename}"
                     title="{data['title'].replace('"', "&quot;")}"
                     style="aspect-ratio: {data['width']}/{data['height']};"
                     onload="flashTitle();this.style.opacity='1';"
                     oncontextmenu="applySettings(event, {settings});"
                     onclick="window.open(this.src, '_blank').focus();"></img>
                '''.encode())
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

                elements.append(f'''\
                <div class="queue"
                    style="aspect-ratio: {data['width']}/{data['height']};"
                    title="{data['title'].replace('"', "&quot;")}"
                    hx-get="/queue"
                    hx-trigger="every 1s [document.getElementById('loading') == null]"
                    hx-vals='{{"filename": "{filename}"}}'
                    hx-swap="outerHTML"
                    onclick="cancel(this);">
                </div>\
                ''')
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
