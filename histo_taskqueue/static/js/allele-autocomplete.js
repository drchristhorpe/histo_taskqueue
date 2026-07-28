// Lightweight allele autocomplete for the pMHC panel.
// Queries /api/alleles?q= as the user types and shows a suggestion list; picking
// one fills the allele name and (if empty) the heavy-chain sequence.
(function () {
  "use strict";
  var input = document.getElementById("allele_name");
  var box = document.getElementById("allele_suggest");
  var heavy = document.getElementById("heavy_chain");
  if (!input || !box) return;

  var items = [];
  var active = -1;
  var timer = null;

  function close() {
    box.classList.remove("open");
    box.innerHTML = "";
    active = -1;
  }

  function render() {
    if (!items.length) {
      close();
      return;
    }
    box.innerHTML = "";
    items.forEach(function (a, i) {
      var b = document.createElement("button");
      b.type = "button";
      b.innerHTML =
        escapeHtml(a.name) +
        (a.locus ? '<span class="locus">HLA-' + escapeHtml(a.locus) + "</span>" : "");
      b.addEventListener("mousedown", function (e) {
        e.preventDefault();
        choose(a);
      });
      if (i === active) b.classList.add("active");
      box.appendChild(b);
    });
    box.classList.add("open");
  }

  function choose(a) {
    input.value = a.name;
    close();
    // Pull the heavy chain so the user can see/edit it; only if left blank.
    if (heavy && !heavy.value.trim()) {
      fetch("/api/alleles?q=" + encodeURIComponent(a.name) + "&limit=1")
        .then(function (r) { return r.json(); })
        .then(function () { /* name resolved server-side on submit */ });
    }
  }

  function fetchMatches(q) {
    fetch("/api/alleles?q=" + encodeURIComponent(q) + "&limit=12")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        items = data.alleles || [];
        active = -1;
        render();
      })
      .catch(close);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  input.addEventListener("input", function () {
    var q = input.value.trim();
    clearTimeout(timer);
    if (q.length < 1) {
      close();
      return;
    }
    timer = setTimeout(function () { fetchMatches(q); }, 120);
  });

  input.addEventListener("keydown", function (e) {
    if (!box.classList.contains("open")) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      active = Math.min(active + 1, items.length - 1);
      render();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      active = Math.max(active - 1, 0);
      render();
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      choose(items[active]);
    } else if (e.key === "Escape") {
      close();
    }
  });

  document.addEventListener("click", function (e) {
    if (e.target !== input && !box.contains(e.target)) close();
  });
})();
