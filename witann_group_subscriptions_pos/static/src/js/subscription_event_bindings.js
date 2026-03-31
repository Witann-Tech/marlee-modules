/** @odoo-module **/

function bindActionMap(root, actions) {
    root.addEventListener("click", async (event) => {
        const actionButton = event.target.closest("[data-action]");
        if (!actionButton) {
            return;
        }
        const action = actionButton.dataset.action;
        const handler = actions[action];
        if (!handler) {
            return;
        }
        await handler({ event, actionButton, action });
    });
}

function bindFieldChange(root, handler) {
    root.addEventListener("change", async (event) => {
        const field = event.target.dataset.field;
        if (!field) {
            return;
        }
        await handler({ event, field, target: event.target });
    });
}

function bindFieldInput(root, handler) {
    root.addEventListener("input", (event) => {
        const field = event.target.dataset.field;
        if (!field) {
            return;
        }
        handler({ event, field, target: event.target });
    });
}

export {
    bindActionMap,
    bindFieldChange,
    bindFieldInput,
};
