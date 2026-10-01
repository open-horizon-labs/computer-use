"""Fixture pages for the surfaces A/B. Booking and orders are reused unchanged from ../facade-vs-native/fixtures.py
(loaded by path: both directories have modules with the same names). New pages: intake form, upload, product compare.

Every page reports to the loopback server (server.py) and that event log is the only ground truth for the local
web jobs; nothing here operates the desktop. Answers live only in this file and tasks.py, never in a prompt.
"""
import html
import importlib.util
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / 'facade-vs-native' / 'fixtures.py'
_spec = importlib.util.spec_from_file_location('fvn_fixtures', _SRC)
fvn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fvn)

_PAGE = fvn._PAGE
BOOKING_EXPECTED_ID = fvn.BOOKING_EXPECTED_ID
ORDERS_EXPECTED_ID = fvn.ORDERS_EXPECTED_ID

# --- intake form -------------------------------------------------------------
FORM_VALUES = {  # what the person asks to be entered (the prompt states these; tasks.py scores the submission)
    'name': 'Dana Whitfield', 'email': 'dana.whitfield@example.com', 'phone': '555-0142',
    'department': 'billing', 'copy': 'yes', 'message': 'Invoice 4471 was charged twice in September.',
}
DEPARTMENTS = [('sales', 'Sales'), ('support', 'Support'), ('billing', 'Billing'), ('other', 'Other')]


def render_form(run):
    run = html.escape(run)
    options = ''.join('<option value="%s">%s</option>' % (v, label) for v, label in DEPARTMENTS)
    js = ("log({run:'%s',task:'form',action:'submit',id:'intake',"
          "v_name:document.getElementById('f_name').value.trim(),"
          "v_email:document.getElementById('f_email').value.trim(),"
          "v_phone:document.getElementById('f_phone').value.trim(),"
          "v_department:document.getElementById('f_dept').value,"
          "v_copy:document.getElementById('f_copy').checked?'yes':'no',"
          "v_message:document.getElementById('f_msg').value.trim()});"
          "document.getElementById('status').textContent='Request received';" % run)
    body = f"""<form onsubmit="return false" autocomplete="off">
<p><label>Full name <input id="f_name" name="name" type="text"></label></p>
<p><label>Email address <input id="f_email" name="email" type="text"></label></p>
<p><label>Phone number <input id="f_phone" name="phone" type="text"></label></p>
<p><label>Department <select id="f_dept" name="department"><option value="">Choose one</option>{options}</select></label></p>
<p><label><input id="f_copy" name="copy" type="checkbox"> Email me a copy of this request</label></p>
<p><label>How can we help? <br><textarea id="f_msg" name="message" rows="4" cols="50"></textarea></label></p>
<button type="button" onclick="{js}">Send request</button>
<button type="button" onclick="log({{run:'{run}',task:'form',action:'cancel',id:'intake'}});document.getElementById('status').textContent='Cancelled';">Cancel</button>
</form>"""
    return _PAGE.format(title=f'Intake Form {run}', body=body)


# --- upload ------------------------------------------------------------------
def render_upload(run):
    run = html.escape(run)
    body = f"""<form onsubmit="return false">
<p><label>Attachment <input id="attachment" name="attachment" type="file"></label></p>
<button type="button" onclick="sendUpload()">Send request</button>
</form>
<script>
async function sendUpload(){{
  const f=document.getElementById('attachment').files[0];
  const st=document.getElementById('status');
  if(!f){{st.textContent='Choose a file first';return;}}
  const fd=new FormData();fd.append('attachment',f,f.name);
  try{{const r=await fetch('/upload?run={run}&task=upload',{{method:'POST',body:fd}});
    st.textContent=r.ok?'Request sent with attachment: '+f.name+' ('+f.size+' bytes)':'Upload failed';}}
  catch(e){{st.textContent='Upload failed';}}
}}
</script>"""
    return _PAGE.format(title=f'Support Request {run}', body=body)


# --- product compare -----------------------------------------------------------
# slug, name, price, in_stock. Cheapest overall is out of stock; the cheapest IN STOCK item is the answer.
PRODUCTS = [
    ('a', 'Halden Task Lamp', 42.00, True, 'Adjustable arm, warm white.'),
    ('b', 'Marlow Banker Lamp', 29.00, False, 'Green glass shade.'),
    ('c', 'Quillon Arc Lamp', 36.75, True, 'Floor-standing, brass finish.'),
]
COMPARE_ANSWER = {'name': 'Quillon Arc Lamp', 'price': '36.75'}
COMPARE_DECOY_PRICES = ['42.00', '29.00']
COMPARE_DECOY_NAMES = ['Halden Task Lamp', 'Marlow Banker Lamp']


def render_shop(run):
    run = html.escape(run)
    items = ''.join('<li><a href="/product/%s?run=%s">%s</a></li>' % (slug, run, html.escape(name)) for slug, name, *_ in PRODUCTS)
    body = f'<p>Desk and floor lamps.</p><ul>{items}</ul>'
    return _PAGE.format(title=f'Lamp Shop {run}', body=body)


def render_product(run, slug):
    run = html.escape(run)
    for s, name, price, in_stock, blurb in PRODUCTS:
        if s == slug:
            stock = 'In stock' if in_stock else 'Out of stock'
            body = (f'<p class="price">${price:,.2f}</p><p class="stock">{stock}</p><p>{html.escape(blurb)}</p>'
                    f'<p><a href="/shop?run={run}">Back to all lamps</a></p>'
                    f"<script>log({{run:'{run}',task:'compare',action:'view',id:'{s}'}});</script>")
            return _PAGE.format(title=f'{html.escape(name)} {run}', body=body)
    return None


def page_for(route, run):
    """HTML for a route like 'booking' or 'product/c', or None."""
    if route == 'booking':
        return fvn.render_booking(run)
    if route == 'orders':
        return fvn.render_orders(run)
    simple = {'form': render_form, 'upload': render_upload, 'shop': render_shop}
    if route in simple:
        return simple[route](run)
    if route.startswith('product/'):
        return render_product(run, route.split('/', 1)[1])
    return None
