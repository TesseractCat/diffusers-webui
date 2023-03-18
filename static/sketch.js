export class SketchElement extends HTMLElement {
    #shadow;
    #canvas;
    #ctx;

    constructor() {
        super();
        this.#shadow = this.attachShadow({mode: "open"});

        let style = document.createElement("style");
        style.textContent = `
:host {
    display: block;
    transform: scale(1);
}
canvas {
    border-radius: inherit;
    width: 100%;
    height: 100%;
}

button {
    width: 40px;
    height: 40px;

    background-color: #999;
    border: none;
    color: white;
    cursor: pointer;
}
button:hover {
    background-color: #888;
}
button:active {
    background-color: #666;
}
#clear {
    border-radius: 5px 5px 0px 0px;
}
#send {
    border-radius: 0px 0px 5px 5px;
    font-size: 1.5em;
}
#buttons {
    position: absolute;
    display: flex;
    flex-direction: column;
    top: 10px;
    right: 10px;
}
        `;
        this.#shadow.appendChild(style);

        let buttons = document.createElement("div");
        buttons.id = "buttons";
        let clearButton = document.createElement("button");
        let sendButton = document.createElement("button");
        clearButton.id = "clear";
        sendButton.id = "send";
        clearButton.innerText = "⌫";
        sendButton.innerText = "⏎";
        buttons.appendChild(clearButton);
        buttons.appendChild(sendButton);
        this.#shadow.appendChild(buttons);

        this.#canvas = document.createElement("canvas");
        this.#ctx = this.#canvas.getContext("2d");

        const clearCanvas = () => {
            this.#ctx.closePath();
            this.#ctx.fillStyle = this.getAttribute("bg-color");
            this.#ctx.fillRect(0, 0, this.#canvas.width, this.#canvas.height);
        }
        const resizeCanvas = () => {
            let rect = this.#canvas.getBoundingClientRect();
            this.#canvas.width = rect.width;
            this.#canvas.height = rect.height;

            clearCanvas();
        }
        //window.addEventListener('resize', resizeCanvas);

        clearButton.addEventListener('click', clearCanvas);
        sendButton.addEventListener('click', () => {
            this.dispatchEvent(new Event('change'));
        });

        let down = false;
        let [x, y] = [0, 0];
        this.#canvas.addEventListener('mousedown', (e) => {
            down = true;
            [x, y] = [e.offsetX, e.offsetY];
            this.#ctx.strokeStyle = e.ctrlKey ?
                this.getAttribute("bg-color") : this.getAttribute("pen-color");
            this.#ctx.lineWidth = this.getAttribute("pen-size");
            this.#ctx.lineJoin = "round";
            this.#ctx.lineCap = "round";

            this.#ctx.beginPath();
            this.#ctx.moveTo(x, y);
            this.#ctx.lineTo(x, y);
            this.#ctx.stroke();
        });
        window.addEventListener('mouseup', () => {
            down = false;
            this.#ctx.closePath();
        });
        window.addEventListener('mousemove', (e) => {
            if (down) {
                let rect = this.#canvas.getBoundingClientRect();
                this.#ctx.lineTo(e.clientX - rect.x, e.clientY - rect.y);
                this.#ctx.stroke();
            }
            [x, y] = [e.offsetX, e.offsetY];
        });
        
        this.#shadow.appendChild(this.#canvas);
        resizeCanvas();
    }

    async toFile(filename) {
        return new Promise((resolve) => {
            this.#canvas.toBlob((blob) => {
                resolve(new File([blob], filename, { type: "image/jpeg" }))
            }, 'image/jpeg');
        });
    }
}
customElements.define("x-sketch", SketchElement);
