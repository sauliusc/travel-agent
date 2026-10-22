"""Packing checklist HTML: checkboxes whose state is saved in the browser's
localStorage. Rendered by code and injected into the page at the
<!-- PACKING_LIST --> placeholder so it always works, whatever the Page
Designer's own markup looks like."""

import hashlib
import html

from schemas.packing import PackingList

PLACEHOLDER = "<!-- PACKING_LIST -->"
START, END = "<!-- PACKING_LIST:START -->", "<!-- PACKING_LIST:END -->"

_STYLE = """<style>
.packing-list{margin:8px 0}
.packing-list .pk-meta{opacity:.8;margin:0 0 8px}
.packing-list .pk-tips{margin:0 0 12px;padding-left:18px}
.packing-list .pk-cat{margin:14px 0 6px;font-size:1.05em}
.packing-list ul.pk-items{list-style:none;margin:0;padding:0}
.packing-list li{margin:0;padding:0}
.packing-list label{display:flex;gap:10px;align-items:flex-start;padding:8px 0;cursor:pointer;border-bottom:1px solid rgba(127,127,127,.2)}
.packing-list input[type=checkbox]{width:20px;height:20px;flex-shrink:0;margin-top:2px;accent-color:currentColor}
.packing-list input:checked+span{text-decoration:line-through;opacity:.55}
.packing-list .pk-note{display:block;font-size:.85em;opacity:.75}
.packing-list .pk-bar{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:6px 0 10px;font-size:.9em}
.packing-list .pk-reset{font:inherit;padding:4px 10px;border-radius:6px;border:1px solid currentColor;background:transparent;color:inherit;cursor:pointer}
</style>"""

_SCRIPT = """<script>
(function(){
  var root=document.getElementById('packing-list'); if(!root) return;
  var prefix=root.getAttribute('data-key'), boxes=root.querySelectorAll('input[type=checkbox]');
  var count=root.querySelector('.pk-count');
  function get(k){try{return localStorage.getItem(k);}catch(e){return null;}}
  function set(k,v){try{v?localStorage.setItem(k,'1'):localStorage.removeItem(k);}catch(e){}}
  function update(){var n=0;boxes.forEach(function(b){if(b.checked)n++;});if(count)count.textContent=n+' / '+boxes.length;}
  boxes.forEach(function(b){
    var k=prefix+b.getAttribute('data-id'); b.checked=get(k)==='1';
    b.addEventListener('change',function(){set(k,b.checked);update();});
  });
  var reset=root.querySelector('.pk-reset');
  if(reset) reset.addEventListener('click',function(){boxes.forEach(function(b){b.checked=false;set(prefix+b.getAttribute('data-id'),false);});update();});
  update();
})();
</script>"""


def _item_id(category: str, item: str) -> str:
    return hashlib.sha1(f"{category}|{item}".encode()).hexdigest()[:10]


def render(packing: PackingList, storage_key: str) -> str:
    e = html.escape
    parts = [_STYLE, f'<div class="packing-list" id="packing-list" data-key="{e(storage_key)}:">']
    parts.append(f'<p class="pk-meta">{e(packing.baggage)}</p>')
    if packing.tips:
        parts.append('<ul class="pk-tips">' + "".join(f"<li>{e(t)}</li>" for t in packing.tips) + "</ul>")
    parts.append('<div class="pk-bar"><span>Supakuota: <b class="pk-count"></b></span>'
                 '<button type="button" class="pk-reset">Išvalyti žymes</button></div>')
    for cat in packing.categories:
        parts.append(f'<h4 class="pk-cat">{e(cat.name)}</h4><ul class="pk-items">')
        for item in cat.items:
            note = f'<span class="pk-note">{e(item.note)}</span>' if item.note else ""
            parts.append(
                f'<li><label><input type="checkbox" data-id="{_item_id(cat.name, item.name)}">'
                f"<span>{e(item.name)}{note}</span></label></li>"
            )
        parts.append("</ul>")
    parts.append("</div>")
    parts.append(_SCRIPT)
    return "".join(parts)


def inject(page_html: str, packing: PackingList, storage_key: str) -> str:
    """Put the checklist at the placeholder; if the designer left it out, add
    it as its own section before </body> so it's never silently lost."""
    block = START + render(packing, storage_key) + END
    if PLACEHOLDER in page_html:
        return page_html.replace(PLACEHOLDER, block, 1)
    section = f'<section id="packing"><h2>Ką pasiimti</h2>{block}</section>'
    idx = page_html.lower().rfind("</body>")
    return page_html[:idx] + section + page_html[idx:] if idx != -1 else page_html + section


def to_template(page_html: str) -> str | None:
    """The page with the injected checklist turned back into the placeholder
    (for incremental page updates), or None if the page has no markers."""
    a, b = page_html.find(START), page_html.find(END)
    if a == -1 or b == -1:
        return None
    return page_html[:a] + PLACEHOLDER + page_html[b + len(END):]
