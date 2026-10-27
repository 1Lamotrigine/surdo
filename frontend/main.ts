import htmx from "htmx.org";

/**
 * Точка входа клиента. На этапе A3 здесь только проверка сборки и HTMX;
 * модули аватара, записи жестов и PWA появятся позже.
 */
function markClientReady(): void {
  const status = document.querySelector<HTMLElement>("[data-client-status]");
  if (status) {
    status.dataset.state = "ready";
    status.textContent = `Клиент: Vite + HTMX ${htmx.version}`;
  }
  document.documentElement.dataset.htmxVersion = htmx.version;
  console.info(`[client] Vite module loaded, HTMX ${htmx.version}`);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", markClientReady, { once: true });
} else {
  markClientReady();
}
