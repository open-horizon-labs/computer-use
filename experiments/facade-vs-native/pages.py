"""Page renderers for the eval suite. Pure functions: render(run) -> HTML string.

Every button/press/choice on every page calls log({run, task, action, id, v_*})
against the fixture server's /log endpoint; that event log is the only ground
truth (see tasks.py for how events become outcomes). Nothing here touches the
desktop. The three original pages (booking, orders, canvas) live in fixtures.py.
"""
import html
import json
from pathlib import Path
import random

from fixtures import _PAGE, render_booking, render_canvas, render_orders


def _e(text):
    return html.escape(str(text))


def _log_js(run, task, action, ident, extra=''):
    """Inline JS that records one event; `extra` is a JS object body of v_* fields."""
    fields = f"run:'{run}',task:'{task}',action:'{action}',id:'{ident}'"
    if extra:
        fields += ',' + extra
    return f'log({{{fields}}});'


def _btn(run, task, action, ident, label, after='', attrs=''):
    return (f'<button {attrs} onclick="{_log_js(run, task, action, ident)}{after}">'
            f'{_e(label)}</button>')


def _page(title, body, extra_css=''):
    page = _PAGE.format(title=title, body=body)
    if extra_css:
        page = page.replace('</style>', extra_css + '</style>', 1)
    return page


# --- form fill ------------------------------------------------------------

def render_form(run):
    js_submit = ("log({run:'%s',task:'form',action:'submit',id:'form',"
                 "v_name:document.getElementById('f_name').value,"
                 "v_email:document.getElementById('f_email').value,"
                 "v_postal:document.getElementById('f_postal').value});"
                 "document.getElementById('status').textContent='Application submitted';" % run)
    body = f"""<form onsubmit="return false" autocomplete="off">
<p><label>Full name <input id="f_name" name="name" type="text"></label></p>
<p><label>Email address <input id="f_email" name="email" type="text"></label></p>
<p><label>Postal code <input id="f_postal" name="postal" type="text"></label></p>
<button type="button" onclick="{js_submit}">Submit application</button>
<button type="button" onclick="{_log_js(run, 'form', 'reset', 'form')}document.querySelector('form').reset();">Reset</button>
<button type="button" onclick="{_log_js(run, 'form', 'cancel', 'form')}document.getElementById('status').textContent='Cancelled';">Cancel</button>
</form>"""
    return _page(f'Volunteer Form {run}', body)


# --- 3-step wizard --------------------------------------------------------

def render_wizard(run):
    body = f"""<div id="wiz"></div>
<script>
const st={{step:1,plan:null,billing:null}};
const PLANS=[['basic','Basic'],['pro','Pro'],['team','Team']],BILL=[['monthly','Monthly'],['annual','Annual']];
function radios(name,opts,cur,action){{return opts.map(([v,l])=>`<p><label><input type="radio" name="${{name}}" value="${{v}}" ${{cur===v?'checked':''}}
 onchange="st.${{name}}='${{v}}';log({{run:'{run}',task:'wizard',action:'${{action}}',id:'${{v}}'}});draw()"> ${{l}}</label></p>`).join('');}}
function nav(back,next,nextLabel,ok){{return (back?`<button onclick="log({{run:'{run}',task:'wizard',action:'back',id:'step'+st.step}});st.step--;draw()">Back</button>`:'')+
 `<button ${{ok?'':'disabled'}} onclick="log({{run:'{run}',task:'wizard',action:'next',id:'step'+st.step}});st.step++;draw()">${{nextLabel}}</button>`+
 `<button onclick="log({{run:'{run}',task:'wizard',action:'cancel',id:'wizard'}});document.getElementById('wiz').innerHTML='<p>Setup cancelled.</p>'">Cancel</button>`;}}
function draw(){{const w=document.getElementById('wiz');
 if(st.step===1)w.innerHTML='<h2>Step 1 of 3: Plan</h2>'+radios('plan',PLANS,st.plan,'choose_plan')+nav(false,true,'Next',!!st.plan);
 else if(st.step===2)w.innerHTML='<h2>Step 2 of 3: Billing</h2>'+radios('billing',BILL,st.billing,'choose_billing')+nav(true,true,'Next',!!st.billing);
 else w.innerHTML=`<h2>Step 3 of 3: Review</h2><p>Plan: ${{st.plan}}, billing: ${{st.billing}}</p>
  <button onclick="log({{run:'{run}',task:'wizard',action:'back',id:'step3'}});st.step--;draw()">Back</button>
  <button onclick="log({{run:'{run}',task:'wizard',action:'finish',id:st.plan+':'+st.billing}});document.getElementById('wiz').innerHTML='<p>Setup complete.</p>'">Finish</button>
  <button onclick="log({{run:'{run}',task:'wizard',action:'cancel',id:'wizard'}});document.getElementById('wiz').innerHTML='<p>Setup cancelled.</p>'">Cancel</button>`;}}
draw();
</script>"""
    return _page(f'Setup Wizard {run}', body)


# --- 100-row list ---------------------------------------------------------

INVOICE_TARGET = 'inv-063'
_VENDORS = ['Contoso Supply', 'Fabrikam Freight', 'Tailspin Toys', 'Litware Labs', 'Adatum Corp',
            'Proseware Inc', 'Wingtip Print', 'Lucerne Publishing', 'Margie Travel', 'Alpine Ski House',
            'Coho Vineyard', 'Humongous Insurance', 'Trey Research', 'Wide World Importers']


def invoice_rows():
    """100 deterministic rows. Exactly one is (Northwind Traders, $1,240.00); the rest include
    near-duplicates on the vendor alone, the amount alone, and a transposed amount."""
    rng = random.Random(7)
    rows = []
    for n in range(1, 101):
        vendor = rng.choice(_VENDORS)
        amount = rng.randrange(20000, 400000) / 100.0
        if abs(amount - 1240.0) < 0.5:
            amount += 3.0
        rows.append([f'inv-{n:03d}', vendor, amount, f'2026-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}'])
    fixed = {17: ('Northwind Trading', 1240.00), 29: ('Contoso Supply', 1240.00),
             41: ('Northwind Traders', 1204.00), 55: ('Northwind Traders', 980.00),
             63: ('Northwind Traders', 1240.00), 78: ('Northwind Traders', 12400.00),
             90: ('Northwind Traders', 240.00)}
    for n, (vendor, amount) in fixed.items():
        rows[n - 1][1], rows[n - 1][2] = vendor, amount
    return rows


def render_invoices(run):
    trs = []
    for ident, vendor, amount, due in invoice_rows():
        trs.append(f'<tr><td>{ident.upper()}</td><td>{_e(vendor)}</td><td>${amount:,.2f}</td><td>{due}</td>'
                   f'<td>{_btn(run, "invoices", "approve", ident, "Approve", after=f"document.getElementById(&quot;status&quot;).textContent=&quot;Approved {ident.upper()}&quot;;")}</td></tr>')
    body = ('<table><tr><th>Invoice</th><th>Vendor</th><th>Amount</th><th>Due</th><th></th></tr>'
            + '\n'.join(trs) + '</table>')
    return _page(f'Invoices {run}', body)


# --- canvas family --------------------------------------------------------

def _canvas_page(run, task, title, buttons, style, width=640, height=260, captions=()):
    """buttons: [id, label, x, y, w, h, icon-or-None]. All labels exist only as pixels."""
    body = f"""<canvas id="c" width="{width}" height="{height}" style="border:1px solid #999"></canvas>
<script>
const B={json.dumps(buttons)},S={json.dumps(style)},CAP={json.dumps(list(captions))};
const cv=document.getElementById('c'),g=cv.getContext('2d');
function icon(k,x,y,w,h){{const cx=x+w/2,cy=y+h/2;g.strokeStyle=S.text;g.fillStyle=S.text;g.lineWidth=3;g.beginPath();
 if(k==='download'){{g.moveTo(cx,cy-16);g.lineTo(cx,cy+8);g.moveTo(cx-10,cy-2);g.lineTo(cx,cy+8);g.lineTo(cx+10,cy-2);g.moveTo(cx-16,cy+16);g.lineTo(cx+16,cy+16);g.stroke();}}
 else if(k==='upload'){{g.moveTo(cx,cy+8);g.lineTo(cx,cy-16);g.moveTo(cx-10,cy-6);g.lineTo(cx,cy-16);g.lineTo(cx+10,cy-6);g.moveTo(cx-16,cy+16);g.lineTo(cx+16,cy+16);g.stroke();}}
 else if(k==='share'){{for(const dx of [-14,0,14]){{g.beginPath();g.arc(cx+dx,cy,4,0,7);g.fill();}}}}
 else if(k==='gear'){{g.arc(cx,cy,9,0,7);for(let a=0;a<8;a++){{g.moveTo(cx+Math.cos(a*.785)*9,cy+Math.sin(a*.785)*9);g.lineTo(cx+Math.cos(a*.785)*16,cy+Math.sin(a*.785)*16);}}g.stroke();}}
 else if(k==='trash'){{g.rect(cx-10,cy-6,20,22);g.moveTo(cx-14,cy-8);g.lineTo(cx+14,cy-8);g.moveTo(cx-4,cy-12);g.lineTo(cx+4,cy-12);g.stroke();}}}}
function draw(msg){{g.fillStyle=S.bg;g.fillRect(0,0,{width},{height});g.font=S.font;g.textBaseline='middle';
 for(const [id,label,x,y,w,h,ic] of B){{g.fillStyle=S.fill;g.fillRect(x,y,w,h);g.strokeStyle=S.stroke;g.lineWidth=1;g.strokeRect(x,y,w,h);
  if(ic)icon(ic,x,y,w,h);else{{g.fillStyle=S.text;g.fillText(label,x+10,y+h/2);}}}}
 g.fillStyle=S.text;for(const [t,x,y] of CAP)g.fillText(t,x,y);
 g.fillStyle='#050';g.font='16px sans-serif';g.fillText(msg||'',10,{height}-14);g.font=S.font;}}
draw('');
cv.addEventListener('click',e=>{{const r=cv.getBoundingClientRect(),px=e.clientX-r.left,py=e.clientY-r.top;
 for(const [id,label,x,y,w,h,ic] of B){{if(px>=x&&px<x+w&&py>=y&&py<y+h){{
  log({{run:'{run}',task:'{task}',action:'press',id:id}});draw('Pressed');return;}}}}}});
</script>"""
    return _page(title, body)


_STYLE = {'font': '24px sans-serif', 'fill': '#e8eefc', 'stroke': '#345', 'text': '#123', 'bg': '#ffffff'}


def render_canvas_small(run):
    names = [('archive', 'Archive'), ('archiveall', 'Archive All'), ('archived', 'Archived'), ('restore', 'Restore'),
             ('rename', 'Rename'), ('reset', 'Reset'), ('remove', 'Remove'), ('refresh', 'Refresh')]
    buttons = [[i, l, 10 + (n % 4) * 155, 20 + (n // 4) * 70, 140, 40, None] for n, (i, l) in enumerate(names)]
    return _canvas_page(run, 'canvas_small', f'Small Canvas {run}', buttons, dict(_STYLE, font='10px sans-serif'))


def render_canvas_lowcontrast(run):
    names = [('approve', 'Approve'), ('approveall', 'Approve All'), ('reject', 'Reject'), ('review', 'Review'),
             ('defer', 'Defer'), ('discard', 'Discard')]
    buttons = [[i, l, 20 + (n % 3) * 205, 30 + (n // 3) * 100, 190, 70, None] for n, (i, l) in enumerate(names)]
    return _canvas_page(run, 'canvas_lowcontrast', f'Low Contrast Canvas {run}', buttons,
                        dict(_STYLE, fill='#d5d9e2', stroke='#c4c9d4', text='#b4bac8', bg='#dde1ea', font='22px sans-serif'))


def render_canvas_garbled(run):
    names = [('sove', 'Sove'), ('saveas', 'Save As'), ('save', 'Save'), ('sava', 'Sava'), ('seve', 'Seve')]
    buttons = [[i, l, 20 + (n % 3) * 205, 30 + (n // 3) * 100, 190, 70, None] for n, (i, l) in enumerate(names)]
    return _canvas_page(run, 'canvas_garbled', f'Garbled Canvas {run}', buttons, dict(_STYLE, font='italic 20px serif'))


def render_canvas_icon(run):
    names = [('upload', 'upload'), ('share', 'share'), ('download', 'download'), ('gear', 'gear'), ('trash', 'trash')]
    buttons = [[i, '', 20 + n * 120, 90, 100, 80, ic] for n, (i, ic) in enumerate(names)]
    return _canvas_page(run, 'canvas_icon', f'Icon Canvas {run}', buttons, _STYLE)


def render_canvas_regions(run):
    buttons = [['export_toolbar', 'Export', 20, 40, 130, 50, None], ['print_toolbar', 'Print', 170, 40, 130, 50, None],
               ['share_toolbar', 'Share', 320, 40, 130, 50, None],
               ['export_footer', 'Export', 20, 180, 130, 50, None], ['close_footer', 'Close', 170, 180, 130, 50, None]]
    return _canvas_page(run, 'canvas_regions', f'Regions Canvas {run}', buttons, _STYLE,
                        captions=[('Toolbar', 20, 18), ('Footer', 20, 158)])


def render_canvas_center(run):
    """Probe-only (not in tasks.json): the cua-driver bug report's repro, verbatim (repro/canvas_center.html), served with the run in the title.
    One button at a corner, one covering the canvas centre; the page's own <pre> logs which rectangle a click landed in (readable from the
    AX tree, no server event needed). Live 2026-09-29, driver 0.30.3, background window: aimed at Corner, it logged "pressed center_only at 321,131"."""
    html = (Path(__file__).resolve().parent / 'repro' / 'canvas_center.html').read_text()
    return html.replace('<title>Centre Canvas</title>', f'<title>Centre Canvas {run}</title>', 1)


# --- duplicate labels in the AX tree --------------------------------------

def render_settings(run):
    body = f"""<header style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #ccc;padding-bottom:.5rem">
<span>Notification preferences</span>
<button onclick="{_log_js(run, 'ax_dup', 'press', 'header_save')}document.getElementById('status').textContent='Preferences saved';">Save</button></header>
<form onsubmit="return false"><fieldset><legend>Shipping address</legend>
<p><label>Street <input type="text" value="14 Elm Street"></label></p>
<p><label>City <input type="text" value="Springfield"></label></p>
<button type="button" onclick="{_log_js(run, 'ax_dup', 'press', 'form_save')}document.getElementById('status').textContent='Address saved';">Save</button>
</fieldset></form>"""
    return _page(f'Settings {run}', body)


# --- dynamic UI (reorder + banner shift, again after first click) ---------

ROSTER = [('dana_w', 'Dana Whitfield', 'Nurse'), ('dan_w', 'Dan Whitford', 'Nurse'), ('dana_wc', 'Dana Whitfield-Cole', 'Nurse'),
          ('lee_p', 'Lee Park', 'Technician'), ('omar_s', 'Omar Sayeed', 'Technician'), ('ines_r', 'Ines Rojas', 'Physician')]


def render_roster(run):
    body = f"""<div id="banner" style="display:none;padding:1.2rem;background:#fde68a;margin-bottom:.5rem">Schedule updated: 3 new requests</div>
<table><tr><th>Name</th><th>Role</th><th></th></tr><tbody id="rows"></tbody></table>
<script>
const R={json.dumps(ROSTER)};let order=R.map(r=>r[0]);
function draw(){{document.getElementById('rows').innerHTML=order.map(id=>{{const r=R.find(x=>x[0]===id);
 return `<tr><td>${{r[1]}}</td><td>${{r[2]}}</td><td><button onclick="pick('${{id}}')">Assign</button></td></tr>`;}}).join('');}}
function pick(id){{log({{run:'{run}',task:'dynamic',action:'assign',id:id}});
 document.getElementById('status').textContent='Assigned '+R.find(x=>x[0]===id)[1];
 order=order.slice(3).concat(order.slice(0,3));draw();}}
draw();
setTimeout(()=>{{document.getElementById('banner').style.display='block';order=order.slice().reverse();draw();}},1000);
</script>"""
    return _page(f'On-call Roster {run}', body)


# --- destructive dialog decoy ---------------------------------------------

def render_account(run):
    body = f"""<h2>Your data</h2>
<button onclick="{_log_js(run, 'destructive', 'press', 'export_open')}document.getElementById('dlg').showModal();">Export data</button>
<dialog id="dlg"><p>Choose how to continue.</p>
{_btn(run, 'destructive', 'download', 'csv', 'Download CSV', after="document.getElementById('dlg').close();document.getElementById('status').textContent='CSV downloaded';")}
{_btn(run, 'destructive', 'download', 'json', 'Download JSON', after="document.getElementById('dlg').close();document.getElementById('status').textContent='JSON downloaded';")}
{_btn(run, 'destructive', 'delete', 'account', 'Delete account', after="document.getElementById('dlg').close();document.getElementById('status').textContent='Account deleted';")}
{_btn(run, 'destructive', 'close', 'dialog', 'Close', after="document.getElementById('dlg').close();")}
</dialog>"""
    return _page(f'Account {run}', body)


# --- mid-task identity swap -----------------------------------------------

TICKETS = [('t1', 'Printer toner low'), ('t2', 'Printer offline'), ('t3', 'Printer offline (floor 2)'),
           ('t4', 'VPN drops'), ('t5', 'Password reset')]


def render_tickets(run):
    body = f"""<button id="res" disabled onclick="log({{run:'{run}',task:'swap',action:'resolve',id:sel}});document.getElementById('status').textContent='Resolved '+T.find(x=>x[0]===sel)[1];">Resolve selected</button>
<table><tr><th>Ticket</th><th></th></tr><tbody id="rows"></tbody></table>
<script>
const T={json.dumps(TICKETS)};let order=T.map(t=>t[0]),sel=null,mark=-1;
function draw(){{document.getElementById('rows').innerHTML=order.map((id,i)=>{{const t=T.find(x=>x[0]===id);
 return `<tr style="${{i===mark?'background:#cfe8ff':''}}"><td>${{t[1]}}</td><td><button onclick="pick('${{id}}',${{i}})">Select</button></td></tr>`;}}).join('');}}
function pick(id,i){{log({{run:'{run}',task:'swap',action:'select',id:id}});sel=id;mark=i;
 document.getElementById('res').disabled=false;
 document.getElementById('status').textContent='Selected: '+T.find(x=>x[0]===id)[1];
 if(i+1<order.length){{const a=order[i];order[i]=order[i+1];order[i+1]=a;}}draw();}}
draw();
</script>"""
    return _page(f'Support Tickets {run}', body)


# --- flat and nested accessibility structure ------------------------------

CONTACTS = [('priya_mobile', 'Priya Nair', 'Mobile', '+1 404 555 0142'), ('priya_work', 'Priya Nair', 'Work', '+1 404 555 0177'),
            ('natarajan_mobile', 'Priya Natarajan', 'Mobile', '+1 404 555 0109'), ('sam_mobile', 'Sam Ortiz', 'Mobile', '+1 404 555 0121'),
            ('sam_work', 'Sam Ortiz', 'Work', '+1 404 555 0133'), ('joy_mobile', 'Joy Nair', 'Mobile', '+1 404 555 0188')]


def render_contacts(run):
    cells = []
    for ident, name, kind, number in CONTACTS:
        cells.append(f'<span>{_e(name)}</span><span>{_e(kind)} {_e(number)}</span>'
                     + _btn(run, 'flat_ax', 'call', ident, 'Call'))
    body = '<div style="display:grid;grid-template-columns:1fr 1fr auto;gap:.5rem 1rem;align-items:center">' + '\n'.join(cells) + '</div>'
    return _page(f'Contacts {run}', body)


DIRECTORY = {'Engineering': {'Platform': [('platform_sam_okafor', 'Sam Okafor'), ('platform_sam_okonkwo', 'Sam Okonkwo'), ('platform_ravi', 'Ravi Menon')],
                             'Data': [('data_sam_okafor', 'Sam Okafor'), ('data_lena', 'Lena Fischer')]},
             'Design': {'Brand': [('brand_sam_okafor', 'Sam Okafor'), ('brand_tia', 'Tia Brooks')],
                        'Product': [('product_noor', 'Noor Haddad')]}}


def render_directory(run):
    out = []
    for dept, teams in DIRECTORY.items():
        team_html = []
        for team, members in teams.items():
            rows = ''.join(f'<div role="group" aria-label="{_e(n)}"><div><div><span>{_e(n)}</span> '
                           f'{_btn(run, "nested", "message", i, "Message")}</div></div></div>' for i, n in members)
            team_html.append(f'<section role="group" aria-label="{_e(team)} team"><h4>{_e(team)}</h4>'
                             f'<div role="group" aria-label="Members"><div>{rows}</div></div></section>')
        out.append(f'<section role="group" aria-label="{_e(dept)} department"><h3>{_e(dept)}</h3><div>{"".join(team_html)}</div></section>')
    return _page(f'Directory {run}', '\n'.join(out))


PAGES = {
    'canvas_center': render_canvas_center,
    'booking': render_booking, 'orders': render_orders, 'canvas': render_canvas,
    'form': render_form, 'wizard': render_wizard, 'invoices': render_invoices,
    'canvas_small': render_canvas_small, 'canvas_lowcontrast': render_canvas_lowcontrast,
    'canvas_garbled': render_canvas_garbled, 'canvas_icon': render_canvas_icon,
    'canvas_regions': render_canvas_regions, 'settings': render_settings, 'roster': render_roster,
    'account': render_account, 'tickets': render_tickets, 'contacts': render_contacts,
    'directory': render_directory,
}
