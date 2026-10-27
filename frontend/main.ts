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

/**
 * Подтверждение опасных действий (закрытие комнаты, смена ID).
 * Кнопка с `data-confirm` не отправляет форму, пока пользователь не согласится.
 */
function setupConfirmButtons(): void {
  document.addEventListener("click", (event) => {
    const target = event.target as HTMLElement | null;
    const button = target?.closest<HTMLElement>("[data-confirm]");
    if (!button) return;

    const question = button.dataset.confirm ?? "Продолжить?";
    if (!window.confirm(question)) {
      event.preventDefault();
      event.stopPropagation();
    }
  });
}

function init(): void {
  markClientReady();
  setupConfirmButtons();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
