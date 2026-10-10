/* LeaseFlow interface behaviour: theme, loading states, chat feedback, small interactions. */
(function () {
  "use strict";

  var root = document.documentElement;

  /* ----- Light and dark mode ----- */
  function applyTheme(theme) {
    root.dataset.theme = theme;
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      var dark = theme === "dark";
      button.setAttribute("aria-pressed", dark ? "true" : "false");
      button.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
    });
  }
  applyTheme(root.dataset.theme || "light");
  var calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-theme-toggle]");
    if (!toggle) return;
    var next = root.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("leaseflow-theme", next); } catch (error) { /* private window */ }
    if (!document.startViewTransition || calm) { applyTheme(next); return; }

    // The new colours open outward in a circle from the button that was pressed.
    var box = toggle.getBoundingClientRect();
    var x = box.left + box.width / 2;
    var y = box.top + box.height / 2;
    var radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
    root.classList.add("theme-reveal");
    var change = document.startViewTransition(function () { applyTheme(next); });
    change.ready.then(function () {
      root.animate(
        { clipPath: ["circle(0px at " + x + "px " + y + "px)", "circle(" + radius + "px at " + x + "px " + y + "px)"] },
        { duration: 520, easing: "cubic-bezier(0.2, 0.7, 0.3, 1)", pseudoElement: "::view-transition-new(root)" }
      );
    });
    change.finished.then(function () { root.classList.remove("theme-reveal"); });
  });

  /* ----- Buttons show a spinner while their form is being sent ----- */
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form.hasAttribute("hx-post")) return;
    var button = event.submitter || form.querySelector("button[type=submit]");
    if (!button || !button.classList.contains("btn")) return;
    // Wait one tick so the browser has already collected the clicked button's value.
    setTimeout(function () {
      button.classList.add("is-loading");
      button.setAttribute("aria-busy", "true");
      form.querySelectorAll("button").forEach(function (other) { other.disabled = true; });
    }, 0);
  });
  window.addEventListener("pageshow", function () {
    document.querySelectorAll(".btn.is-loading").forEach(function (button) {
      button.classList.remove("is-loading");
      button.removeAttribute("aria-busy");
    });
    document.querySelectorAll("form button:disabled").forEach(function (button) { button.disabled = false; });
  });

  /* ----- Messages fade out by themselves ----- */
  function dismiss(notice) {
    notice.classList.add("is-leaving");
    setTimeout(function () { notice.remove(); }, 260);
  }
  document.querySelectorAll(".notice-success").forEach(function (notice) {
    setTimeout(function () { dismiss(notice); }, 6000);
  });
  document.addEventListener("click", function (event) {
    var close = event.target.closest("[data-dismiss]");
    if (close) dismiss(close.closest(".notice"));
  });

  /* ----- Account menu closes on outside click or Escape ----- */
  document.addEventListener("click", function (event) {
    document.querySelectorAll("details.menu[open]").forEach(function (menu) {
      if (!menu.contains(event.target)) menu.removeAttribute("open");
    });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    document.querySelectorAll("details.menu[open]").forEach(function (menu) {
      menu.removeAttribute("open");
      menu.querySelector("summary").focus();
    });
  });

  /* ----- Search: the dropdown opens while typing, "/" jumps to the box, Escape closes it ----- */
  var search = document.querySelector("form.search");
  if (search) {
    var searchInput = search.querySelector("input");
    search.addEventListener("focusin", function () { search.classList.add("is-open"); });
    document.addEventListener("click", function (event) {
      if (!search.contains(event.target)) search.classList.remove("is-open");
    });
    document.addEventListener("keydown", function (event) {
      var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
      if (event.key === "/" && !typing) { event.preventDefault(); searchInput.focus(); searchInput.select(); }
      if (event.key === "Escape" && search.contains(document.activeElement)) {
        search.classList.remove("is-open");
        searchInput.blur();
      }
    });
  }

  /* ----- Password fields get a show and hide button ----- */
  var EYE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
    'stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/>' +
    '<circle cx="12" cy="12" r="3"/></svg>';
  document.querySelectorAll(".form input[type=password]").forEach(function (field) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "reveal-password";
    button.setAttribute("aria-label", "Show password");
    button.setAttribute("aria-pressed", "false");
    button.innerHTML = EYE;
    button.addEventListener("click", function () {
      var show = field.type === "password";
      field.type = show ? "text" : "password";
      button.setAttribute("aria-pressed", show ? "true" : "false");
      button.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
    field.style.paddingRight = "48px";
    field.parentElement.style.position = "relative";
    field.insertAdjacentElement("afterend", button);
  });

  /* ----- Dashboard numbers count up when the page opens ----- */
  if (!calm) {
    document.querySelectorAll("[data-countup]").forEach(function (node) {
      var target = Number(node.dataset.countup);
      if (!isFinite(target) || target <= 0) return;
      var prefix = node.dataset.prefix || "";
      var rest = node.querySelector("small");
      var started = null;
      function frame(now) {
        if (started === null) started = now;
        var progress = Math.min((now - started) / 700, 1);
        var eased = 1 - Math.pow(1 - progress, 3);
        var text = prefix + Math.round(target * eased).toLocaleString("en-US");
        if (rest) node.firstChild.textContent = text; else node.textContent = text;
        if (progress < 1) requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    });
  }

  /* ----- Sections below the first screen fade up as they scroll into view ----- */
  if (!calm && "IntersectionObserver" in window) {
    var watcher = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        watcher.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -8% 0px" });
    document.querySelectorAll(".container > .card, .container > section, .container > .grid, .reveal").forEach(function (node) {
      if (node.getBoundingClientRect().top < window.innerHeight) return;
      node.classList.add("reveal-ready");
      watcher.observe(node);
    });
  }

  /* ----- On a phone the tabs scroll sideways: bring the current one into view ----- */
  var currentTab = document.querySelector(".tabs a[aria-current=page]");
  if (currentTab) currentTab.scrollIntoView({ block: "nearest", inline: "center" });

  /* ----- Whole table rows are clickable ----- */
  document.addEventListener("click", function (event) {
    var row = event.target.closest("tr.row-link");
    if (!row || event.target.closest("a, button, input, select, textarea, form, summary")) return;
    window.location.href = row.dataset.href;
  });

  /* ----- Chat: show the question at once and a placeholder while the answer is written ----- */
  var chatForm = document.getElementById("chat-form");
  if (chatForm) {
    var box = document.getElementById("messages");
    var input = chatForm.querySelector("input[name=question]");
    var lastQuestion = "";

    function toBottom() {
      var last = box.lastElementChild;
      if (last) last.scrollIntoView({ behavior: "smooth", block: "end" });
    }
    function clearPending() {
      box.querySelectorAll("[data-pending]").forEach(function (node) { node.remove(); });
    }

    chatForm.addEventListener("htmx:beforeRequest", function () {
      lastQuestion = input.value.trim();
      var question = document.createElement("p");
      question.className = "question";
      question.dataset.pending = "";
      question.textContent = lastQuestion;
      var answer = document.createElement("div");
      answer.className = "answer is-pending";
      answer.dataset.pending = "";
      answer.setAttribute("aria-label", "The assistant is working on it");
      answer.innerHTML =
        '<div class="skeleton skeleton-line" style="width: 38%"></div>' +
        '<div class="skeleton skeleton-line" style="width: 92%"></div>' +
        '<div class="skeleton skeleton-line" style="width: 70%"></div>';
      box.append(question, answer);
      input.value = "";
      toBottom();
    });
    document.body.addEventListener("htmx:beforeSwap", clearPending);
    document.body.addEventListener("htmx:afterSwap", toBottom);
    ["htmx:responseError", "htmx:sendError", "htmx:timeout"].forEach(function (name) {
      document.body.addEventListener(name, function () {
        clearPending();
        var failed = document.createElement("div");
        failed.className = "answer";
        failed.textContent = "That did not go through. Please check your connection and try again.";
        box.append(failed);
        input.value = lastQuestion;
        toBottom();
      });
    });

    document.querySelectorAll("[data-suggest]").forEach(function (button) {
      button.addEventListener("click", function () {
        input.value = button.dataset.suggest;
        chatForm.requestSubmit();
      });
    });

    // Links in answers (such as payment links) open in a new tab.
    box.addEventListener("click", function (event) {
      var link = event.target.closest("a");
      if (link && !link.classList.contains("cite-open")) { link.target = "_blank"; link.rel = "noopener"; }
    });
    toBottom();
  }

  // Demo buttons on the login page fill in a sample account and log in.
  document.querySelectorAll("[data-demo-email]").forEach(function (button) {
    button.addEventListener("click", function () {
      var form = document.querySelector(".glass form");
      if (!form) { return; }
      form.querySelector("[name=username]").value = button.dataset.demoEmail;
      form.querySelector("[name=password]").value = button.dataset.demoPassword;
      form.requestSubmit();
    });
  });

  // "Copy link" buttons: copy the value of the field they point at.
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", function () {
      var field = document.querySelector(button.dataset.copy);
      if (!field) { return; }
      field.select();
      var done = function () {
        var label = button.textContent;
        button.textContent = "Copied";
        setTimeout(function () { button.textContent = label; }, 1600);
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(field.value).then(done, function () { document.execCommand("copy"); done(); });
      } else {
        document.execCommand("copy");
        done();
      }
    });
  });

  // Lease page viewer: bring the cited passage into view, and make "Back" return
  // to wherever the person came from (usually their chat) when that is known.
  var cited = document.getElementById("cited");
  if (cited) {
    setTimeout(function () { cited.scrollIntoView({ behavior: "smooth", block: "center" }); }, 250);
  }
  document.querySelectorAll("[data-back]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      if (document.referrer && new URL(document.referrer).origin === location.origin && history.length > 1) {
        event.preventDefault();
        history.back();
      }
    });
  });
})();
