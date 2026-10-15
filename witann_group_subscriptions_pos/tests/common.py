"""Fixtures for the native Odoo 19 Enterprise recurring-price schema."""


def create_recurring_price(env, product, plan, amount):
    return env['product.pricelist.item'].create({
        'pricelist_id': False,
        'applied_on': '1_product',
        'product_tmpl_id': product.product_tmpl_id.id,
        'plan_id': plan.id,
        'compute_price': 'fixed',
        'fixed_price': amount,
    })
