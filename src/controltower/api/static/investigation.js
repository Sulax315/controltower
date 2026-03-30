(() => {
  const shells = document.querySelectorAll("[data-investigation-shell]");

  const closeShellPanels = (shell) => {
    const panels = shell.querySelectorAll("[data-investigation-panel]");
    const triggers = shell.querySelectorAll("[data-investigation-open]");
    const backdrop = shell.querySelector(".investigation-backdrop");

    panels.forEach((panel) => {
      panel.dataset.panelState = "closed";
      panel.setAttribute("aria-hidden", "true");
    });
    triggers.forEach((trigger) => {
      trigger.setAttribute("aria-expanded", "false");
    });
    if (backdrop) {
      backdrop.dataset.panelState = "closed";
    }
  };

  shells.forEach((shell) => {
    closeShellPanels(shell);

    const backdrop = shell.querySelector(".investigation-backdrop");
    shell.querySelectorAll("[data-investigation-open]").forEach((trigger) => {
      trigger.addEventListener("click", () => {
        const panelId = trigger.getAttribute("data-investigation-open");
        const panel = panelId ? shell.querySelector(`#${panelId}`) : null;
        if (!panel) {
          return;
        }
        const nextState = panel.dataset.panelState === "open" ? "closed" : "open";
        closeShellPanels(shell);
        if (nextState === "open") {
          panel.dataset.panelState = "open";
          panel.setAttribute("aria-hidden", "false");
          trigger.setAttribute("aria-expanded", "true");
          if (backdrop) {
            backdrop.dataset.panelState = "open";
          }
        }
      });
    });

    shell.querySelectorAll("[data-investigation-close]").forEach((control) => {
      control.addEventListener("click", () => closeShellPanels(shell));
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
      return;
    }
    shells.forEach((shell) => closeShellPanels(shell));
  });

  const copySourceValue = (sourceId) => {
    if (!sourceId) {
      return "";
    }
    const source = document.getElementById(sourceId);
    if (!source) {
      return "";
    }
    if ("value" in source) {
      return source.value;
    }
    return source.textContent || "";
  };

  document.querySelectorAll("[data-copy-source]").forEach((button) => {
    button.addEventListener("click", async () => {
      const sourceId = button.getAttribute("data-copy-source");
      const text = copySourceValue(sourceId);
      if (!text) {
        return;
      }
      try {
        await navigator.clipboard.writeText(text);
        button.setAttribute("data-copy-state", "copied");
        const originalText = button.textContent;
        button.textContent = "Copied";
        window.setTimeout(() => {
          button.textContent = originalText;
          button.removeAttribute("data-copy-state");
        }, 1400);
      } catch (_error) {
        if (navigator.clipboard && window.isSecureContext) {
          return;
        }
        const fallback = document.createElement("textarea");
        fallback.value = text;
        fallback.setAttribute("readonly", "true");
        fallback.style.position = "absolute";
        fallback.style.left = "-9999px";
        document.body.appendChild(fallback);
        fallback.select();
        document.execCommand("copy");
        document.body.removeChild(fallback);
      }
    });
  });

  document.querySelectorAll("[data-print-trigger]").forEach((button) => {
    button.addEventListener("click", () => window.print());
  });

  document.querySelectorAll("[data-proofpack-toggle]").forEach((button) => {
    const targetId = button.getAttribute("data-proofpack-toggle");
    const target = targetId ? document.getElementById(targetId) : null;
    if (!target) {
      return;
    }

    const items = Array.from(target.querySelectorAll("details"));
    const expandLabel = button.getAttribute("data-expand-label") || "Expand Proof Pack";
    const collapseLabel = button.getAttribute("data-collapse-label") || "Collapse Proof Pack";
    const updateLabel = () => {
      const allOpen = items.length > 0 && items.every((item) => item.open);
      button.textContent = allOpen ? collapseLabel : expandLabel;
    };

    button.addEventListener("click", () => {
      const shouldOpen = !(items.length > 0 && items.every((item) => item.open));
      const pack = target.closest("details");
      if (pack && shouldOpen) {
        pack.open = true;
      }
      items.forEach((item) => {
        item.open = shouldOpen;
      });
      updateLabel();
    });

    items.forEach((item) => item.addEventListener("toggle", updateLabel));
    updateLabel();
  });

  const params = new URLSearchParams(window.location.search);
  if (params.get("print") === "1" && document.body.classList.contains("publish")) {
    window.setTimeout(() => window.print(), 120);
  }
})();
