// Wire types — mirror Memory.to_dict() / MemoryEvent.to_dict() 1:1.
// Server is the source of truth; these are JSON-shaped, not class-shaped.

export type EventSource = "store" | "evolver" | "agent" | "user" | "system";

export interface Source {
  document_id: string;
  chunk_id?: string | null;
  span?: [number, number] | null;
  uri?: string | null;
  authority?: number | null;
  retrieved_at?: string | null;
}

export interface Memory {
  id: string;
  type: string;
  content: string;
  confidence: number;
  timestamp: string;             // ISO 8601
  updated_at: string;            // ISO 8601
  subject?: string | null;
  tags: string[];
  workspace: string;
  sources: Source[];
  superseded_by?: string | null;
  metadata: Record<string, unknown>;
  status?: string | null;
}

/** Inbound memory shape for ``add()`` — server fills in id / timestamps. */
export interface MemoryInput {
  type: string;
  content: string;
  confidence?: number;
  subject?: string | null;
  tags?: string[];
  workspace?: string;
  sources?: Source[];
  metadata?: Record<string, unknown>;
  status?: string | null;
  id?: string;                   // honoured if you're migrating data
  timestamp?: string;            // honoured if you're migrating data
}

export interface MemoryEvent {
  id: string;
  memory_id: string;
  workspace: string;
  type?: string | null;
  subject?: string | null;
  action: string;
  source: EventSource;
  source_name?: string | null;
  reason: string;
  input_ids: string[];
  output_ids: string[];
  payload: Record<string, unknown>;
  timestamp: string;             // ISO 8601
}

export interface ScoredMemory {
  score: number;
  memory: Memory;
}

export interface EvolutionRecord {
  evolver: string;
  action: string;
  input_ids: string[];
  output_ids: string[];
  reason: string;
  timestamp: string;
}

export interface ReflectReport {
  contradictions: Memory[][];
  drift_records: EvolutionRecord[];
  goal_records: EvolutionRecord[];
}

export interface VersionInfo {
  typedmem: string;
  instance: string;
}
