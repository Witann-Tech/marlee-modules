/** @odoo-module **/

function isAuthorizationOnlyOffer(offer) {
    if (!offer) {
        return false;
    }
    return !Number(offer.discount_percent || 0) && !Number(offer.discount_fixed_amount || 0);
}

function getAuthorizationOnlyOffer(form) {
    const offers = Array.isArray(form && form.discountOffers) ? form.discountOffers : [];
    if (offers.length !== 1) {
        return null;
    }
    return isAuthorizationOnlyOffer(offers[0]) ? offers[0] : null;
}

function getAuthorizedDiscountPercent(form) {
    return Number(
        form
        && form.authorizedDiscount
        && form.authorizedDiscount.discountPercent !== undefined
            ? form.authorizedDiscount.discountPercent
            : 0
    ) || 0;
}

function getDiscountedDisplayAmount(charge, form) {
    const displayAmount = Number(
        charge && charge.displayAmount !== undefined
            ? charge.displayAmount
            : 0
    ) || 0;
    const percent = getAuthorizedDiscountPercent(form);
    if (!percent) {
        return displayAmount;
    }
    return displayAmount * (1 - (percent / 100));
}

function renderDiscountAuthorizationSection({
    form,
    formError,
    escapeHtml,
    formatMoney,
    authorizeAction,
    codeField,
    pinField,
    _t,
}) {
    if (!form) {
        return "";
    }
    const offers = Array.isArray(form.discountOffers) ? form.discountOffers : [];
    if (!offers.length) {
        return "";
    }
    const authorizationOnlyOffer = getAuthorizationOnlyOffer(form);
    if (authorizationOnlyOffer) {
        const authorized = Boolean(
            form.authorizedDiscount
            && String(form.authorizedDiscount.code || "") === String(authorizationOnlyOffer.code || "")
        );
        const authMessage = authorized && form.authorizedDiscount
            ? _t("Autorizado por %s").replace("%s", form.authorizedDiscount.authorizedBy || "-")
            : "";
        return `
            <div class="wgs-inline-discount-card">
                <div class="wgs-inline-section-title">${escapeHtml(authorizationOnlyOffer.label || _t("Autorización supervisor"))}</div>
                <div class="wgs-inline-form-grid">
                    <label>
                        <span>${escapeHtml(_t("PIN supervisor"))}</span>
                        <input type="password" data-field="${escapeHtml(pinField)}" value="${escapeHtml(form.supervisorPin || "")}" />
                    </label>
                </div>
                ${authorized ? `
                    <div class="wgs-inline-notice wgs-inline-notice-compact">${escapeHtml(authMessage)}</div>
                ` : ""}
                ${!authorized ? `
                    <div class="wgs-inline-actions">
                        <button type="button" class="wgs-secondary-action-btn" data-action="${escapeHtml(authorizeAction)}">${escapeHtml(_t("Autorizar venta"))}</button>
                    </div>
                ` : ""}
                ${!authorized && !formError ? `
                    <div class="wgs-inline-note">${escapeHtml(_t("Debes autorizar esta venta antes de agregarla al ticket."))}</div>
                ` : ""}
            </div>
        `;
    }
    const options = offers.map((offer) => {
        const code = String(offer.code || "");
        const selected = code === String(form.selectedDiscountCode || "") ? "selected" : "";
        return `<option value="${escapeHtml(code)}" ${selected}>${escapeHtml(offer.label || code)}</option>`;
    }).join("");
    const selectedCode = String(form.selectedDiscountCode || "");
    const hasSelectedOffer = Boolean(selectedCode);
    const authorized = Boolean(form.authorizedDiscount && form.authorizedDiscount.code === selectedCode);
    const authorizedLabel = authorized && form.authorizedDiscount
        ? `${form.authorizedDiscount.label || selectedCode} | ${formatMoney(getDiscountedDisplayAmount(form.charge, form))}`
        : "";
    const authMessage = authorized && form.authorizedDiscount
        ? _t("Autorizado por %s").replace("%s", form.authorizedDiscount.authorizedBy || "-")
        : "";

    return `
        <div class="wgs-inline-discount-card">
            <div class="wgs-inline-section-title">${escapeHtml(_t("Beneficio autorizado"))}</div>
            <div class="wgs-inline-form-grid">
                <label>
                    <span>${escapeHtml(_t("Beneficio"))}</span>
                    <select data-field="${escapeHtml(codeField)}">
                        <option value="">${escapeHtml(_t("Sin descuento"))}</option>
                        ${options}
                    </select>
                </label>
                ${hasSelectedOffer ? `
                    <label>
                        <span>${escapeHtml(_t("PIN supervisor"))}</span>
                        <input type="password" data-field="${escapeHtml(pinField)}" value="${escapeHtml(form.supervisorPin || "")}" />
                    </label>
                ` : ""}
            </div>
            ${authorized ? `
                <div class="wgs-inline-notice wgs-inline-notice-compact">
                    ${escapeHtml(authMessage)}
                    <br/>
                    ${escapeHtml(authorizedLabel)}
                </div>
            ` : ""}
            ${hasSelectedOffer && !authorized ? `
                <div class="wgs-inline-actions">
                    <button type="button" class="wgs-secondary-action-btn" data-action="${escapeHtml(authorizeAction)}">${escapeHtml(_t("Autorizar descuento"))}</button>
                </div>
            ` : ""}
            ${hasSelectedOffer && !authorized && !formError ? `
                <div class="wgs-inline-note">${escapeHtml(_t("Debes autorizar el descuento antes de agregarlo al ticket."))}</div>
            ` : ""}
        </div>
    `;
}

export {
    getAuthorizedDiscountPercent,
    getDiscountedDisplayAmount,
    getAuthorizationOnlyOffer,
    renderDiscountAuthorizationSection,
};
