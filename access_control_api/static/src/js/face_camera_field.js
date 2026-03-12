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

    _setValue(value) {
        if (typeof this.props.update === "function") {
            this.props.update(value);
            return;
        }
        if (this.props.record && typeof this.props.record.update === "function") {
            this.props.record.update({ [this.props.name]: value });
            return;
        }
        throw new Error("face_camera: no writable API found on field props");
    }

    async onFileChange(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) {
            return;
        }
        try {
            const dataUrl = await this._readFileAsDataURL(file);
            this._setValue(this._base64FromDataURL(dataUrl));
        } finally {
            ev.target.value = "";
        }
    }

    clearImage() {
        if (this.props.readonly) {
            return;
        }
        this._setValue(false);
    }

    async takePhoto() {
        if (this.props.readonly) {
            return;
        }
        if (!window.isSecureContext) {
            window.alert("La cámara solo funciona en contexto seguro (HTTPS o localhost).");
            return;
        }
        const mediaDevices = navigator.mediaDevices;
        if (!mediaDevices || !mediaDevices.getUserMedia) {
            window.alert("Tu navegador no soporta acceso a cámara.");
            return;
        }
        const policy = document.permissionsPolicy || document.featurePolicy;
        if (policy && typeof policy.allowsFeature === "function") {
            try {
                if (!policy.allowsFeature("camera")) {
                    window.alert("La cámara está bloqueada por la política del sitio (Permissions-Policy).");
                    return;
                }
            } catch (_error) {
                // Ignore policy introspection errors and continue with runtime request.
            }
        }

        let stream = null;
        try {
            stream = await this._openCameraStream(mediaDevices);
        } catch (error) {
            // Keep browser-level diagnostics visible for remote debugging in staging.
            // eslint-disable-next-line no-console
            console.error("face_camera getUserMedia error", {
                name: error && error.name,
                message: error && error.message,
                constraint: error && error.constraint,
            });
            window.alert(this._cameraErrorMessage(error));
            return;
        }

        try {
            const base64 = await this._captureFromStream(stream);
            if (base64) {
                this._setValue(base64);
            }
        } finally {
            if (stream) {
                stream.getTracks().forEach((track) => track.stop());
            }
        }
    }

    async _openCameraStream(mediaDevices) {
        const attempts = [
            {
                video: true,
                audio: false,
            },
            {
                video: {
                    width: { ideal: 1280 },
                    height: { ideal: 720 },
                    facingMode: { ideal: "user" },
                },
                audio: false,
            },
        ];
        let lastError = null;
        for (const constraints of attempts) {
            try {
                return await mediaDevices.getUserMedia(constraints);
            } catch (error) {
                lastError = error;
            }
        }
        throw lastError;
    }

    _cameraErrorMessage(error) {
        const name = error && error.name ? error.name : "";
        const message = error && error.message ? String(error.message) : "";
        if (name === "NotAllowedError" || name === "SecurityError") {
            return `No fue posible acceder a la cámara (${name}). ${message || "El navegador o una política del sitio la bloqueó antes del prompt."}`;
        }
        if (name === "NotFoundError" || name === "DevicesNotFoundError") {
            return "No se encontró una cámara disponible en este equipo.";
        }
        if (name === "NotReadableError" || name === "TrackStartError") {
            return "La cámara está en uso por otra aplicación. Ciérrala e inténtalo de nuevo.";
        }
        if (name === "OverconstrainedError" || name === "ConstraintNotSatisfiedError") {
            return "No se pudo iniciar la cámara con la configuración solicitada.";
        }
        return "No fue posible acceder a la cámara. Revisa permisos del navegador.";
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
            captureButton.disabled = true;

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

            const enableCapture = () => {
                captureButton.disabled = false;
            };
            video.addEventListener("loadedmetadata", enableCapture, { once: true });
            video.play().catch(() => {
                // Ignore play race errors; capture button is enabled on metadata.
            });

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
