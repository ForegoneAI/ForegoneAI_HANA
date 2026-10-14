import type { DealProfile } from "./api";

/** How a field's value is entered and shown. */
export type FieldKind = "text" | "longtext" | "money" | "percent" | "integer" | "number" | "year";

export interface FieldSpec {
  name: string;
  label: string;
  kind: FieldKind;
  /** May be negative (NOI: a property can operate at a loss). */
  signed?: boolean;
}

export interface FieldGroup {
  id: string;
  title: string;
  fields: FieldSpec[];
}

/**
 * The REPEDealProfile value fields (backend/app/h9n/schemas/repe_deal.py and
 * base_deal.py), grouped the way a reviewer reads a deal (M2.2). The schema
 * has no separate assumption fields yet, so "Strategy & assumptions" holds
 * the investment strategy and business plan.
 */
export const FIELD_GROUPS: FieldGroup[] = [
  {
    id: "property",
    title: "Property",
    fields: [
      { name: "property_name", label: "Property name", kind: "text" },
      { name: "property_type", label: "Property type", kind: "text" },
      { name: "address", label: "Address", kind: "text" },
      { name: "location", label: "Location", kind: "text" },
      { name: "market", label: "Market", kind: "text" },
      { name: "submarket", label: "Submarket", kind: "text" },
      { name: "units", label: "Units", kind: "integer" },
      { name: "square_feet", label: "Square feet", kind: "number" },
      { name: "year_built", label: "Year built", kind: "year" },
    ],
  },
  {
    id: "transaction",
    title: "Transaction",
    fields: [
      { name: "deal_name", label: "Deal name", kind: "text" },
      { name: "transaction_type", label: "Transaction type", kind: "text" },
      { name: "asking_price", label: "Asking price", kind: "money" },
      { name: "cap_rate", label: "Cap rate", kind: "percent" },
    ],
  },
  {
    id: "operations",
    title: "Operations",
    fields: [
      { name: "occupancy_rate", label: "Occupancy", kind: "percent" },
      { name: "annual_revenue", label: "Annual revenue", kind: "money" },
      { name: "operating_expenses", label: "Operating expenses", kind: "money" },
      { name: "noi", label: "NOI", kind: "money", signed: true },
    ],
  },
  {
    id: "financing",
    title: "Financing",
    fields: [
      { name: "loan_amount", label: "Loan amount", kind: "money" },
      { name: "interest_rate", label: "Interest rate", kind: "percent" },
      { name: "ltv", label: "LTV", kind: "percent" },
      { name: "loan_term_years", label: "Loan term (years)", kind: "integer" },
    ],
  },
  {
    id: "sponsor",
    title: "Sponsor",
    fields: [
      { name: "sponsor_name", label: "Sponsor", kind: "text" },
      { name: "sponsor_equity", label: "Sponsor equity", kind: "money" },
    ],
  },
  {
    id: "assumptions",
    title: "Strategy & assumptions",
    fields: [
      { name: "investment_strategy", label: "Investment strategy", kind: "longtext" },
      { name: "business_plan", label: "Business plan", kind: "longtext" },
    ],
  },
];

export const ALL_FIELDS: FieldSpec[] = FIELD_GROUPS.flatMap((group) => group.fields);

export type FieldValue = string | number | null;

/** A field's value as shown to a reviewer, e.g. "$12,500,000" or "6.5%". */
export function formatValue(kind: FieldKind, value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value !== "number") return String(value);
  switch (kind) {
    case "money":
      return `$${value.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
    case "percent":
      return `${value.toLocaleString("en-US", { maximumFractionDigits: 4 })}%`;
    case "year":
      return String(value);
    default:
      return value.toLocaleString("en-US", { maximumFractionDigits: 4 });
  }
}

/** A field's value as it starts out in its input box: plain, no symbols. */
export function toInput(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

/**
 * Reads what a reviewer typed into a field. Empty means "no value" (null).
 * Numbers may include $, %, commas and spaces ("$12,500,000", "6.5%").
 * Percentages are the number itself, as the extractor stores them: 6.5 is
 * 6.5%, so a fraction like 0.065 is probably a mistake and is refused.
 */
export function parseInput(field: FieldSpec, raw: string): { value: FieldValue } | { error: string } {
  const { kind } = field;
  const text = raw.trim();
  if (text === "") return { value: null };
  if (kind === "text" || kind === "longtext") return { value: text };

  const cleaned = text.replace(/[$,%\s]/g, "");
  if (!/^-?\d+(\.\d+)?$/.test(cleaned)) return { error: "Enter a number." };
  const value = Number(cleaned);

  switch (kind) {
    case "percent":
      if (value < 0 || value > 100) return { error: "Enter a percentage between 0 and 100 (6.5 means 6.5%)." };
      return { value };
    case "integer":
      if (!Number.isInteger(value) || value < 0) return { error: "Enter a whole number." };
      return { value };
    case "year":
      if (!Number.isInteger(value) || value < 1700 || value > 2100) return { error: "Enter a year, e.g. 1998." };
      return { value };
    case "money":
    case "number":
      if (value < 0 && !field.signed) return { error: "Enter a number that isn't negative." };
      return { value };
  }
}

/** Two field values are the same value (so saving it changes nothing). */
export function sameValue(a: unknown, b: unknown): boolean {
  return (a ?? null) === (b ?? null);
}

/** The profile's current value for a field. */
export function valueOf(profile: DealProfile, field: string): FieldValue {
  const value = profile[field];
  return typeof value === "string" || typeof value === "number" ? value : null;
}
