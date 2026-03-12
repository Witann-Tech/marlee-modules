/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

class FaceCameraField extends Component {
    static template = "access_control_api.FaceCameraField";
    static props = {
        ...standardFieldProps,
    };
    static supportedTypes = ["binary"];

    get hasValue() {
        return Boolean(this.props.value);
    }

    get imageSrc() {
        return this.hasValue ? `data:image/jpeg;base64,${this.props.value}` : null;
    }

    async onFileChange(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) {
            return;
        }
        try {
            const dataUrl = await this._readFileAsDataURL(file);
            this.props.update(this._base64FromDataURL(dataUrl));
        } finally {
            ev.target.value = "";
        }
    }

    clearImage() {
        if (this.props.readonly) {
            return;
        }
        this.props.update(false);
    }

    async takePhoto() {
        if (this.props.readonly) {
            return;
        }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            window.alert("Tu navegador no soporta acceso a cámara.");
            return;
        }

        let stream = null;
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: "user" },
                audio: false,
            });
        } catch (_error) {
            window.alert("No fue posible acceder a la cámara. Revisa permisos del navegador.");
            return;
        }

        try {
            const base64 = await this._captureFromStream(stream);
            if (base64) {
                this.props.update(base64);
            }
        } finally {
            stream.getTracks().forEach((track) => track.stop());
        }
    }

    _readFileAsDataURL(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    _base64FromDataURL(dataUrl) {
        const parts = String(dataUrl || "").split(",");
        return parts.length > 1 ? parts[1] : parts[0];
    }

    _captureFromStream(stream) {
        return new Promise((resolve) => {
            const overlay = document.createElement("div");
            overlay.style.position = "fixed";
            overlay.style.inset = "0";
            overlay.style.background = "rgba(0, 0, 0, 0.8)";
            overlay.style.display = "flex";
            overlay.style.alignItems = "center";
            overlay.style.justifyContent = "center";
            overlay.style.zIndex = "9999";

            const panel = document.createElement("div");
            panel.style.background = "#fff";
            panel.style.padding = "16px";
            panel.style.borderRadius = "8px";
            panel.style.maxWidth = "920px";
            panel.style.width = "95vw";

            const title = document.createElement("div");
            title.textContent = "Captura de foto";
            title.style.fontWeight = "600";
            title.style.marginBottom = "12px";

            const video = document.createElement("video");
            video.style.width = "100%";
            video.style.maxHeight = "70vh";
            video.style.background = "#111";
            video.autoplay = true;
            video.playsInline = true;
            video.srcObject = stream;

            const actions = document.createElement("div");
            actions.style.display = "flex";
            actions.style.gap = "8px";
            actions.style.justifyContent = "flex-end";
            actions.style.marginTop = "12px";

            const cancelButton = document.createElement("button");
            cancelButton.type = "button";
            cancelButton.className = "btn btn-secondary";
            cancelButton.textContent = "Cancelar";

            const captureButton = document.createElement("button");
            captureButton.type = "button";
            captureButton.className = "btn btn-primary";
            captureButton.textContent = "Tomar foto";

            actions.appendChild(cancelButton);
            actions.appendChild(captureButton);
            panel.appendChild(title);
            panel.appendChild(video);
            panel.appendChild(actions);
            overlay.appendChild(panel);
            document.body.appendChild(overlay);

            const cleanup = () => {
                if (overlay.parentNode) {
                    overlay.parentNode.removeChild(overlay);
                }
            };

            cancelButton.addEventListener("click", () => {
                cleanup();
                resolve(null);
            });

            captureButton.addEventListener("click", () => {
                const vw = video.videoWidth || 1280;
                const vh = video.videoHeight || 720;
                const maxSize = 1024;
                const scale = Math.min(maxSize / vw, maxSize / vh, 1);
                const width = Math.max(1, Math.round(vw * scale));
                const height = Math.max(1, Math.round(vh * scale));

                const canvas = document.createElement("canvas");
                canvas.width = width;
                canvas.height = height;
                const ctx = canvas.getContext("2d");
                ctx.drawImage(video, 0, 0, width, height);

                const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
                cleanup();
                resolve(this._base64FromDataURL(dataUrl));
            });
        });
    }
}

registry.category("fields").add("face_camera", {
    component: FaceCameraField,
    displayName: "Foto con cámara",
});
