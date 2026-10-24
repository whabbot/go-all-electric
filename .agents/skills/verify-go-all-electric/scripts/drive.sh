# Go All-Electric browser helpers for chrome-devtools-axi. Source, then call the functions:
#
#   . .agents/skills/verify-go-all-electric/scripts/drive.sh
#   evidence my-change            # evidence dir for this proof: .verify/evidence/<date>-my-change
#   frame 390 844 /               # phone width (axi cannot resize below ~500 px, so use the iframe)
#   desk /                        # 1280x800 top-level page (no iframe)
#   click button "Load Sam's sample (demo)"
#   upload "Radiators" 3          # three synthetic images into the Radiators slot's file input
#   shot 01-dialog; snap 01-dialog
#
# Works in bash and zsh. Needs launch.sh to have run in this worktree (it sources .verify/run/env,
# which sets GAE_URL and this worktree's own CHROME_DEVTOOLS_AXI_SESSION).

_GAE_DRIVE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")" && pwd -P)
_GAE_WT=$(git -C "$_GAE_DRIVE_DIR" rev-parse --show-toplevel)
if [ -f "$_GAE_WT/.verify/run/env" ]; then
  . "$_GAE_WT/.verify/run/env"
else
  echo "drive.sh: no running instance; run $_GAE_DRIVE_DIR/launch.sh first" >&2
fi
AX=chrome-devtools-axi
AUDIT_JS="$_GAE_DRIVE_DIR/audit.js"
EV=${EV:-$GAE_EVIDENCE/scratch}

# evidence NAME: start a proof; screenshots and transcripts go to .verify/evidence/<date>-NAME.
evidence() {
  EV="$GAE_EVIDENCE/$(date +%Y%m%d-%H%M)-$1"; mkdir -p "$EV"
  wc -l <"$GAE_STATE/backend.log" | tr -d ' ' >"$EV/.apimark"; echo "$EV"
}

# frame W H PATH: load the app at PATH inside a WxH iframe (/__frame.html). Clears sessionStorage
# first (fresh session); add a 4th arg `keep` to keep it.
frame() {
  $AX resize 1300 950 >/dev/null 2>&1
  local keep=""; [ "${4:-}" = keep ] && keep="&keep"
  $AX open "$GAE_URL/__frame.html?w=$1&h=$2&path=$3$keep" >/dev/null; sleep 1.5
}
# desk PATH: load the app as a normal 1280x800 page (no iframe).
desk() { $AX resize 1280 800 >/dev/null 2>&1; $AX open "$GAE_URL$1" >/dev/null; sleep 1.5; }

# fjs BODY: run JS against the app; `d` is its document, `w` its window, `f` the iframe (or null).
fjs() { $AX eval "() => { const f=document.getElementById('f'); const w=f?f.contentWindow:window, d=w.document; $1 }" | sed -n 's/^result: //p' | _gae_unquote; }
# axi prints results JSON-encoded (strings twice); print plain text.
_gae_unquote() { python3 -c 'import json,sys
s=sys.stdin.read().strip()
try:
    v=json.loads(s)
    while isinstance(v,str) and v[:1] in "\"[{":
        v=json.loads(v)
except Exception:
    v=s
print(v if isinstance(v,str) else json.dumps(v))'; }
# _js TEXT: TEXT as a JS string literal, so quotes in labels ("Sam's") are safe inside fjs.
_js() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"; }

# uid ROLE NAME: the snapshot uid of the first ROLE whose accessible name starts with NAME.
uid() { $AX snapshot 2>/dev/null | grep -m1 -F "$1 \"$2" | sed 's/.*uid=\([^ ]*\).*/\1/'; }
# click ROLE NAME: a real (trusted) click on that element by role and accessible name.
click() {
  local u; u=$(uid "$1" "$2")
  [ -n "$u" ] || { echo "MISSING $1 \"$2\""; return 1; }
  $AX click "@$u" >/dev/null && sleep 0.6 && echo "clicked $1 \"$2\""
}
# tap TEXT: JS click on the first visible button/link/label whose text is (or contains) TEXT.
# Use when the accessible name is ambiguous; prefer `click`.
tap() { local t; t=$(_js "$1"); fjs "const t=$t; const all=[...d.querySelectorAll('button,a,label,[role=button]')].filter(e=>e.offsetParent); const el=all.find(e=>e.textContent.trim()===t)||all.find(e=>e.textContent.includes(t)); if(!el) return 'MISSING '+t; el.click(); return 'ok'"; sleep 0.6; }
# fill LABEL VALUE: set an input by its <label> text (React-safe). Synthetic/sample values only.
fill() { local l v; l=$(_js "$1"); v=$(_js "$2"); fjs "const l=[...d.querySelectorAll('label')].find(x=>x.textContent.trim()===$l); const i=l&&(l.control||d.getElementById(l.htmlFor)); if(!i) return 'MISSING '+$l; Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype,'value').set.call(i,$v); i.dispatchEvent(new Event('input',{bubbles:true})); return 'ok'"; }
# go PATH: client-side navigation that keeps in-memory state (like a link click, not a reload).
go() { fjs "w.history.pushState({}, '', '$1'); w.dispatchEvent(new PopStateEvent('popstate')); w.scrollTo(0,0); return w.location.pathname"; sleep 0.8; }
# where: current app path.
where() { fjs "return w.location.pathname"; }
# has TEXT: prints yes/no for whether the app's visible text contains TEXT.
has() { fjs "return d.body.innerText.includes($(_js "$1")) ? 'yes' : 'no'"; }
# waitfor TEXT [SECONDS]: poll until the app shows TEXT (default 30 s). Returns 1 on timeout.
waitfor() {
  local i n=$(( ${2:-30} * 2 ))
  for i in $(seq 1 "$n"); do [ "$(has "$1")" = yes ] && { echo "seen \"$1\" after $((i / 2)) s"; return 0; }; sleep 0.5; done
  echo "TIMEOUT waiting for \"$1\""; return 1
}
# into SELECTOR: scroll the first match into view.
into() { fjs "const el=d.querySelector($(_js "$1")); if(!el) return 'MISSING'; el.scrollIntoView({block:'center'}); return 'ok'" >/dev/null; sleep 0.3; }
# scrolly PX: scroll the app to PX from the top.
scrolly() { fjs "w.scrollTo(0,$1); return w.scrollY" >/dev/null; sleep 0.3; }

# upload SLOT [COUNT] [PREFIX]: put COUNT synthetic 1200x900 images (default 1) into the file input
# of the Photos slot whose label contains SLOT ("Gas bill", "Loft", "Boiler data plate",
# "Radiators", "Fuse cutout", "Outdoor unit spot"). Fires `change` like a real pick; a single-file
# slot only takes the first. Images are drawn in the page: grey, labelled SYNTHETIC TEST IMAGE.
# `$AX upload @uid file` also works but only ever sends one file.
upload() {
  local n=${2:-1} p=${3:-synthetic} slot; slot=$(_js "$1")
  fjs "const slot=$slot; const li=[...d.querySelectorAll('li')].find(l=>l.querySelector('.capture-guide-label')?.textContent.includes(slot));
    const inp=li&&li.querySelector('input[type=file]'); if(!inp) return 'MISSING slot '+slot;
    const mk=(i)=>new Promise(r=>{const c=d.createElement('canvas'); c.width=1200; c.height=900; const g=c.getContext('2d');
      g.fillStyle='hsl('+(i*67%360)+',18%,62%)'; g.fillRect(0,0,1200,900); g.fillStyle='#222'; g.font='60px sans-serif';
      g.fillText('SYNTHETIC TEST IMAGE '+i,120,430); g.fillText(slot,120,520);
      c.toBlob(b=>r(new File([b],'$p-'+i+'.png',{type:'image/png'})),'image/png')});
    return Promise.all(Array.from({length:$n},(_, i)=>mk(i+1))).then(fs=>{const dt=new DataTransfer(); fs.forEach(x=>dt.items.add(x));
      inp.files=dt.files; inp.dispatchEvent(new Event('change',{bubbles:true})); return 'queued '+fs.length+' (multiple='+inp.multiple+')'})"
  sleep 1.2
}
# coverup: one-line state of the Redact dialog ("closed", or title + "Photo i of n").
coverup() { fjs "const g=d.querySelector('[role=dialog][aria-labelledby=cover-up-title]'); if(!g) return 'closed'; return g.querySelector('h2').textContent+' | '+(g.querySelector('.cover-up-progress')?.textContent||'single photo')"; }
# synth NAME [W H]: write a synthetic PNG (grey, labelled SYNTHETIC TEST IMAGE) to
# $GAE_STATE/fixtures/NAME.png and print its path. For `pick` and curl; never use real photos.
synth() {
  mkdir -p "$GAE_STATE/fixtures"
  "$GAE_WORKTREE/backend/.venv/bin/python" -I -c 'import sys
from PIL import Image, ImageDraw, ImageFont
name, w, h, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
im = Image.new("RGB", (w, h), (138, 154, 168)); g = ImageDraw.Draw(im)
font = ImageFont.load_default(size=max(24, w // 20))
g.text((w // 10, h // 2 - w // 20), "SYNTHETIC TEST IMAGE", fill=(20, 20, 20), font=font)
g.text((w // 10, h // 2 + w // 40), name, fill=(20, 20, 20), font=font)
im.save(out)' "$1" "${2:-1200}" "${3:-900}" "$GAE_STATE/fixtures/$1.png" && echo "$GAE_STATE/fixtures/$1.png"
}
# pick SLOT FILE: choose FILE through the slot's real file input (CDP file chooser, one file only),
# the closest thing to a user picking from the gallery. Use `upload` for several files at once.
pick() {
  local u; u=$($AX snapshot 2>/dev/null | awk -v s="button \"$1" 'index($0,s){f=1} f&&/button "📷/{sub(/.*uid=/,""); sub(/ .*/,""); print; exit}')
  [ -n "$u" ] || { echo "MISSING file input for slot $1"; return 1; }
  $AX upload "@$u" "$2" >/dev/null && sleep 1.2 && echo "picked $(basename "$2") for $1"
}
# fileinput SLOT: the slot's file input value as the browser shows it ("No file chosen" = cleared,
# so picking the same file again will fire `change`).
fileinput() { $AX snapshot 2>/dev/null | awk -v s="button \"$1" 'index($0,s){f=1} f&&/button "📷/{sub(/.*value=/,""); print; exit}'; }

# drag X1 Y1 X2 Y2: drag across the Redact dialog's image, corners as fractions (0-1) of the
# canvas. Press "Crop area" or "Black out" first to pick what the drag draws.
drag() {
  fjs "const c=d.querySelector('.cover-up-canvas-wrap'); if(!c) return 'MISSING canvas'; const r=c.getBoundingClientRect();
    c.setPointerCapture=()=>{}; c.releasePointerCapture=()=>{};
    const ev=(t,x,y)=>c.dispatchEvent(new w.PointerEvent(t,{bubbles:true,clientX:r.left+x*r.width,clientY:r.top+y*r.height,pointerId:1,isPrimary:true,buttons:t==='pointerup'?0:1}));
    const tick=()=>new Promise(k=>setTimeout(k,60));
    return (async()=>{ ev('pointerdown',$1,$2); await tick(); ev('pointermove',($1+$3)/2,($2+$4)/2); await tick();
      ev('pointermove',$3,$4); await tick(); ev('pointerup',$3,$4); await tick(); return 'dragged' })()"
}
# blackout: draw one black box over the middle of the image.
blackout() { tap "Black out" >/dev/null; drag 0.3 0.35 0.7 0.65; }
# crop: select a central area that stays inside the image whatever its aspect, then press Crop
# (the preview shrinks to it).
crop() { tap "Crop area" >/dev/null; drag 0.2 0.35 0.8 0.65; tap "Crop"; }

# shot NAME [full]: screenshot the app (the iframe in frame mode) to $EV/NAME.png.
shot() {
  mkdir -p "$EV"
  local u
  if [ "$(fjs "return f ? 'frame' : 'page'")" = frame ]; then
    [ "${2:-}" = full ] && fjs "f.dataset.h=f.style.height; f.style.height=d.documentElement.scrollHeight+'px'; return 1" >/dev/null && sleep 0.5
    u=$($AX snapshot 2>/dev/null | grep -m1 'Iframe' | sed 's/.*uid=\([^ ]*\).*/\1/')
    $AX screenshot "$EV/$1.png" --uid "@$u" >/dev/null
    [ "${2:-}" = full ] && fjs "f.style.height=f.dataset.h; return 1" >/dev/null
  else
    if [ "${2:-}" = full ]; then $AX screenshot "$EV/$1.png" --full >/dev/null; else $AX screenshot "$EV/$1.png" >/dev/null; fi
  fi
  echo "saved $EV/$1.png"
}
# snap NAME: save the ARIA snapshot (accessible names, roles, state) to $EV/NAME.aria.txt.
snap() { mkdir -p "$EV"; $AX snapshot 2>/dev/null | sed '/^help\[/,$d' >"$EV/$1.aria.txt"; echo "saved $EV/$1.aria.txt"; }
# net NAME: the /api requests this run's backend served since the last `net` (or `evidence`),
# from its access log, to $EV/NAME.api.txt, plus the browser's network list to
# $EV/NAME.network.txt. Count the /api lines from the backend log: in frame mode the browser list
# does not include the app's own fetches.
net() {
  mkdir -p "$EV"
  local mark; mark=$(cat "$EV/.apimark" 2>/dev/null || echo 0)
  tail -n +"$((mark + 1))" "$GAE_STATE/backend.log" | grep -E '"(GET|POST|PUT|DELETE) /api/' | grep -v '/api/access' >"$EV/$1.api.txt"
  wc -l <"$GAE_STATE/backend.log" | tr -d ' ' >"$EV/.apimark"
  $AX network 2>/dev/null | sed '/^help\[/,$d' >"$EV/$1.network.txt"
  echo "saved $EV/$1.api.txt ($(wc -l <"$EV/$1.api.txt" | tr -d ' ') /api requests)"; sed 's/^/  /' "$EV/$1.api.txt"
}
# apilog NAME: copy this run's backend log (request lines, Gemini call lines; never keys) to evidence.
apilog() { mkdir -p "$EV"; cp "$GAE_STATE/backend.log" "$EV/$1.backend.log"; echo "saved $EV/$1.backend.log"; }
# note TEXT: append a line to the proof transcript $EV/transcript.md.
note() { mkdir -p "$EV"; echo "- $(date +%H:%M:%S) $*" >>"$EV/transcript.md"; }
# audit: automated layout/contrast/tap-target checks for the current state, as JSON.
audit() { $AX eval "$(cat "$AUDIT_JS")" | sed -n 's/^result: //p' | _gae_unquote; }

# --- Real mode only ---------------------------------------------------------------------------
# realhouse: pick a house on Start from a postcode kept in a private file outside every repo
# ($GAE_VERIFY_POSTCODE_FILE, default ~/.config/go-all-electric/verify-postcode). The postcode and
# the address list are never printed or captured: take screenshots only after this returns, when
# the app shows the district alone. Live mode has no sample house, so the Photos step and
# everything after it need this.
realhouse() {
  local pf=${GAE_VERIFY_POSTCODE_FILE:-$HOME/.config/go-all-electric/verify-postcode}
  [ "$GAE_MODE" = real ] || { echo "realhouse: mock mode already has Sam's sample house"; return 1; }
  [ -r "$pf" ] || { echo "realhouse: no private postcode file at $pf (ask the operator; never commit one)"; return 1; }
  fill Postcode "$(tr -d '\n' <"$pf")" >/dev/null
  click button "Find EPC" >/dev/null
  local i; for i in $(seq 1 40); do
    [ "$(fjs "return d.querySelector('.address-list button, [role=alert]') ? 'y' : 'n'")" = y ] && break; sleep 0.5
  done
  fjs "const b=d.querySelector('.address-list button'); if(!b) return 'no address found (EPC search error or no certificate)'; b.click(); return 'picked the first listed address'"
  sleep 0.8
  fjs "return (d.querySelector('.selected-house strong')||{}).innerText||'no house selected'"
}
# photocheck KIND [FILE]: POST one synthetic image to /api/photos/check through the app's own /api
# proxy, exactly the request the Photos step sends (multipart kind + file). Prints status, time and
# the JSON reply. Real mode calls Gemini; mock mode's backend has no key and answers 503.
photocheck() {
  local f=${2:-$(synth "$1")} out
  mkdir -p "$EV"; out="$EV/photocheck-$1.json"
  curl -sS -o "$out" -w "HTTP %{http_code} in %{time_total}s\n" -F "kind=$1" -F "file=@$f;type=image/png" "$GAE_URL/api/photos/check"
  cat "$out"; echo
}
