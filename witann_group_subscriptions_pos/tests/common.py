"""Fixtures for the native Odoo 19 Enterprise recurring-price schema."""


def create_recurring_price(env, product, plan, amount):
    return env['product.pricelist.item'].sudo().create({
        'pricelist_id': False,
        'applied_on': '1_product',
        'product_tmpl_id': product.product_tmpl_id.id,
        'plan_id': plan.id,
        'compute_price': 'fixed',
        'fixed_price': amount,
    })


def create_tax(env, values):
    """Configure VAT as an administrator, without assuming demo tax groups."""
    company_id = values.get('company_id') or env.company.id
    group = env['account.tax.group'].sudo().create({
        'name': 'WGS QA VAT group', 'company_id': company_id,
    })
    country = env['res.company'].sudo().browse(company_id).account_fiscal_country_id or env.ref('base.us')
    return env['account.tax'].sudo().create({
        **values, 'tax_group_id': group.id, 'country_id': country.id,
    })
