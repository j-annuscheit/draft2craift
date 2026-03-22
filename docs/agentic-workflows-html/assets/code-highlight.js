(function () {
  "use strict";

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function store(stash, cls, raw) {
    var key = "@@TOK" + stash.length + "@@";
    stash.push({
      key: key,
      html: '<span class="' + cls + '">' + escapeHtml(raw) + "</span>",
    });
    return key;
  }

  function restore(text, stash) {
    var out = String(text || "");
    for (var i = 0; i < stash.length; i += 1) {
      out = out.replace(stash[i].key, stash[i].html);
    }
    return out;
  }

  function detectLang(text) {
    var raw = String(text || "").trim();
    if (!raw) {
      return "text";
    }
    if (
      /^\s*\[\[?[A-Za-z0-9_.-]+\]?\]/m.test(raw) ||
      /\b(schema_version|workflow_id|profile_id|entry_step|terminal_steps)\s*=/.test(raw)
    ) {
      return "toml";
    }
    if (
      /(^|\n)\s*(from|import|def|class)\s+/.test(raw) ||
      /\b(StepOutcome|GraphSpec|return|yield)\b/.test(raw)
    ) {
      return "python";
    }
    if (
      /^\s*\{/.test(raw) ||
      /"type"\s*:/.test(raw) ||
      /"nodes"\s*:/.test(raw)
    ) {
      return "json";
    }
    if (
      /(^|\n)\s*(PYTHONPATH=|python\b|pytest\b|sed\b|rg\b|cd\b|git\b|ls\b)/.test(raw) ||
      /<<'PY'/.test(raw)
    ) {
      return "shell";
    }
    return "text";
  }

  function highlightToml(line) {
    if (/^\s*\[\[?[^\]]+\]\]?\s*$/.test(line)) {
      return '<span class="tok-type">' + escapeHtml(line) + "</span>";
    }
    var stash = [];
    var work = String(line || "");
    work = work.replace(/"(?:\\.|[^"])*"|'(?:\\.|[^'])*'/g, function (match) {
      return store(stash, "tok-str", match);
    });
    work = work.replace(/#.*/g, function (match) {
      return store(stash, "tok-comment", match);
    });
    work = escapeHtml(work);
    work = work.replace(
      /^(\s*)([A-Za-z0-9_.-]+)(\s*=)/,
      '$1<span class="tok-prop">$2</span>$3'
    );
    work = work.replace(/\b(true|false)\b/gi, '<span class="tok-bool">$1</span>');
    work = work.replace(/\b\d+(?:\.\d+)?\b/g, '<span class="tok-num">$&</span>');
    return restore(work, stash);
  }

  function highlightPython(line) {
    var stash = [];
    var work = String(line || "");
    work = work.replace(/"(?:\\.|[^"])*"|'(?:\\.|[^'])*'/g, function (match) {
      return store(stash, "tok-str", match);
    });
    work = work.replace(/#.*/g, function (match) {
      return store(stash, "tok-comment", match);
    });
    work = escapeHtml(work);
    work = work.replace(
      /\b(def|class)\b(\s+)([A-Za-z_][A-Za-z0-9_]*)/g,
      '<span class="tok-kw">$1</span>$2<span class="tok-fn">$3</span>'
    );
    work = work.replace(
      /\b(import|from|return|if|elif|else|for|while|in|try|except|with|as|pass|break|continue|or|and|not|lambda)\b/g,
      '<span class="tok-kw">$1</span>'
    );
    work = work.replace(/\b(True|False|None)\b/g, '<span class="tok-bool">$1</span>');
    work = work.replace(/\b\d+(?:\.\d+)?\b/g, '<span class="tok-num">$&</span>');
    return restore(work, stash);
  }

  function highlightJson(line) {
    var stash = [];
    var work = String(line || "");
    work = work.replace(/"(?:\\.|[^"])*"(?=\s*:)/g, function (match) {
      return store(stash, "tok-prop", match);
    });
    work = work.replace(/"(?:\\.|[^"])*"/g, function (match) {
      return store(stash, "tok-str", match);
    });
    work = escapeHtml(work);
    work = work.replace(/\b(true|false|null)\b/gi, '<span class="tok-bool">$1</span>');
    work = work.replace(/\b\d+(?:\.\d+)?\b/g, '<span class="tok-num">$&</span>');
    return restore(work, stash);
  }

  function highlightShell(line) {
    var stash = [];
    var work = String(line || "");
    work = work.replace(/"(?:\\.|[^"])*"|'(?:\\.|[^'])*'/g, function (match) {
      return store(stash, "tok-str", match);
    });
    work = work.replace(/#.*/g, function (match) {
      return store(stash, "tok-comment", match);
    });
    work = escapeHtml(work);
    work = work.replace(
      /\b([A-Z][A-Z0-9_]*)(=)/g,
      '<span class="tok-prop">$1</span>$2'
    );
    work = work.replace(
      /\b(python|pytest|sed|rg|cd|git|ls|cat|printf)\b/g,
      '<span class="tok-fn">$1</span>'
    );
    work = work.replace(/(^|\s)(--?[A-Za-z0-9_.-]+)/g, '$1<span class="tok-flag">$2</span>');
    work = work.replace(/\b\d+(?:\.\d+)?\b/g, '<span class="tok-num">$&</span>');
    return restore(work, stash);
  }

  function highlightText(line) {
    return escapeHtml(line);
  }

  function highlightBlock(code) {
    var text = code.textContent.replace(/\r\n?/g, "\n");
    var lang = detectLang(text);
    var lines = text.split("\n");
    var renderer = highlightText;
    if (lang === "toml") {
      renderer = highlightToml;
    } else if (lang === "python") {
      renderer = highlightPython;
    } else if (lang === "json") {
      renderer = highlightJson;
    } else if (lang === "shell") {
      renderer = highlightShell;
    }
    code.innerHTML = lines.map(renderer).join("\n");
    code.setAttribute("data-lang", lang);
    if (code.parentElement) {
      code.parentElement.classList.add("code-editor");
      code.parentElement.setAttribute("data-lang", lang);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var blocks = document.querySelectorAll("pre code");
    for (var i = 0; i < blocks.length; i += 1) {
      highlightBlock(blocks[i]);
    }
  });
})();
