/** @odoo-module **/

function normalizeSequences(values) {
    return [...new Set((values || [])
        .map((value) => Number(value || 0))
        .filter((value) => Number.isInteger(value) && value > 0))]
        .sort((left, right) => left - right);
}

function getInstallments(domiciliation) {
    return Array.isArray(domiciliation && domiciliation.installments)
        ? [...domiciliation.installments].sort((left, right) => Number(left.sequence || 0) - Number(right.sequence || 0))
        : [];
}

function getInitialInstallmentRows(installments, selectedSequences) {
    const selected = new Set(selectedSequences);

    return installments.map((installment) => {
        const sequence = Number(installment.sequence || 0);
        const isInitial = sequence === 1;
        return {
            ...installment,
            sequence,
            isSelected: selected.has(sequence),
            isFixed: isInitial,
            isToggleable: !isInitial,
        };
    });
}

function getRenewalInstallmentRows(installments, selectedSequences) {
    const selected = new Set(selectedSequences);
    const paidSequences = new Set(
        installments
            .filter((installment) => installment.state === "paid")
            .map((installment) => Number(installment.sequence || 0))
    );
    return installments.map((installment) => {
        const sequence = Number(installment.sequence || 0);
        const isPaid = paidSequences.has(sequence);
        const isSelected = selected.has(sequence);
        return {
            ...installment,
            sequence,
            isSelected: isPaid || isSelected,
            isFixed: isPaid,
            isToggleable: !isPaid && !(isSelected && selectedSequences.length === 1),
        };
    });
}

function getDomiciliationInstallmentRows(domiciliation) {
    const installments = getInstallments(domiciliation);
    const selectedSequences = normalizeSequences(domiciliation && domiciliation.selected_installment_sequences);
    if ((domiciliation && domiciliation.selection_mode) === "renewal") {
        return getRenewalInstallmentRows(installments, selectedSequences);
    }
    return getInitialInstallmentRows(installments, selectedSequences);
}

function getToggledDomiciliationInstallmentSequences(domiciliation, sequence, checked) {
    const installments = getInstallments(domiciliation);
    const targetSequence = Number(sequence || 0);
    const target = installments.find((installment) => Number(installment.sequence || 0) === targetSequence);
    const selected = new Set(normalizeSequences(domiciliation && domiciliation.selected_installment_sequences));
    if (!target) {
        return [...selected].sort((left, right) => left - right);
    }
    if ((domiciliation && domiciliation.selection_mode) === "renewal") {
        if (target.state === "paid") {
            return [...selected].sort((left, right) => left - right);
        }
        const paidSequences = new Set(
            installments
                .filter((installment) => installment.state === "paid")
                .map((installment) => Number(installment.sequence || 0))
        );
        const firstPending = installments.find(
            (installment) => !paidSequences.has(Number(installment.sequence || 0))
        );
        if (!firstPending) {
            return [];
        }
        if (!checked && selected.size === 1 && selected.has(targetSequence)) {
            return [...selected].sort((left, right) => left - right);
        }
        if (checked) {
            for (let current = Number(firstPending.sequence); current <= targetSequence; current += 1) {
                if (!paidSequences.has(current)) {
                    selected.add(current);
                }
            }
        } else {
            for (const selectedSequence of selected) {
                if (selectedSequence >= targetSequence) {
                    selected.delete(selectedSequence);
                }
            }
        }
        return [...selected].sort((left, right) => left - right);
    }

    const termSequence = Number(installments.at(-1)?.sequence || 0);
    if (targetSequence === 1) {
        return [...selected].sort((left, right) => left - right);
    }
    if (checked) {
        if (targetSequence === termSequence && selected.size === 1 && selected.has(1)) {
            return [1, termSequence];
        }
        selected.clear();
        for (let current = 1; current <= targetSequence; current += 1) {
            selected.add(current);
        }
    } else {
        for (const selectedSequence of selected) {
            if (selectedSequence >= targetSequence) {
                selected.delete(selectedSequence);
            }
        }
        selected.add(1);
    }
    return [...selected].sort((left, right) => left - right);
}

export {
    getDomiciliationInstallmentRows,
    getToggledDomiciliationInstallmentSequences,
};
