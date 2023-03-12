import torch
from diffusers import StableDiffusionPipeline, EulerAncestralDiscreteScheduler

import random
from functools import partial
import time
import json
from urllib.parse import urlparse, parse_qs, unquote, quote
import base64
import mimetypes
import os
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

print("Loading model...")
pipe = StableDiffusionPipeline.from_pretrained(
    "./models/stable-diffusion-v1-5",
    torch_dtype=torch.float16,
    local_files_only=True
)
pipe.safety_checker = None
pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
pipe.set_progress_bar_config(disable=True)
print("Moving to GPU...")
pipe = pipe.to("cuda")
pipe.enable_xformers_memory_efficient_attention()

queue = []
progress = 0
def update_progress(data, s, t, l):
    global progress
    progress = s/int(data['steps'])
def run(data, path):
    global queue
    global progress

    with torch.inference_mode():
        seed = int(data['seed'])
        generator = torch.Generator(device="cuda").manual_seed(seed)
        if seed == -1:
            seed = generator.seed()
        print(f"Generating [{seed}]: +{data['positive']} | -{data['negative']}")
        result = pipe(
            prompt=data['positive'],
            negative_prompt=data['negative'],
            width=int(data['width']),
            height=int(data['height']),
            num_inference_steps=int(data['steps']),
            guidance_scale=float(data['cfgscale']),
            generator=generator,
            callback=partial(update_progress, data)
        )
        image = result.images[0]
        image.save(path)
        progress = 1
        queue.pop(0)

class DreamServer(BaseHTTPRequestHandler):
    def do_GET(self):
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
                    title="+{data['positive']} | -{data['negative']}"
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
        elif parsed.path == "/progress":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            query = parse_qs(parsed.query)
            filename = query['filename'][0]
            data = next((x['data'] for x in queue if x['filename'] == filename), None)

            if data != None:
                self.wfile.write(f'''\
                <div class="loading"
                    title="+{data['positive']} | -{data['negative']}"
                    hx-get="/progress"
                    hx-trigger="load delay:0.5s"
                    hx-vals='{{"filename": "{filename}"}}'
                    hx-swap="outerHTML">
                    <div id="loading-bar" style="width: {progress*100}%"></div>
                </div>\
                '''.encode())
            else:
                self.wfile.write(f'''\
                <img src="{filename}"
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
            data = parse_qs(self.rfile.read(content_length).decode("utf-8"))
            data = {k: v[0] for k, v in data.items()}
            data['positive'] = data.get('positive', '')
            data['negative'] = data.get('negative', '')

            elements = []
            for i in range(int(data['iterations'])):
                fileprompt = data['positive'].replace("'", "").replace('"', "")[:20]
                filename = f"./outputs/{fileprompt}-{random.getrandbits(64)}.jpg"

                entry = {"data": data, "filename": filename}
                queue.append(entry)

                elements.append(f'''\
                <div class="queue"
                    title="+{data['positive']} | -{data['negative']}"
                    hx-get="/queue"
                    hx-trigger="every 1s"
                    hx-vals='{{"filename": "{filename}"}}'
                    hx-swap="outerHTML"
                    onclick="cancel(this);">
                </div>\
                ''')
            elements.reverse()
            self.wfile.write("\n".join(elements).encode())
            

if __name__ == "__main__":
    # Start server
    dream_server = ThreadingHTTPServer(("0.0.0.0", 9090), DreamServer)
    print("\n* Started Stable Diffusion dream server! Point your browser at http://localhost:9090 or use the host's DNS name or IP address. *")

    try:
        dream_server.serve_forever()
    except KeyboardInterrupt:
        pass

    dream_server.server_close()
