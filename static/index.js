import './sketch.js';

// https://stackoverflow.com/a/52311051
function getBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.readAsDataURL(file);
    reader.onload = () => {
      let encoded = reader.result.toString().replace(/^data:(.*,)?/, '');
      if ((encoded.length % 4) > 0) {
        encoded += '='.repeat(4 - (encoded.length % 4));
      }
      resolve(encoded);
    };
    reader.onerror = error => reject(error);
  });
}

function saveFields(form) {
    for (const [k, v] of new FormData(form)) {
        if (typeof v !== 'object') { // Don't save 'file' type
            localStorage.setItem(k, v);
        }
    }
}
function loadFields(form) {
    for (const [k, v] of new FormData(form)) {
        const item = localStorage.getItem(k);
        if (item != null) {
            let elem = form.querySelector(`*[name=${k}]`);
            elem.value = item;
            elem.dispatchEvent(new Event('change'));
        }
    }
}
function applySettings(e, settings) {
    e.preventDefault();

    let form = document.querySelector("#generate-form");

    for (const [k, v] of new FormData(form)) {
        const item = settings[k];
        if (item != null) {
            let elem = form.querySelector(`*[name=${k}]`);
            elem.value = item;
            elem.dispatchEvent(new Event('change'));
        }
    }
}
window.applySettings = applySettings;

function cancel(item) {
    let filename = JSON.parse(item.getAttribute("hx-vals")).filename;
    fetch("/cancel?filename=" + encodeURIComponent(filename));
    item.remove();
}
window.cancel = cancel;
function flashTitle() {
    document.title = "* Done *";
    setTimeout(() => document.title = "Stable Diffusion", 500);
}
window.flashTitle = flashTitle;

window.onload = () => {
    document.querySelector("#guide").addEventListener('change', (e) => {
        if (e.target.value != "img2img") {
            document.querySelector("#strength").setAttribute("disabled", "");
        } else {
            document.querySelector("#strength").removeAttribute("disabled");
        }
    });

    document.querySelectorAll("textarea").forEach(elem => {
        elem.addEventListener("keydown", (e) => {
            if (e.which === 13 && !e.shiftKey) {
                e.preventDefault();
                const submitEvent = new Event("submit", {cancelable: true});
                e.target.form.dispatchEvent(submitEvent);
            }
        });
    });
    document.querySelector("#results").addEventListener('htmx:beforeSwap', () => {
        document.querySelector("#nothing")?.remove();
    });

    // Sketchpad
    document.querySelector("#sketchpad").addEventListener('change', async (e) => {
        // Hacky way to set file input files
        let file = await e.target.toFile("Sketch");
        let dt = new DataTransfer();
        dt.items.add(file);
        document.querySelector("#initimg").files = dt.files;
    });

    // Drag and drop
    document.documentElement.addEventListener('dragover', (e) => {
        e.preventDefault();
        document.body.classList.add('dragging');
    });
    document.documentElement.addEventListener('dragleave', () => {
        document.body.classList.remove('dragging');
    });
    document.documentElement.addEventListener('drop', (e) => {
        e.preventDefault();
        document.body.classList.remove('dragging');
        
        document.querySelector('#initimg').files = e.dataTransfer.files;
    });

    // Load fields *before* registering change/save event
    loadFields(document.querySelector("#generate-form"));
    document.querySelector("#generate-form").addEventListener('change', (e) => {
        saveFields(e.target.form);
    });
};

