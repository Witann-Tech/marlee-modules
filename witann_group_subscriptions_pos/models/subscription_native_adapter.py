"""Explicit writes to the supported Odoo 19 subscription schema."""

from odoo import Command, models


class PosSubscriptionNativeAdapter(models.Model):
    _inherit = 'pos.order'

    def _wgs_build_subscription_recurring_line_values_for_pos(
        self, *, pos_line, product, qty, recurring_price_unit,
    ):
        # Plan belongs to sale.order. Its related field on the line is read-only.
        # Authorized discounts belong to the POS event, never the recurring price.
        return {
            'product_id': product.id,
            'name': pos_line.full_product_name or product.display_name,
            'product_uom_qty': qty,
            'product_uom_id': product.uom_id.id,
            'price_unit': recurring_price_unit,
            'discount': 0.0,
        }

    def _wgs_sync_subscription_metadata(
        self, sale_order, participant_ids=None, contract_date=False,
        subscription_start_date=False, subscription_end_date=False,
        next_billing_date=False, clear_next_billing_date=False,
        recurring_plan_id=False, monthly_cutoff_day=None,
    ):
        """Update the contracted order only, never its historical relatives."""
        sale_order.ensure_one()
        values = {}
        if participant_ids is not None:
            values['participant_ids'] = [Command.set(participant_ids)]
        if contract_date:
            values['date_order'] = self._wgs_convert_date_for_field_value(
                contract_date, sale_order._fields['date_order'],
            )
        if subscription_start_date:
            values.update(start_date=subscription_start_date, wgs_effective_start_date=subscription_start_date)
        if subscription_end_date:
            values['end_date'] = subscription_end_date
        if next_billing_date:
            values['next_invoice_date'] = next_billing_date
        elif clear_next_billing_date:
            values['next_invoice_date'] = False
        if recurring_plan_id:
            values['plan_id'] = self._wgs_to_int(recurring_plan_id)
        if monthly_cutoff_day is not None:
            values['wgs_monthly_cutoff_day'] = monthly_cutoff_day
        if values:
            sale_order.write(values)

    def _wgs_clear_subscription_next_billing_date(self, sale_order):
        sale_order.ensure_one()
        sale_order.write({'next_invoice_date': False})
