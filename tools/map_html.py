"""Trip map rendered by code (Leaflet), not written by the Page Designer.

The designer's hand-written map JS broke on real runs (container id not
matching the L.map() call -> empty map box), and markers had only click
popups. Here the map is generated from the Itinerary itself, so it always
works and every point has a hover tooltip with the place name. The designer
only places the <!-- TRIP_MAP --> placeholder.
"""

import html
import json

from schemas.itinerary import Itinerary

PLACEHOLDER = "<!-- TRIP_MAP -->"
START, END = "<!-- TRIP_MAP:START -->", "<!-- TRIP_MAP:END -->"

PALETTE = ["#d7263d", "#1b998b", "#2e86ab", "#f46036", "#7b2cbf", "#c5a600"]
LEAFLET = "https://unpkg.com/leaflet@1.9.4/dist/leaflet"


def map_data(itinerary: Itinerary) -> dict:
    """Points (one per distinct stop per day) and a polyline per day."""
    points, lines = [], []
    for i, day in enumerate(itinerary.days):
        color = PALETTE[i % len(PALETTE)]
        coords = []
        for order, stop in enumerate(day.stops, 1):
            coords.append([stop.lat, stop.lon])
            points.append({
                "day": day.number, "order": order, "name": stop.name, "lat": stop.lat, "lon": stop.lon,
                "time": stop.arrive if stop.arrive == stop.depart else f"{stop.arrive}–{stop.depart}",
                "url": stop.google_maps_url, "color": color,
            })
        if len(coords) > 1:
            lines.append({"day": day.number, "color": color, "coords": coords})
    return {"points": points, "lines": lines}


_SCRIPT = """<script>(function(){
var D=%s,el=document.getElementById('trip-map');
function e(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML;}
function draw(){
  var m=L.map(el,{scrollWheelZoom:false});
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap'}).addTo(m);
  D.lines.forEach(function(l){L.polyline(l.coords,{color:l.color,weight:3,dashArray:'6 6'}).addTo(m);});
  var b=[];
  D.points.forEach(function(p){
    b.push([p.lat,p.lon]);
    L.circleMarker([p.lat,p.lon],{radius:7,color:'#fff',weight:2,fillColor:p.color,fillOpacity:1}).addTo(m)
      .bindTooltip(e(p.name),{direction:'top',offset:[0,-6]})
      .bindPopup('<b>'+e(p.name)+'</b><br>'+p.day+' diena · '+e(p.time)+'<br><a href="'+e(p.url)+'" target="_blank" rel="noopener">Google Maps</a>');
  });
  if(b.length) m.fitBounds(b,{padding:[30,30],maxZoom:12});
  var lg=L.control({position:'bottomleft'});
  lg.onAdd=function(){var d=L.DomUtil.create('div','trip-map-legend');
    d.innerHTML=D.lines.map(function(l){return '<span><i style="background:'+l.color+'"></i>'+l.day+' d.</span>';}).join('');return d;};
  if(D.lines.length) lg.addTo(m);
}
function load(){
  if(window.L){draw();return;}
  var c=document.createElement('link');c.rel='stylesheet';c.href='%s.css';document.head.appendChild(c);
  var s=document.createElement('script');s.src='%s.js';s.onload=draw;document.head.appendChild(s);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',load);else load();
})();</script>"""

_STYLE = """<style>
#trip-map{height:440px;width:100%;border-radius:12px;margin-top:12px;z-index:0}
.trip-map-legend{background:#fff;padding:4px 8px;border-radius:6px;font:12px sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.3)}
.trip-map-legend span{margin-right:8px;white-space:nowrap}
.trip-map-legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:middle}
@media(max-width:600px){#trip-map{height:340px}}
</style>"""


def render(data: dict) -> str:
    js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return _STYLE + '<div id="trip-map" role="region" aria-label="Kelionės žemėlapis"></div>' + _SCRIPT % (js, LEAFLET, LEAFLET)


def inject(page_html: str, data: dict) -> str:
    """Map at the placeholder; if missing, its own section before </body>."""
    block = START + render(data) + END
    if PLACEHOLDER in page_html:
        return page_html.replace(PLACEHOLDER, block, 1)
    section = f'<section id="trip-map-section"><h2>🗺️ Žemėlapis</h2>{block}</section>'
    idx = page_html.lower().rfind("</body>")
    return page_html[:idx] + section + page_html[idx:] if idx != -1 else page_html + section


def to_template(page_html: str) -> str:
    """The page with the injected map turned back into the placeholder."""
    a, b = page_html.find(START), page_html.find(END)
    if a == -1 or b == -1:
        return page_html
    return page_html[:a] + PLACEHOLDER + page_html[b + len(END):]
