/**
 * WebSocket-клиент комнаты (этап A8): подключение, presence и ping/pong.
 * Чат и события фраз подключатся на A9/A11.
 */

type PresenceEntry = {
  name: string;
  participant_id: number | null;
  guest: boolean;
  count: number;
};

type ServerEvent =
  | { type: "presence"; participants: PresenceEntry[] }
  | { type: "pong" }
  | { type: "room_closed" }
  | { type: string; [key: string]: unknown };

function isPresenceEvent(event: ServerEvent): event is { type: "presence"; participants: PresenceEntry[] } {
  return event.type === "presence" && Array.isArray((event as { participants?: unknown }).participants);
}

const PING_INTERVAL_MS = 20_000;
// На 4401/4403 переподключаться нельзя — доступа нет.
const NON_RETRYABLE_CODES = new Set([4401, 4403]);

function roomSocketUrl(joinCode: string): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws/rooms/${joinCode}/`;
}

function renderPresence(list: HTMLElement, participants: PresenceEntry[]): void {
  list.innerHTML = "";
  for (const person of participants) {
    const item = document.createElement("li");
    item.textContent = person.guest ? person.name : `${person.name} (преподаватель)`;
    list.append(item);
  }
}

export function setupRoomSocket(root: HTMLElement): void {
  const joinCode = root.dataset.joinCode;
  if (!joinCode) return;

  const status = root.querySelector<HTMLElement>("[data-socket-status]");
  const list = root.querySelector<HTMLElement>("[data-presence-list]");
  let pingTimer: number | undefined;

  const setStatus = (text: string, state: "loading" | "ready" | "error"): void => {
    if (status) {
      status.textContent = text;
      status.dataset.state = state;
    }
  };

  const connect = (): void => {
    setStatus("Подключение…", "loading");
    const socket = new WebSocket(roomSocketUrl(joinCode));

    socket.addEventListener("open", () => {
      setStatus("На связи", "ready");
      pingTimer = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "ping" }));
        }
      }, PING_INTERVAL_MS);
    });

    socket.addEventListener("message", (event: MessageEvent<string>) => {
      let payload: ServerEvent;
      try {
        payload = JSON.parse(event.data) as ServerEvent;
      } catch {
        return;
      }
      if (isPresenceEvent(payload) && list) {
        renderPresence(list, payload.participants);
      } else if (payload.type === "room_closed") {
        setStatus("Комната закрыта", "error");
      }
    });

    socket.addEventListener("close", (event: CloseEvent) => {
      window.clearInterval(pingTimer);
      if (NON_RETRYABLE_CODES.has(event.code)) {
        setStatus("Нет доступа к комнате", "error");
        return;
      }
      setStatus("Соединение потеряно, переподключение…", "loading");
      window.setTimeout(connect, 2_000);
    });

    socket.addEventListener("error", () => {
      setStatus("Ошибка соединения", "error");
    });
  };

  connect();
}

function init(): void {
  document.querySelectorAll<HTMLElement>("[data-room-socket]").forEach(setupRoomSocket);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
