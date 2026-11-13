/* Jukebox Heroes — band website.
 *
 * Five small behaviours. The page reads and works with none of them: links
 * are links, photos open as files, the video has a plain YouTube link.
 */
(function () {
  "use strict";

  var root = document.documentElement;
  root.classList.add("js");

  /* ---------------------------------------------------------- header ---- */
  var top = document.querySelector(".top");
  function stick() { top.classList.toggle("is-stuck", window.scrollY > 24); }
  window.addEventListener("scroll", stick, { passive: true });
  stick();

  /* ------------------------------------------------------------ menu ---- */
  var burger = document.querySelector(".top__burger");
  var menu = document.getElementById("menu");
  function setMenu(open) {
    root.classList.toggle("menu-open", open);
    burger.setAttribute("aria-expanded", String(open));
  }
  burger.addEventListener("click", function () {
    setMenu(burger.getAttribute("aria-expanded") !== "true");
  });
  menu.addEventListener("click", function (ev) {
    if (ev.target.closest("a")) setMenu(false);
  });
  window.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") setMenu(false);
  });

  /* ---------------------------------------------------------- reveal ---- */
  var revealed = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window) {
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-in");
        seen.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -8% 0px" });
    revealed.forEach(function (el) { seen.observe(el); });
  } else {
    revealed.forEach(function (el) { el.classList.add("is-in"); });
  }

  /* ----------------------------------------------------------- video ---- */
  /* YouTube is contacted only when someone presses play. */
  document.querySelectorAll("[data-video]").forEach(function (box) {
    box.querySelector(".video__play").addEventListener("click", function () {
      var frame = document.createElement("iframe");
      frame.src = "https://www.youtube-nocookie.com/embed/" + box.dataset.video + "?autoplay=1&rel=0";
      frame.title = "Jukebox Heroes – promo video";
      frame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
      box.classList.add("is-playing");
      box.appendChild(frame);
    });
  });

  /* --------------------------------------------------------- gallery ---- */
  var box = document.querySelector(".lightbox");
  var links = Array.prototype.slice.call(document.querySelectorAll(".gallery a"));
  if (box && box.showModal && links.length) {
    var image = box.querySelector("img");
    var current = 0;

    function show(index) {
      current = (index + links.length) % links.length;
      image.src = links[current].href;
      image.alt = links[current].querySelector("img").alt;
    }

    links.forEach(function (link, index) {
      link.addEventListener("click", function (ev) {
        ev.preventDefault();
        show(index);
        box.showModal();
      });
    });

    box.querySelector(".lightbox__close").addEventListener("click", function () { box.close(); });
    box.querySelector(".lightbox__nav--prev").addEventListener("click", function () { show(current - 1); });
    box.querySelector(".lightbox__nav--next").addEventListener("click", function () { show(current + 1); });
    // A click on the dark around the photo closes it.
    box.addEventListener("click", function (ev) { if (ev.target === box) box.close(); });
    box.addEventListener("keydown", function (ev) {
      if (ev.key === "ArrowLeft") show(current - 1);
      if (ev.key === "ArrowRight") show(current + 1);
    });
    box.addEventListener("close", function () {
      image.removeAttribute("src");
      links[current].focus();
    });
  }
})();
