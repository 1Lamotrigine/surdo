/**
 * Страница комнаты: крупный режим для проектора и копирование ссылки.
 */

function setupProjectorMode(): void {
  const button = document.querySelector<HTMLButtonElement>("[data-projector-toggle]");
  if (!button) return;

  const setActive = (active: boolean): void => {
    document.body.classList.toggle("projector-mode", active);
    button.setAttribute("aria-pressed", String(active));
    button.textContent = active ? "Выйти из крупного режима" : "Крупный режим";
  };

  button.addEventListener("click", async () => {
    const active = !document.body.classList.contains("projector-mode");
    setActive(active);

    try {
      if (active) {
        await document.documentElement.requestFullscreen?.();
      } else if (document.fullscreenElement) {
        await document.exitFullscreen();
      }
    } catch {
      // Полноэкранный режим может быть запрещён браузером — крупный вид всё равно работает.
    }
  });

  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement) {
      setActive(false);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (
      event.key === "Escape" &&
      document.body.classList.contains("projector-mode") &&
      !document.fullscreenElement
    ) {
      setActive(false);
    }
  });
}

function setupCopyLink(): void {
  const button = document.querySelector<HTMLButtonElement>("[data-copy-link]");
  const status = document.querySelector<HTMLElement>("[data-copy-status]");
  if (!button) return;

  button.addEventListener("click", async () => {
    const value = button.dataset.copyValue ?? "";
    if (!value) return;

    if (!navigator.clipboard) {
      if (status) status.textContent = "Скопируйте ссылку вручную.";
      return;
    }

    try {
      await navigator.clipboard.writeText(value);
      if (status) status.textContent = "Ссылка скопирована.";
      window.setTimeout(() => {
        if (status) status.textContent = "";
      }, 3000);
    } catch {
      if (status) status.textContent = "Не удалось скопировать ссылку.";
    }
  });
}

function setupRoomPage(): void {
  setupProjectorMode();
  setupCopyLink();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", setupRoomPage, { once: true });
} else {
  setupRoomPage();
}
