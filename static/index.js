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
            form.querySelector(`*[name=${k}]`).value = item;
        }
    }
}
function applySettings(e, settings) {
    e.preventDefault();

    let form = document.querySelector("#generate-form");

    for (const [k, v] of new FormData(form)) {
        const item = settings[k];
        if (item != null) {
            form.querySelector(`*[name=${k}]`).value = item;
        }
    }
}

function cancel(item) {
    let filename = JSON.parse(item.getAttribute("hx-vals")).filename;
    fetch("/cancel?filename=" + encodeURIComponent(filename));
    item.remove();
}
function flashTitle() {
    document.title = "* Done *";
    setTimeout(() => document.title = "Stable Diffusion", 500);
}

window.onload = () => {
    document.querySelectorAll("textarea").forEach(elem => {
        elem.addEventListener("keydown", (e) => {
            if (e.which === 13 && !e.shiftKey) {
                e.preventDefault();
                const submitEvent = new Event("submit", {cancelable: true});
                e.target.form.dispatchEvent(submitEvent);
            }
        });
    });
    document.querySelector("#generate-form").addEventListener('change', (e) => {
        saveFields(e.target.form);
    });
    document.querySelector("#reset").addEventListener('click', (e) => {
        document.querySelector("#seed").value = -1;
        saveFields(e.target.form);
    });
    document.querySelector("#results").addEventListener('htmx:beforeSwap', () => {
        document.querySelector("#nothing")?.remove();
    });
    loadFields(document.querySelector("#generate-form"));
};

