/**
 * Точка входа тестовой страницы аватара (C1): `GET /avatar/`.
 * Создаёт `Avatar`, грузит VRM по адресу из поля и показывает состояние.
 */

import { Avatar, type AvatarStatus } from "./avatar";

const STATUS_LABELS: Record<AvatarStatus, string> = {
  loading: "Загрузка…",
  ready: "Готово",
  error: "Ошибка",
};

function setupAvatarPage(root: HTMLElement): void {
  const stage = root.querySelector<HTMLElement>("[data-avatar-stage]");
  const status = root.querySelector<HTMLElement>("[data-avatar-status]");
  const form = root.querySelector<HTMLFormElement>("[data-avatar-form]");
  const urlInput = root.querySelector<HTMLInputElement>("[data-avatar-url]");
  if (!stage) return;

  const setStatus = (state: AvatarStatus, detail?: string): void => {
    if (!status) return;
    status.dataset.state = state;
    status.textContent = detail ? `${STATUS_LABELS[state]}: ${detail}` : STATUS_LABELS[state];
  };

  const avatar = new Avatar({
    container: stage,
    background: root.dataset.avatarBackground || undefined,
    onStatus: setStatus,
  });

  const initialUrl = root.dataset.avatarModelUrl?.trim();
  void avatar.load(initialUrl || undefined);

  form?.addEventListener("submit", (event: SubmitEvent) => {
    event.preventDefault();
    const url = urlInput?.value.trim();
    if (url) void avatar.load(url);
  });

  // Освобождаем WebGL при уходе со страницы (переход назад, закрытие вкладки).
  window.addEventListener("pagehide", () => avatar.dispose(), { once: true });
}

function init(): void {
  document.querySelectorAll<HTMLElement>("[data-avatar-page]").forEach(setupAvatarPage);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
