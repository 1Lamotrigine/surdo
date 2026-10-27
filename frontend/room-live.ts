/**
 * Живой клиент комнаты (A8–A11): одно WebSocket-соединение на страницу.
 * Presence, история и чат; ping раз в 20 с (heartbeat), переподключение с
 * нарастающей паузой (1, 2, 4, 8 с, потолок 15 с) и догрузка пропущенного.
 * На странице студента дополнительно держит экран включённым и уведомляет
 * подсветкой/вибрацией (C8).
 */

import {
  ScreenNotifier,
  ScreenWakeLock,
  notificationKindFor,
  type NotificationKind,
} from "./notifications";
import type { UtteranceEvent } from "./room-clips";

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
  | { type: "asr_text"; text: string }
  | { type: "utterance"; utterance: UtteranceEvent }
  | { type: "lag_status"; lag_ms: number; level: string }
  | { type: "unknown_words"; words: string[] }
  | { type: "pong" }
  | { type: "room_closed" }
  | { type: "participant_removed" }
  | { type: string; [key: string]: unknown };

// Heartbeat и переподключение (ТЗ 7.6): ping раз в 20 с, пауза 1,2,4,8…15 с.
const PING_INTERVAL_MS = 20_000;
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 15_000;
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
  const isStudentView = root.hasAttribute("data-student-view");
  const wakeLockStatus = root.querySelector<HTMLElement>("[data-wake-lock-status]");
  const liveCaption = root.querySelector<HTMLElement>("[data-room-live-caption]");
  const lagPanel = root.querySelector<HTMLElement>("[data-lag-panel]");
  const lagValue = root.querySelector<HTMLElement>("[data-lag-value]");
  const lagHint = root.querySelector<HTMLElement>("[data-lag-hint]");
  const unknownWordsList = root.querySelector<HTMLElement>("[data-unknown-words]");
  const removeParticipantUrl = root.dataset.removeParticipantUrl;
  const csrfToken = root.dataset.csrfToken;
  let pingTimer: number | undefined;
  let socket: WebSocket | undefined;
  let lastMessageId = 0;
  let lastSeq = 0;
  let reconnectAttempt = 0;
  let closed = false;

  type PhraseController = {
    enqueue(utterance: UtteranceEvent): boolean;
    dispose(): void;
  };
  let phrasePlayer: Promise<PhraseController> | null = null;

  /** E4: сообщить серверу, что фраза действительно начала показываться. */
  const sendDisplayStarted = (utterance: UtteranceEvent): void => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(
      JSON.stringify({
        type: "display_started",
        utterance_id: utterance.id,
        ts: Date.now(),
      }),
    );
  };

  /**
   * Тяжёлый аватар/плеер грузится только на странице студента и только когда
   * пришла первая фраза. До этого субтитры `asr_text` показывает room-live.
   */
  const getPhrasePlayer = (): Promise<PhraseController> | null => {
    if (!isStudentView || !root.querySelector("[data-room-avatar-stage]")) return null;
    phrasePlayer ??= import("./room-phrase")
      .then((module) =>
        module.createRoomPhrasePlayer(root, {
          onDisplayStarted: (utterance) => sendDisplayStarted(utterance),
        }),
      )
      .catch((error: unknown) => {
        phrasePlayer = null;
        setStatus("Не удалось загрузить аватар: показываем субтитры.", "error");
        throw error;
      });
    return phrasePlayer;
  };

  const showLiveCaption = (text: string): void => {
    if (!liveCaption) return;
    liveCaption.textContent = text;
    liveCaption.hidden = false;
  };

  const hideLiveCaption = (): void => {
    if (liveCaption) liveCaption.hidden = true;
  };

  /** E4: индикатор FR-15. Уровень считает сервер, клиент только показывает. */
  const renderLagStatus = (lagMs: number, level: string): void => {
    const safeLag = Number.isFinite(lagMs) ? Math.max(0, lagMs) : 0;
    const safeLevel = level === "yellow" || level === "red" ? level : "green";
    const seconds = (safeLag / 1000).toLocaleString("ru-RU", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    });
    if (lagPanel) lagPanel.dataset.level = safeLevel;
    if (lagValue) lagValue.textContent = `${seconds} с`;
    if (lagHint) {
      lagHint.textContent =
        safeLevel === "red"
          ? "Замедлитесь: аватар отстаёт больше чем на 10 секунд."
          : safeLevel === "yellow"
            ? "Отставание растёт — говорите короче."
            : "Отставание в норме.";
    }
  };

  /** E4: слова последней фразы, для которых в словаре нет проверенного жеста. */
  const renderUnknownWords = (words: string[]): void => {
    if (!unknownWordsList) return;
    unknownWordsList.innerHTML = "";
    if (words.length === 0) {
      const empty = document.createElement("li");
      empty.className = "unknown-word-empty";
      empty.textContent = "Все слова есть в словаре.";
      unknownWordsList.append(empty);
      return;
    }
    for (const word of words) {
      const item = document.createElement("li");
      item.className = "unknown-word";
      item.textContent = word;
      unknownWordsList.append(item);
    }
  };

  // C8: уведомления и Wake Lock только на странице студента, не в панели.
  const notifier = isStudentView ? new ScreenNotifier(root) : null;
  const wakeLock = isStudentView ? new ScreenWakeLock() : null;

  const setWakeLockStatus = (text: string, state: "on" | "off" | "pending"): void => {
    if (!wakeLockStatus) return;
    wakeLockStatus.textContent = text;
    wakeLockStatus.dataset.state = state;
  };

  const notifyStudent = (kind: NotificationKind | null): void => {
    if (kind) notifier?.notify(kind);
  };

  const announceWakeLock = (active: boolean): void => {
    setWakeLockStatus(
      active
        ? "Экран не погаснет, пока открыта комната."
        : "Не удалось удержать экран включённым.",
      active ? "on" : "off",
    );
  };

  const stopStudentFeatures = (): void => {
    void wakeLock?.disable();
    if (wakeLock?.supported) setWakeLockStatus("Удержание экрана снято.", "off");
    notifier?.clear();
  };

  if (wakeLock) {
    if (!wakeLock.supported) {
      setWakeLockStatus("Браузер не поддерживает удержание экрана.", "off");
    } else {
      setWakeLockStatus("Удерживаем экран включённым…", "pending");
      void wakeLock.enable().then(announceWakeLock);
      // Некоторые браузеры дают Wake Lock только после касания — повторяем
      // один раз при первом взаимодействии, если с первого раза не вышло.
      window.addEventListener(
        "pointerdown",
        () => {
          if (wakeLock.active) return;
          void wakeLock.enable().then(announceWakeLock);
        },
        { once: true },
      );
    }
  }

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

  /** Догрузить пропущенное после обрыва; дубликаты отсекаются по id и seq. */
  const fetchMissed = async (): Promise<void> => {
    const params = new URLSearchParams();
    if (lastSeq > 0) params.set("after_seq", String(lastSeq));
    if (lastMessageId > 0) params.set("after_message_id", String(lastMessageId));
    const url = `/api/rooms/${joinCode}/history/?${params.toString()}`;

    try {
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      if (!response.ok) return;
      const data = (await response.json()) as {
        messages?: ChatMessage[];
        utterances?: UtteranceEvent[];
      };
      for (const message of data.messages ?? []) appendMessage(message);
      const missed = (data.utterances ?? [])
        .filter((utterance) => utterance.seq > lastSeq)
        .sort((left, right) => left.seq - right.seq);
      for (const utterance of missed) {
        lastSeq = utterance.seq;
        getPhrasePlayer()
          ?.then((player) => {
            player.enqueue(utterance);
            hideLiveCaption();
          })
          .catch(() => undefined);
      }
    } catch {
      // Не критично: следующее переподключение попробует снова.
    }
  };

  const connect = (): void => {
    setStatus("Подключение…", "loading");
    socket = new WebSocket(roomSocketUrl(joinCode));

    socket.addEventListener("open", () => {
      setStatus("На связи", "ready");
      const reconnected = reconnectAttempt > 0;
      reconnectAttempt = 0;
      if (reconnected) void fetchMissed();
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
        notifyStudent(
          notificationKindFor(
            { type: "chat_message", is_teacher: payload.message.is_teacher },
            isStudentView,
          ),
        );
      } else if (isEvent(payload, "asr_text")) {
        showLiveCaption(payload.text);
      } else if (isEvent(payload, "utterance")) {
        const utterance = payload.utterance;
        if (utterance && utterance.seq > lastSeq) {
          lastSeq = utterance.seq;
          notifyStudent(notificationKindFor({ type: "utterance" }, isStudentView));
          getPhrasePlayer()
            ?.then((player) => {
              player.enqueue(utterance);
              hideLiveCaption();
            })
            .catch(() => undefined);
        } else {
          hideLiveCaption();
        }
      } else if (isEvent(payload, "lag_status")) {
        renderLagStatus(payload.lag_ms, payload.level);
      } else if (isEvent(payload, "unknown_words")) {
        if (isTeacherView) renderUnknownWords(payload.words);
      } else if (isEvent(payload, "chat_error") && chatHint) {
        chatHint.textContent =
          payload.error === "rate_limited"
            ? "Слишком часто. Подождите несколько секунд."
            : payload.error;
      } else if (payload.type === "room_closed") {
        closed = true;
        setStatus("Комната закрыта", "error");
        stopStudentFeatures();
      } else if (payload.type === "participant_removed") {
        closed = true;
        setStatus("Преподаватель удалил вас из комнаты", "error");
        stopStudentFeatures();
      }
    });

    socket.addEventListener("close", (event: CloseEvent) => {
      window.clearInterval(pingTimer);
      if (closed || NON_RETRYABLE_CODES.has(event.code)) {
        setStatus(closed ? status?.textContent ?? "Комната недоступна" : "Нет доступа к комнате", "error");
        return;
      }
      const delay = Math.min(RECONNECT_BASE_MS * 2 ** reconnectAttempt, RECONNECT_MAX_MS);
      reconnectAttempt += 1;
      setStatus(`Соединение потеряно, переподключение через ${Math.round(delay / 1000)} с…`, "loading");
      window.setTimeout(connect, delay);
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

  // Уход со страницы: снять Wake Lock и подсветку, чтобы не держать экран
  // включённым в фоне и не оставлять класс на body.
  window.addEventListener(
    "pagehide",
    () => {
      window.clearInterval(pingTimer);
      void wakeLock?.disable();
      notifier?.dispose();
      phrasePlayer?.then((player) => player.dispose()).catch(() => undefined);
      phrasePlayer = null;
    },
    { once: true },
  );

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
