/**
 * Optional: download the latest ECB euro reference rates straight from the phone.
 * Free, no key; reuse allowed with attribution. If the browser cannot reach the ECB
 * (offline, or the site refuses direct browser access), rates can be entered by hand.
 */
import { headerIndex, parseCsv } from "./csv";

export const ECB_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D..EUR.SP00.A?lastNObservations=1&format=csvdata";
export const ECB_SOURCE = "ECB euro reference rate";

export type EcbRate = { currency: string; date: string; value: string };

export function parseEcbCsv(text: string): EcbRate[] {
  const rows = parseCsv(text);
  if (rows.length < 2) return [];
  const c = headerIndex(rows[0], { currency: ["currency"], date: ["time_period"], value: ["obs_value"] });
  if (c.currency === undefined || c.date === undefined || c.value === undefined) return [];
  return rows
    .slice(1)
    .map((r) => ({ currency: (r[c.currency!] ?? "").trim(), date: (r[c.date!] ?? "").trim(), value: (r[c.value!] ?? "").trim() }))
    .filter((r) => /^[A-Z]{3}$/.test(r.currency) && /^\d{4}-\d{2}-\d{2}$/.test(r.date) && Number(r.value) > 0);
}

export async function fetchEcbRates(): Promise<EcbRate[]> {
  let res: Response;
  try {
    res = await fetch(ECB_URL, { headers: { Accept: "text/csv" }, cache: "no-store" });
  } catch {
    throw new Error("Could not reach the ECB from this browser (offline, or direct access is not allowed). Enter the rates you need by hand.");
  }
  if (!res.ok) throw new Error(`The ECB answered with an error (${res.status}). Try later or enter rates by hand.`);
  const rates = parseEcbCsv(await res.text());
  if (!rates.length) throw new Error("The ECB response could not be read. Enter rates by hand.");
  return rates;
}
