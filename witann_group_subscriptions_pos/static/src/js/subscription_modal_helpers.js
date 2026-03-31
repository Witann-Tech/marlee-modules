/** @odoo-module **/

function readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(reader.error || new Error("file_read_error"));
        reader.readAsDataURL(file);
    });
}

function stripDataUrlPrefix(value) {
    return String(value || "").replace(/^data:image\/[^;]+;base64,/i, "");
}

function showSimpleInfoModal({
    modalId,
    title,
    message,
    closeLabel,
    escapeHtml,
}) {
    const previous = document.getElementById(modalId);
    if (previous) {
        previous.remove();
    }

    const overlay = document.createElement("div");
    overlay.id = modalId;
    overlay.className = "wgs-status-modal-overlay";

    const modal = document.createElement("div");
    modal.className = "wgs-status-modal";

    modal.innerHTML = `
        <div class="wgs-status-modal-header"><h3>${escapeHtml(title)}</h3></div>
        <div class="wgs-status-modal-body"><p class="wgs-simple-message">${escapeHtml(message)}</p></div>
        <div class="wgs-status-modal-footer">
            <button type="button" class="wgs-status-close-btn">${escapeHtml(closeLabel)}</button>
        </div>
    `;

    const closeModal = () => overlay.remove();
    modal.querySelector(".wgs-status-close-btn").addEventListener("click", closeModal);
    overlay.addEventListener("click", (event) => {
        if (event.target === overlay) {
            closeModal();
        }
    });

    overlay.appendChild(modal);
    document.body.appendChild(overlay);
}

export {
    readFileAsDataUrl,
    showSimpleInfoModal,
    stripDataUrlPrefix,
};
