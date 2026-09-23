/* Jukebox LIVE — client behaviour.
 *
 * Three jobs, and deliberately nothing else:
 *   1. enforce the vote limit visibly (dim, never hide);
 *   2. survive a reload without losing a half-made selection;
 *   3. reconnect the live stream when venue wifi drops.
 *
 * There is no client-side copy of the application state. The server renders
 * every fragment; the stream only says "something changed, re-fetch".
 */
(function () {
  "use strict";

  /* ---------------------------------------------------------- ballot ---- */
  function initBallot(form) {
    var max = parseInt(form.dataset.maxVotes, 10) || 5;
    var roundKey = "jb.ballot." + form.dataset.roundId;
    var boxes = Array.prototype.slice.call(form.querySelectorAll('input[type="checkbox"]'));
    var counter = document.getElementById("vote-count");
    var bar = document.getElementById("vote-progress");
    var submit = document.getElementById("vote-submit");
    var search = document.getElementById("song-search");

    // A ballot id, generated once and reused for every retry of this ballot.
    // The server dedups on it, so a double tap on bad signal is a no-op.
    var ballotField = form.querySelector('input[name="ballot_id"]');
    if (ballotField && !ballotField.value) {
      ballotField.value = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());
    }

    function restore() {
      try {
        var saved = JSON.parse(sessionStorage.getItem(roundKey) || "[]");
        boxes.forEach(function (b) { if (saved.indexOf(b.value) !== -1) b.checked = true; });
      } catch (e) { /* private mode, cleared storage: start empty */ }
    }

    function persist(selected) {
      try { sessionStorage.setItem(roundKey, JSON.stringify(selected)); } catch (e) {}
    }

    function sync() {
      var selected = boxes.filter(function (b) { return b.checked; });
      var n = selected.length;
      var atLimit = n >= max;

      boxes.forEach(function (b) {
        // Locked, not removed. The row stays on the page, dimmed, and can
        // still be un-ticked — which is the whole reason it must stay.
        var lock = atLimit && !b.checked;
        b.disabled = lock;
        b.closest(".song").classList.toggle("locked", lock);
      });

      if (counter) {
        counter.firstChild.nodeValue = n + " / " + max;
      }
      if (bar) bar.style.width = (n / max * 100) + "%";
      if (submit) submit.disabled = n === 0;
      persist(selected.map(function (b) { return b.value; }));
    }

    boxes.forEach(function (b) { b.addEventListener("change", sync); });

    // Clear the saved draft once the ballot is actually on its way.
    form.addEventListener("submit", function () {
      try { sessionStorage.removeItem(roundKey); } catch (e) {}
      if (submit) { submit.disabled = true; submit.textContent = "Odesílám…"; }
    });

    /* Search filters in place. It does not unmount rows, so a ticked song
       that scrolls out of the filter stays ticked and still submits. */
    if (search) {
      search.addEventListener("input", function () {
        var q = search.value.trim().toLowerCase();
        form.querySelectorAll(".songs li").forEach(function (li) {
          li.classList.toggle("hide", q !== "" && li.dataset.search.indexOf(q) === -1);
        });
      });
    }

    restore();
    sync();
  }

  /* --------------------------------------------------------- refresh ---- */
  /* Any element carrying data-refresh="<url>" re-fetches that URL and replaces
     its own contents. The server stays the only renderer, so there is no
     second copy of the state on the client to drift out of step. */
  function refreshAll() {
    document.querySelectorAll("[data-refresh]").forEach(function (el) {
      fetch(el.dataset.refresh, { headers: { "X-Fragment": "1" } })
        .then(function (r) { return r.ok ? r.text() : null; })
        .then(function (html) { if (html !== null) el.innerHTML = html; })
        .catch(function () { /* offline; the next event will try again */ });
    });
  }

  /* ---------------------------------------------------------- stream ---- */
  /* Reconnection is EventSource's own job; this wrapper exists only to reload
     the page when the round state changes underneath the viewer. */
  function initStream(url) {
    var source;
    var retry = 1000;

    function connect() {
      source = new EventSource(url);

      source.addEventListener("ready", function () { retry = 1000; });

      source.addEventListener("update", function (ev) {
        var data = {};
        try { data = JSON.parse(ev.data); } catch (e) {}
        // A change to what the round *is* reloads the page, because the whole
        // shape of it differs between open, closed and not-yet-started.
        if (data.reload) {
          window.location.reload();
          return;
        }
        // Anything else (votes arriving from other phones) just re-renders
        // the live fragments in place.
        refreshAll();
      });

      source.addEventListener("error", function () {
        source.close();
        retry = Math.min(retry * 2, 15000);
        setTimeout(connect, retry);
      });
    }

    connect();
  }

  /* ------------------------------------------------------------ boot ---- */
  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("ballot");
    if (form) initBallot(form);

    var streamEl = document.querySelector("[data-stream]");
    if (streamEl && window.EventSource) initStream(streamEl.dataset.stream);
  });
})();
