# The band website

The public site for Jukebox Heroes: one page, plain HTML, CSS and a little
JavaScript. No build step and nothing running on a server. It replaces the Wix
site at `www.jukeboxheroes.cz`, with the same content and one change: where the
old page showed a static QR code, this one has a **Hlasovat** button and panel
that lead to the voting app in [`../jukebox/`](../jukebox/).

```
site/
  public/            everything that is published, exactly as it is served
    index.html         the page
    404.html
    _headers           cache and security headers (Cloudflare reads it)
    assets/css  js  fonts  img  docs
  originals/         full-size photos, logos and PDFs as downloaded from Wix
  tools/build_images.py   originals/ -> public/assets/img/
  wrangler.jsonc     Cloudflare configuration
```

## Look at it

```sh
python3 -m http.server 8000 --directory site/public
```

Then open <http://localhost:8000>.

## Change it

- **Text**: edit `public/index.html`. All of it is there, in Czech, in page order.
- **The voting address**: `https://hlasuj.jukeboxheroes.cz/` appears three times
  in `index.html` and once in `404.html`. Replace all four if the address changes.
- **A photo**: put the full-size file in `originals/`, add its name to the list
  at the top of `tools/build_images.py`, run `python3 site/tools/build_images.py`
  (needs Pillow and numpy), then add the `<li>` to the gallery in `index.html`.
- **A band member**: the studio portraits have the name and instrument printed
  in the picture. The script paints that lettering out, because the page shows
  it as real text; a new portrait needs its own box in `MEMBERS`.

## Going live on Cloudflare

1. Add `jukeboxheroes.cz` to the Cloudflare account as a site (free plan is
   enough for this). Cloudflare shows two nameservers.
2. At Webglobe, where the domain is registered, replace the Wix nameservers
   (`ns10.wixdns.net`, `ns11.wixdns.net`) with those two. The registration
   itself stays at Webglobe: Cloudflare's registrar does not take `.cz`.
3. `cd site && npx wrangler deploy`. Then uncomment the `routes` block in
   `wrangler.jsonc` and deploy again, so the site answers on the real address.
4. In Cloudflare, redirect `jukeboxheroes.cz` to `www.jukeboxheroes.cz`. The
   page's canonical address is the `www` one, as it was on Wix.

Not verified here: the deploy itself. It needs the Cloudflare account, which
this checkout has no access to.

## What came from where

- Photos, logos, texts and both PDFs: the Wix site, downloaded 2026-11-12.
  Two things were left behind on purpose: Wix's stock background image and its
  social icons, which are licensed for Wix sites only. The icons here are drawn
  in the page.
- The old QR code (`originals/docs/qr-stary-streamlit.pdf`) points at
  `https://jukeboxlive.streamlit.app/`. It is kept for the record and not
  published.
- Fonts: Unbounded and Figtree, both under the SIL Open Font License; the
  licence texts sit next to the files in `public/assets/fonts/`. They are
  served from this site, so no visitor's browser contacts Google.
- The promo video is loaded from YouTube only after someone presses play.

## Not carried over

The Wix contact form. It needs something that sends mail, and a static page has
nothing of the kind. The e-mail link opens a message with the questions already
written in (date, place, kind of event, number of guests). A form that sends
from the page is a small Cloudflare Worker plus Email Routing on the domain.
