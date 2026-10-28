import htmx from "htmx.org";

import { setupPwa } from "./pwa";

/**
 * Точка входа клиента: HTMX, подтверждения и регистрация PWA (G1).
 * Модули аватара и записи жестов подключаются только на своих страницах.
 */
function markClientReady(): void {
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
  // PWA (G1): манифест и service worker. Регистрация не критична для работы.
  setupPwa();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
