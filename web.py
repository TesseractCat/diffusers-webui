import torch
from diffusers import StableDiffusionPipeline

import time
import json
from urllib.parse import parse_qs, unquote, quote
import base64
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

print("Loading model...")
pipe = StableDiffusionPipeline.from_pretrained(
    "./models/stable-diffusion-v1-5",
    torch_dtype=torch.float16,
    local_files_only=True
)
pipe.safety_checker = None
print("Moving to GPU...")
pipe = pipe.to("cuda")

def run(data):
    return pipe(
        prompt=data['prompt'],
        width=int(data['width']),
        height=int(data['height']),
        num_inference_steps=int(data['steps']),
        guidance_scale=float(data['cfgscale']),
    )

class DreamServer(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            with open("./static/index.html", "rb") as content:
                self.wfile.write(content.read())
        elif os.path.exists("." + self.path):
            mime_type = mimetypes.guess_type(self.path)[0]
            if mime_type is not None:
                self.send_response(200)
                self.send_header("Content-type", mime_type)
                self.end_headers()
                with open("." + self.path, "rb") as content:
                    self.wfile.write(content.read())
            else:
                self.send_response(404)
        elif self.path == "/progress":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()

            progress = 0.5
            self.wfile.write(f'<progress id="progress" value="{progress}" max="1" hx-get="/progress" hx-trigger="every 1s" hx-swap="outerHTML"></progress>'.encode())
        else:
            self.send_response(404)

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        if self.path == "/generate":
            content_length = int(self.headers['Content-Length'])
            data = parse_qs(self.rfile.read(content_length).decode("utf-8"))
            data = {k: v[0] for k, v in data.items()}

            path = f"./outputs/{quote(data['prompt'])}-{int(time.time())}.jpg"

            self.wfile.write(f'''
            <img src="static/bar.svg"
                 hx-get="/progress"
                 hx-trigger="load delay:0.5s"
                 hx-vals='{{"path": "{path}"}}'
                 hx-swap="outerHTML"></img>
            '''.encode())

            image = run(data).images[0]
            image.save(path)
            #self.wfile.write(f'<img src="{path}"></img>'.encode())
            print(data)
        elif self.path == "/progress":
            self.wfile.write(f'''
            <h1>cool dog</h1>
            '''.encode())
            

if __name__ == "__main__":
    # Start server
    dream_server = ThreadingHTTPServer(("0.0.0.0", 9090), DreamServer)
    print("\n* Started Stable Diffusion dream server! Point your browser at http://localhost:9090 or use the host's DNS name or IP address. *")

    try:
        dream_server.serve_forever()
    except KeyboardInterrupt:
        pass

    dream_server.server_close()
