/* Jukebox LIVE — client behaviour.
 *
 * Three jobs, and deliberately nothing else:
 *   1. enforce the vote limit visibly (dim, never hide);
 *   2. survive a reload without losing a half-made selection;
 *   3. reconnect the live stream when venue wifi drops, and notice what was
 *      missed while it was down.
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

    // The draft is NOT cleared here. On venue wifi the submit can fail, and a
    // draft cleared on the way out is a selection lost at the worst moment.
    // The receipt page clears it, once the server has counted the ballot.
    form.addEventListener("submit", function () {
      if (submit) { submit.disabled = true; submit.textContent = "Odesílám…"; }
    });

    // Back from the browser's page cache after a submit that went nowhere:
    // the button must work again.
    window.addEventListener("pageshow", function (ev) {
      if (ev.persisted && submit) { submit.textContent = "Odeslat hlasy"; sync(); }
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
  /* The stream says "something changed"; the page it is on carries the stamp
     it was rendered from. Every time the stream (re)connects the server names
     the current stamp. If the two differ, this page slept through a change --
     a locked phone, a dead spot in the hall, a restarted server -- and is
     fetched again. Without that check a phone locked between rounds went on
     promising "this page will refresh itself" for the rest of the night. */
  function initStream(el) {
    var url = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + el.dataset.stream;
    var stamp = el.dataset.stamp;
    var jitter = parseInt(el.dataset.jitter, 10) || 0;
    var socket;
    var retry = 1000;
    var connected = 0;        // how many times the stream has come up
    var reloading = false;
    var hiddenAt = 0;
    var heard = 0;            // when anything last arrived, pongs included

    // Five hundred phones are told to reload in the same instant. Each waits
    // a random moment first, so the server sees a few seconds of traffic
    // rather than one wall of it. Screens without data-jitter go at once.
    function reload() {
      if (reloading) return;
      reloading = true;
      if (socket) socket.close();
      setTimeout(function () { window.location.reload(); }, Math.random() * jitter);
    }

    function onReady(data) {
      retry = 1000;
      connected += 1;
      if (stamp !== undefined && data.stamp !== undefined && String(data.stamp) !== stamp) {
        reload();
        return;
      }
      // Same event state, but votes may have landed while we were away.
      if (connected > 1) refreshAll();
    }

    function onUpdate(data) {
      // A change to what the round *is* reloads the page, because the whole
      // shape of it differs between open, closed and not-yet-started.
      if (data.reload) {
        reload();
        return;
      }
      // Anything else (votes arriving from other phones) just re-renders
      // the live fragments in place.
      refreshAll();
    }

    function connect() {
      var ws = new WebSocket(url);
      socket = ws;
      heard = Date.now();

      ws.onmessage = function (ev) {
        heard = Date.now();
        if (ev.data === "pong") return;
        var data = {};
        try { data = JSON.parse(ev.data); } catch (e) { return; }
        if (data.type === "ready") onReady(data);
        else if (data.type === "update") onUpdate(data);
      };

      ws.onclose = function () {
        // Replaced on purpose by reconnect(), or the page is leaving.
        if (socket !== ws || reloading) return;
        retry = Math.min(retry * 2, 15000);
        setTimeout(connect, retry);
      };
    }

    function reconnect() {
      var old = socket;
      socket = null;
      if (old) old.close();
      connect();
    }

    // A phone coming back from the lock screen may hold a connection that is
    // dead without knowing it. Do not wait for it to find out: ask again.
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) { hiddenAt = Date.now(); return; }
      if (reloading || !hiddenAt || Date.now() - hiddenAt < 5000) return;
      reconnect();
    });

    // Networks drop connections that go quiet, and a dead one can look open
    // for minutes. A ping every 25 seconds keeps it alive; nothing heard for
    // a minute means it is gone.
    setInterval(function () {
      if (reloading || !socket) return;
      if (Date.now() - heard > 60000) { reconnect(); return; }
      if (socket.readyState === WebSocket.OPEN) socket.send("ping");
    }, 25000);

    connect();
  }

  /* ------------------------------------------------------------ boot ---- */
  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("ballot");
    if (form) initBallot(form);

    var voted = document.querySelector("[data-voted-round]");
    if (voted) {
      try { sessionStorage.removeItem("jb.ballot." + voted.dataset.votedRound); } catch (e) {}
    }

    var streamEl = document.querySelector("[data-stream]");
    if (streamEl && window.WebSocket) initStream(streamEl);
  });

  /* --------------------------------------------------------- confirm ---- */
  /* <form data-confirm="..."> asks before it submits. The question is read
     from the attribute as text, so no name can break out of it. */
  document.addEventListener("submit", function (ev) {
    var question = ev.target.dataset && ev.target.dataset.confirm;
    if (question && !window.confirm(question)) ev.preventDefault();
  });
})();
