/**
 * Живой клиент комнаты (A8+A9): одно WebSocket-соединение на страницу.
 * Обрабатывает presence, историю и чат; ping раз в 20 с.
 */

type PresenceEntry = {
  name: string;
  participant_id: number | null;
  guest: boolean;
  count: number;
};

type ChatMessage = {
  id: number;
  user: string;
  body: string;
  ts: string;
  is_teacher: boolean;
};

type ServerEvent =
  | { type: "presence"; participants: PresenceEntry[] }
  | { type: "chat_history"; messages: ChatMessage[] }
  | { type: "chat_message"; message: ChatMessage }
  | { type: "chat_error"; error: string; retry_after?: number }
  | { type: "pong" }
  | { type: "room_closed" }
  | { type: "participant_removed" }
  | { type: string; [key: string]: unknown };

const PING_INTERVAL_MS = 20_000;
const NON_RETRYABLE_CODES = new Set([4401, 4403]);

function isEvent<T extends ServerEvent["type"]>(
  payload: ServerEvent,
  type: T,
): payload is Extract<ServerEvent, { type: T }> {
  return payload.type === type;
}

function roomSocketUrl(joinCode: string): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws/rooms/${joinCode}/`;
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export function setupRoomLive(root: HTMLElement): void {
  const joinCode = root.dataset.joinCode;
  if (!joinCode) return;

  const status = root.querySelector<HTMLElement>("[data-socket-status]");
  const presenceList = root.querySelector<HTMLElement>("[data-presence-list]");
  const chatLog = root.querySelector<HTMLElement>("[data-chat-log]");
  const chatForm = root.querySelector<HTMLFormElement>("[data-chat-form]");
  const chatInput = root.querySelector<HTMLTextAreaElement>("[data-chat-input]");
  const chatHint = root.querySelector<HTMLElement>("[data-chat-hint]");
  const isTeacherView = root.hasAttribute("data-teacher-view");
  const removeParticipantUrl = root.dataset.removeParticipantUrl;
  const csrfToken = root.dataset.csrfToken;
  let pingTimer: number | undefined;
  let socket: WebSocket | undefined;
  let lastMessageId = 0;
  let closed = false;

  const setStatus = (text: string, state: "loading" | "ready" | "error"): void => {
    if (status) {
      status.textContent = text;
      status.dataset.state = state;
    }
  };

  const removeParticipant = (participantId: number): void => {
    if (!removeParticipantUrl) return;
    const form = document.createElement("form");
    form.method = "post";
    // URL шаблона приходит с id=0: /rooms/<code>/participants/0/remove/.
    form.action = removeParticipantUrl.replace("/0/", `/${participantId}/`);

    const token = document.createElement("input");
    token.type = "hidden";
    token.name = "csrfmiddlewaretoken";
    token.value = csrfToken ?? "";
    form.append(token);

    document.body.append(form);
    form.submit();
  };

  const renderPresence = (participants: PresenceEntry[]): void => {
    if (!presenceList) return;
    presenceList.innerHTML = "";
    for (const person of participants) {
      const item = document.createElement("li");
      item.className = "presence-item";
      const label = document.createElement("span");
      label.textContent = person.guest ? person.name : `${person.name} (преподаватель)`;
      item.append(label);

      if (isTeacherView && person.participant_id != null) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "button button-secondary button-small";
        button.textContent = "Удалить";
        button.addEventListener("click", () => {
          if (window.confirm(`Удалить ${person.name} из комнаты?`)) {
            removeParticipant(person.participant_id as number);
          }
        });
        item.append(button);
      }
      presenceList.append(item);
    }
  };

  const appendMessage = (message: ChatMessage): void => {
    if (!chatLog || message.id <= lastMessageId) return;
    lastMessageId = message.id;

    const item = document.createElement("li");
    item.className = message.is_teacher ? "chat-item chat-item-teacher" : "chat-item";

    const meta = document.createElement("p");
    meta.className = "chat-meta";
    meta.textContent = `${message.user} · ${formatTime(message.ts)}`;

    const body = document.createElement("p");
    body.className = "chat-body";
    body.textContent = message.body;

    item.append(meta, body);
    chatLog.append(item);
    chatLog.scrollTop = chatLog.scrollHeight;
  };

  const renderHistory = (messages: ChatMessage[]): void => {
    if (!chatLog) return;
    chatLog.innerHTML = "";
    lastMessageId = 0;
    for (const message of messages) appendMessage(message);
  };

  const connect = (): void => {
    setStatus("Подключение…", "loading");
    socket = new WebSocket(roomSocketUrl(joinCode));

    socket.addEventListener("open", () => {
      setStatus("На связи", "ready");
      pingTimer = window.setInterval(() => {
        if (socket?.readyState === WebSocket.OPEN) {
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
      if (isEvent(payload, "presence")) {
        renderPresence(payload.participants);
      } else if (isEvent(payload, "chat_history")) {
        renderHistory(payload.messages);
      } else if (isEvent(payload, "chat_message")) {
        appendMessage(payload.message);
      } else if (isEvent(payload, "chat_error") && chatHint) {
        chatHint.textContent =
          payload.error === "rate_limited"
            ? "Слишком часто. Подождите несколько секунд."
            : payload.error;
      } else if (payload.type === "room_closed") {
        closed = true;
        setStatus("Комната закрыта", "error");
      } else if (payload.type === "participant_removed") {
        closed = true;
        setStatus("Преподаватель удалил вас из комнаты", "error");
      }
    });

    socket.addEventListener("close", (event: CloseEvent) => {
      window.clearInterval(pingTimer);
      if (closed || NON_RETRYABLE_CODES.has(event.code)) {
        setStatus(closed ? status?.textContent ?? "Комната недоступна" : "Нет доступа к комнате", "error");
        return;
      }
      setStatus("Соединение потеряно, переподключение…", "loading");
      window.setTimeout(connect, 2_000);
    });

    socket.addEventListener("error", () => {
      setStatus("Ошибка соединения", "error");
    });
  };

  chatForm?.addEventListener("submit", (event: SubmitEvent) => {
    event.preventDefault();
    const body = chatInput?.value.trim() ?? "";
    if (!body || !socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "chat", body }));
    if (chatInput) chatInput.value = "";
    if (chatHint) chatHint.textContent = "";
  });

  connect();
}

function init(): void {
  document.querySelectorAll<HTMLElement>("[data-room-live]").forEach(setupRoomLive);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
