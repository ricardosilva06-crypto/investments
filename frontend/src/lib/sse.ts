/** POST a JSON body and consume a text/event-stream response. */
export async function postSSE(
  path: string,
  body: unknown,
  onEvent: (event: string, data: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Requested-With": "InvestorIntelligence" },
    body: JSON.stringify(body),
    credentials: "same-origin",
    signal,
  });
  if (!res.ok || !res.body) {
    const j = await res.json().catch(() => null);
    const detail = j && typeof j.detail === "string" ? j.detail : Array.isArray(j?.detail) ? j.detail.map((d: { msg: string }) => d.msg).join(" · ") : `Request failed (${res.status})`;
    throw new Error(detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      try {
        onEvent(event, data ? JSON.parse(data) : null);
      } catch {
        onEvent(event, data);
      }
    }
  }
}
