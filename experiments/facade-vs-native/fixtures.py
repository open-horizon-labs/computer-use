"""Static fixture data and HTML rendering for the facade-vs-native A/B harness.

Two pages: a booking list (12 repeated <li> records, identical "Book"
buttons -- the shape that broke semantic/visual choice in the 2026-09-28
run) and an orders table (Track/Cancel + a confirm step). Every button GETs
/log?run=..&task=..&action=..&id=.. against the harness server in server.py;
that log is the ground truth score.py compares agent behavior against, not
anything Claude or the fixture page asserts about itself.

Expected answers (kept here, next to the fixture data, so score.py and the
runner's prompts read the same source of truth):
  booking -> book s10 only (Dr. Morgan Reyes, Telehealth, "half-hour", 3:00 PM)
             decoy: s07, Dr. Morgan Reyes, Follow-up, 30 min, 3:15 PM
  orders  -> cancel_request + cancel_confirm on 1044 only, nothing else
"""
import html

BOOKING_EXPECTED_ID = 's10'
ORDERS_EXPECTED_ID = '1044'

# id, provider, service, duration, start, note
BOOKING_SLOTS = [
    ('s01', 'Dr. Morgan Reyes', 'Consultation', '60 min', '1:30 PM', None),
    ('s02', 'Morgan Lee, NP', 'Follow-up', '30 min', '2:00 PM', None),
    ('s03', 'Dr. Priya Shah', 'Follow-up', '30 min', '2:15 PM', 'Covering for Dr. Morgan Reyes'),
    ('s04', 'Dr. Morgan Reyes', 'Consultation', '45 min', '2:30 PM', None),
    ('s05', 'Dr. Morgan Reyes', 'Follow-up', '30 min', '1:45 PM', None),
    ('s06', 'Dr. Morgan Reyesford', 'Follow-up', '30 min', '2:45 PM', None),
    ('s07', 'Dr. Morgan Reyes', 'Follow-up', '30 min', '3:15 PM', None),
    ('s08', 'Dr. Morgan Reyes', 'Follow-up', '30 min', '4:00 PM', None),
    ('s09', 'Dr. Alan Morgan', 'Follow-up', '30 min', '2:05 PM', None),
    ('s10', 'Dr. Morgan Reyes', 'Telehealth', 'half-hour', '3:00 PM', 'Video visit'),
    ('s11', 'Dr. Morgan Reyes', 'Follow-up', '30 min', '11:00 AM', None),
    ('s12', 'Dr. Kim Ortega', 'Consultation', '30 min', '2:20 PM', None),
]

# id, item, status
ORDERS_ROWS = [
    ('1041', 'Walnut desk lamp', 'Shipped'),
    ('1042', 'Walnut floor lamp', 'Processing'),
    ('1043', 'Brass desk lamp', 'Processing'),
    ('1044', 'Walnut desk lamp', 'Processing'),
    ('1045', 'Walnut desk organizer', 'Processing'),
    ('1046', 'Walnut desk lamp shade (replacement)', 'Processing'),
    ('1047', 'Walnut desk lamp', 'Delivered'),
]

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:sans-serif;max-width:640px;margin:2rem auto}}
li{{border:1px solid #ccc;border-radius:6px;padding:.75rem;margin:.5rem 0;list-style:none}}
table{{width:100%;border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:.5rem;text-align:left}}
button{{margin-left:.5rem}}dialog{{border-radius:8px}}</style></head>
<body><h1>{title}</h1>
{body}
<div role="status" id="status" aria-live="polite"></div>
<script>
function log(params){{
  const q=new URLSearchParams(params);
  fetch('/log?'+q.toString()).catch(()=>{{}});
}}
</script>
</body></html>"""


def render_booking(run):
    run = html.escape(run)
    items = []
    for sid, provider, service, duration, start, note in BOOKING_SLOTS:
        note_html = f'<div class="note">{html.escape(note)}</div>' if note else ''
        items.append(f"""<li aria-label="Slot {sid}">
  <div class="provider">{html.escape(provider)}</div>
  <div class="service">{html.escape(service)}</div>
  <div class="duration">{html.escape(duration)}</div>
  <div class="start">Starts {html.escape(start)}</div>
  {note_html}
  <button onclick="log({{run:'{run}',task:'booking',action:'book',id:'{sid}'}});
    document.getElementById('status').textContent='Booked: {html.escape(provider)}, {html.escape(duration)}, {html.escape(start)}';">Book</button>
</li>""")
    return _PAGE.format(title=f'Clinic Slots {run}', body='<ul>' + '\n'.join(items) + '</ul>')


def render_orders(run):
    run = html.escape(run)
    rows = []
    for oid, item, status in ORDERS_ROWS:
        rows.append(f"""<tr>
  <td>#{oid}</td><td>{html.escape(item)}</td><td>{html.escape(status)}</td>
  <td>
    <button onclick="log({{run:'{run}',task:'orders',action:'track',id:'{oid}'}});
      document.getElementById('status').textContent='Tracking #{oid}';">Track</button>
    <button onclick="log({{run:'{run}',task:'orders',action:'cancel_request',id:'{oid}'}});
      document.getElementById('confirm-{oid}').showModal();">Cancel</button>
  </td>
</tr>
<dialog id="confirm-{oid}">
  <p>Cancel order #{oid} ({html.escape(item)})?</p>
  <button onclick="log({{run:'{run}',task:'orders',action:'cancel_confirm',id:'{oid}'}});
    document.getElementById('confirm-{oid}').close();
    document.getElementById('status').textContent='Order #{oid} canceled';">Yes, cancel order</button>
  <button onclick="log({{run:'{run}',task:'orders',action:'keep',id:'{oid}'}});
    document.getElementById('confirm-{oid}').close();">Keep order</button>
</dialog>""")
    table = '<table><tr><th>Order</th><th>Item</th><th>Status</th><th>Actions</th></tr>' + '\n'.join(rows) + '</table>'
    return _PAGE.format(title=f'Orders {run}', body=table)
